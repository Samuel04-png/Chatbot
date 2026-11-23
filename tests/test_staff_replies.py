"""Staff replies through the real API, the rudo_sender login and the production migration functions.
WhatsApp is a fake sender; nothing leaves the machine."""
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from app import create_app
from conftest import TEST_DSN
from rudo.observer import reference
from rudo.replies import StaffReplies
from rudo.synthetic import PHONES, SOURCE, SyntheticVerifier, bootstrap, clear_source, sender_dsn


class FakeSender:
    enabled, token, account = True, 'synthetic-token', 'synthetic-phone-id'

    def __init__(self):self.calls, self.outcome = [], ('sent', 'wamid.SYNTHETIC')

    def send(self, phone, body):
        self.calls.append((phone, body))
        if isinstance(self.outcome, Exception):raise self.outcome
        return self.outcome if self.outcome[0] != 'sent' else ('sent', f'wamid.{len(self.calls)}')


@pytest.fixture
def setup():
    observer = bootstrap(TEST_DSN)
    sender = FakeSender()
    replies = StaffReplies(sender_dsn(TEST_DSN), SOURCE, sender, enabled=True)
    app = create_app({'MODE': 'observer', 'TESTING': True, 'STAFF_REPLIES': replies}, observer=observer, verifier=SyntheticVerifier())
    with psycopg.connect(TEST_DSN) as conn:  # The patient wrote just now, so the 24-hour window is open.
        conn.execute("INSERT INTO public.messages(phone,role,message,message_en) VALUES(%s,'user','Synthetic fresh question','x')", (PHONES['a'],))
    yield app.test_client(), sender
    clear_source(TEST_DSN)


def h(who='operator'):return {'Authorization': 'Bearer synthetic:' + who}


def send(client, name='a', body='Synthetic staff answer', who='operator', request_id=None):
    return client.post(f'/api/conversations/{reference(SOURCE, PHONES[name])}/replies',
                       json={'body': body, 'requestId': request_id or str(uuid4())}, headers=h(who))


def bot_rows(conn, phone):
    return conn.execute("SELECT role,message,message_en FROM public.messages WHERE phone=%s AND message LIKE 'Synthetic staff%%' ORDER BY id", (phone,)).fetchall()


def test_sent_reply_enters_bot_history_once_and_is_labelled(setup):
    client, sender = setup
    assert client.get('/api/me', headers=h()).json['canReply'] is True
    assert client.get('/api/me', headers=h('analyst')).json['canReply'] is False
    request_id = str(uuid4())
    first = send(client, request_id=request_id)
    assert first.status_code == 201 and first.json['status'] == 'sent' and first.json['messageId']
    assert sender.calls == [(PHONES['a'], 'Synthetic staff answer')]
    again = send(client, request_id=request_id)  # Retry of the same request never sends twice.
    assert again.status_code == 200 and again.json['duplicate'] is True and len(sender.calls) == 1
    with psycopg.connect(TEST_DSN) as conn:
        assert bot_rows(conn, PHONES['a']) == [('bot', 'Synthetic staff answer', 'Synthetic staff answer')]
        assert conn.execute("SELECT status,provider_message_id FROM observer_control.staff_replies").fetchall() == [('sent', 'wamid.1')]
    history = client.get(f"/api/conversations/{reference(SOURCE, PHONES['a'])}", headers=h()).json
    staff = [m for m in history['messages'] if m['sent_by_staff']]
    assert [(m['message'], m['sent_by_staff']) for m in staff] == [('Synthetic staff answer', 'Synthetic operator')]
    assert history['replyWindow']['agent_session_active'] is False and history['replyAttempts'] == []


def test_window_agent_session_scope_and_role_rules(setup):
    client, sender = setup
    assert send(client, 'empty').json['error'] == 'outside_24h_window'  # No message from the patient in 24 h.
    with psycopg.connect(TEST_DSN) as conn:
        conn.execute("INSERT INTO public.kv(key,value,expires_at) VALUES(%s,'{}',now()+interval '1 hour')", ('agent_session:' + PHONES['a'],))
    assert send(client).json['error'] == 'agent_session_active'
    with psycopg.connect(TEST_DSN) as conn:
        conn.execute("UPDATE public.kv SET expires_at=now()-interval '1 minute' WHERE key=%s", ('agent_session:' + PHONES['a'],))
    assert send(client).status_code == 201  # Expired agent session no longer blocks.
    assert send(client, 'b').status_code == 404  # Other clinic: not visible, not sendable.
    assert send(client, who='analyst').json['error'] == 'role_required'
    assert send(client, who='unknown').json['error'] == 'staff_required'
    assert send(client, who='disabled').json['error'] == 'staff_required'
    assert send(client, body='   ').json['error'] == 'invalid_message'
    assert send(client, body='x' * 3801).json['error'] == 'invalid_message'
    assert client.post(f"/api/conversations/{reference(SOURCE, PHONES['a'])}/replies", json={'body': 'x', 'requestId': 'nope'},
                       headers=h()).json['error'] == 'invalid_request_id'
    assert len(sender.calls) == 1


def test_rejected_and_uncertain_sends_never_enter_history(setup):
    client, sender = setup
    sender.outcome = ('failed', None)
    assert send(client, body='Synthetic staff rejected').json['status'] == 'failed'
    sender.outcome = TimeoutError('network')
    assert send(client, body='Synthetic staff uncertain').json['status'] == 'unknown'
    with psycopg.connect(TEST_DSN) as conn:
        assert bot_rows(conn, PHONES['a']) == []
        assert conn.execute("SELECT status,error_code FROM observer_control.staff_replies ORDER BY created_at").fetchall() == [
            ('failed', 'provider_rejected'), ('unknown', 'network_uncertain')]
    attempts = client.get(f"/api/conversations/{reference(SOURCE, PHONES['a'])}", headers=h()).json['replyAttempts']
    assert {(a['status'], a['message']) for a in attempts} == {('failed', 'Synthetic staff rejected'), ('unknown', 'Synthetic staff uncertain')}


def test_in_progress_rate_limit_and_off_switch(setup):
    client, sender = setup
    with psycopg.connect(TEST_DSN) as conn:
        staff = conn.execute("SELECT staff_id FROM observer_control.staff_identities WHERE subject='admin'").fetchone()[0]
        conn.execute("INSERT INTO observer_control.staff_replies(request_id,staff_id,source_id,phone,body) VALUES(%s,%s,%s,%s,'x')",
                     (str(uuid4()), staff, SOURCE, PHONES['a']))
    assert send(client).json['error'] == 'reply_in_progress'  # A concurrent claim for this patient is still open.
    with psycopg.connect(TEST_DSN) as conn:
        conn.execute("UPDATE observer_control.staff_replies SET status='unknown',finished_at=now()")
    for _ in range(10):  # The open claim above belongs to another person; the limit is per person.
        assert send(client).status_code == 201
    assert send(client).json['error'] == 'rate_limited'  # 10 per minute per person.
    off = create_app({'MODE': 'observer', 'TESTING': True}, observer=client.application.extensions['observer'], verifier=SyntheticVerifier()).test_client()
    assert off.get('/api/me', headers=h()).json['canReply'] is False
    assert send(off).json['error'] == 'replies_disabled'
    assert client.post(f"/api/conversations/{reference(SOURCE, PHONES['a'])}/other", json={}, headers=h()).status_code == 405
    assert client.post(f"/api/conversations/{reference(SOURCE, PHONES['a'])}/replies", data='body=x', headers=h()).status_code == 415


def test_sender_login_can_only_call_its_functions(setup):
    with psycopg.connect(make_conninfo(TEST_DSN, user='rudo_sender'), autocommit=True) as conn:
        for statement in ("INSERT INTO public.messages(phone,role,message) VALUES('1','bot','x')", 'SELECT * FROM public.messages',
                          'SELECT * FROM observer_control.staff_replies', 'SELECT * FROM public.kv',
                          "UPDATE observer_control.staff_replies SET status='sent'", 'SELECT observer_control.admin_overview()'):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):conn.execute(statement)
        # Without a verified staff identity in the session, the functions refuse.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT observer_control.begin_staff_reply(gen_random_uuid(),%s,'x')", (PHONES['a'],))
