"""One internal staff id per person; Firebase and Supabase logins map to it. Account import: tests/test_firebase_migration.py. Runs against the exact production migration file."""
from uuid import uuid4

import psycopg
import pytest

from app import create_app
from conftest import TEST_DSN
from rudo.auth import supabase_issuer
from rudo.errors import ApiError
from rudo.observer import reference
from rudo.staff_migration import LinkStore
from rudo.synthetic import ISSUER, PHONES, SOURCE, SyntheticVerifier, bootstrap, clear_source, snapshot, staff_id

SB_URL = 'http://127.0.0.1:54321'
SB_ISSUER = supabase_issuer(SB_URL)
PROJECT = 'synthetic-test'  # ISSUER == https://securetoken.google.com/synthetic-test


class TwoProviders:
    """Synthetic parallel mode: 'synthetic:<uid>' = Firebase, 'sb:<uuid>' or 'sb:<uuid>:<email>' = Supabase."""
    def verify(self, token):
        if token.startswith('sb:'):
            parts = token.split(':')
            return {'issuer': SB_ISSUER, 'subject': parts[1], 'provider': 'supabase',
                    'email': parts[2] if len(parts) > 2 else None, 'email_verified': len(parts) > 2}
        return SyntheticVerifier().verify(token)


@pytest.fixture
def observer():
    value = bootstrap(TEST_DSN)
    yield value
    clear_source(TEST_DSN)


@pytest.fixture
def client(observer):
    return create_app({'MODE': 'observer', 'TESTING': True}, observer=observer, verifier=TwoProviders()).test_client()


def bearer(token):return {'Authorization': 'Bearer ' + token}


def sid(subject):
    with psycopg.connect(TEST_DSN) as conn:return staff_id(conn, subject)


def link(login, subject):
    LinkStore(TEST_DSN).link(SB_ISSUER, login, sid(subject), subject + '@example.test', 'synthetic-admin')


def phones(client, token):
    return {row['phone'] for row in client.get('/api/conversations', headers=bearer(token)).json['items']}


def test_unlinked_supabase_signup_is_pending_sees_nothing_and_is_recorded(client):
    login = str(uuid4())
    for route in ('/api/me', '/api/conversations', '/api/orders', '/api/referrals', '/api/analytics'):
        response = client.get(route, headers=bearer(f'sb:{login}:new@example.test'))
        assert response.status_code == 403 and response.json['error'] == 'staff_required'
    with psycopg.connect(TEST_DSN) as conn:
        assert conn.execute('SELECT provider,email,email_verified,attempts FROM observer_control.identity_requests WHERE subject=%s',
                            (login,)).fetchone() == ('supabase', 'new@example.test', True, 5)


def test_both_providers_resolve_to_one_staff_id_with_same_role_and_scopes(client):
    login = str(uuid4())
    link(login, 'operator')
    firebase_me, supabase_me = (client.get('/api/me', headers=bearer(t)).json for t in ('synthetic:operator', 'sb:' + login))
    assert firebase_me['staffId'] == supabase_me['staffId'] == str(sid('operator'))
    assert supabase_me['provider'] == 'supabase' and firebase_me['provider'] == 'firebase'
    assert supabase_me['role'] == 'operator' and [(s['account_id'], s['facility_id']) for s in supabase_me['scopes']] == [('account-one', 'facility-a')]
    assert phones(client, 'synthetic:operator') == phones(client, 'sb:' + login) == {PHONES['a'], PHONES['empty'], PHONES['history_only']}
    assert client.get('/api/conversations/' + reference(SOURCE, PHONES['b']), headers=bearer('sb:' + login)).status_code == 404
    with psycopg.connect(TEST_DSN) as conn:
        assert conn.execute('SELECT count(*) FROM observer_control.staff').fetchone()[0] == 7  # No duplicate profile.
        assert conn.execute("SELECT DISTINCT issuer FROM observer_control.access_audit WHERE subject=%s", (login,)).fetchall() == [(SB_ISSUER,)]


def test_suspension_revokes_every_login_of_that_person(client):
    login = str(uuid4())
    link(login, 'operator')
    with psycopg.connect(TEST_DSN) as conn:
        conn.execute("UPDATE observer_control.staff SET status='suspended' WHERE id=%s", (sid('operator'),))
    for token in ('synthetic:operator', 'sb:' + login):
        assert client.get('/api/me', headers=bearer(token)).status_code == 403


def test_identity_constraints(observer):
    login = str(uuid4())
    link(login, 'operator')
    with pytest.raises(psycopg.errors.UniqueViolation):link(str(uuid4()), 'operator')  # One login per provider per person.
    with pytest.raises(psycopg.errors.UniqueViolation):link(login, 'admin')  # A login belongs to exactly one person.
    with psycopg.connect(TEST_DSN) as conn, pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("INSERT INTO observer_control.staff_identities VALUES('i','s','firebase',%s,null,'bootstrap','a')", (str(uuid4()),))
    with psycopg.connect(TEST_DSN) as conn, pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("INSERT INTO observer_control.staff(email,role,created_by) VALUES('OPERATOR@example.test','operator','a')")
    for table in ('staff_admin_events', 'access_audit'):
        with psycopg.connect(TEST_DSN) as conn, pytest.raises(psycopg.errors.RaiseException):
            conn.execute(f'DELETE FROM observer_control.{table}')


def test_restricted_roles_cannot_read_or_forge_staff_metadata(observer):
    from psycopg.conninfo import make_conninfo
    for role in ('rudo_observer', 'rudo_observer_audit', 'rudo_staff_admin'):
        with psycopg.connect(make_conninfo(TEST_DSN, user=role), autocommit=True) as conn:
            conn.execute('SET default_transaction_read_only=off')
            for sql in ('SELECT * FROM observer_control.staff_identities', 'SELECT * FROM observer_control.identity_requests',
                        'SELECT * FROM observer_control.staff_invitations', 'SELECT * FROM observer_control.staff_admin_events',
                        'SELECT * FROM observer_control.source_mappings',
                        "INSERT INTO observer_control.staff_identities VALUES('x','y','firebase',gen_random_uuid(),null,'bootstrap','me')",
                        "UPDATE observer_control.staff SET role='admin'", 'SELECT message_en FROM public.messages',
                        'SELECT * FROM public.kv', 'SELECT * FROM public.user_state', 'SELECT address FROM public.orders'):
                with pytest.raises(psycopg.errors.InsufficientPrivilege):conn.execute(sql)
    # The admin login can call nothing without an active-admin identity context.
    with psycopg.connect(make_conninfo(TEST_DSN, user='rudo_staff_admin')) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute('SELECT observer_control.admin_overview()')


def test_link_store_refuses_remote_targets():
    with pytest.raises(ApiError):LinkStore('postgresql://u@db.example.supabase.co:5432/postgres')
