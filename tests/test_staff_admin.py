"""Staff management through the real API, restricted rudo_staff_admin login and database-enforced
admin functions: invitations, approval of verified sign-ins, provider linking, suspension, scopes."""
from uuid import uuid4

import psycopg
import pytest

from app import create_app
from conftest import TEST_DSN
from rudo.synthetic import PHONES, admin_dsn, bootstrap, clear_source, snapshot
from test_identity_links import TwoProviders


@pytest.fixture
def observer():
    value = bootstrap(TEST_DSN)
    yield value
    clear_source(TEST_DSN)


@pytest.fixture
def client(observer):
    return create_app({'MODE': 'observer', 'TESTING': True, 'STAFF_ADMIN_DATABASE_URL': admin_dsn(TEST_DSN)},
                      observer=observer, verifier=TwoProviders()).test_client()


def h(token):return {'Authorization': 'Bearer ' + token}


ADMIN = h('synthetic:admin')


def post(client, path, body, headers=ADMIN):return client.post(path, json=body, headers=headers)


def overview(client):return client.get('/api/admin/overview', headers=ADMIN).json


def test_only_active_admins_can_manage_staff(client):
    data = overview(client)
    assert {(f['account'], f['facility']) for f in data['facilities']} == {('account-one', 'facility-a'), ('account-one', 'facility-b'), ('account-two', 'facility-a')}
    assert len(data['staff']) == 7 and data['invitations'] == [] and data['requests'] == []
    assert next(s for s in data['staff'] if s['email'] == 'admin@example.test')['self'] is True
    for token in ('synthetic:operator', 'synthetic:analyst', 'synthetic:disabled', 'sb:' + str(uuid4())):
        assert client.get('/api/admin/overview', headers=h(token)).status_code == 403
    assert client.get('/api/admin/overview').status_code == 401
    assert client.post('/api/admin/invitations', data='email=x', headers=ADMIN).status_code == 415
    assert client.post('/api/conversations', json={}, headers=ADMIN).status_code == 405
    unconfigured = create_app({'MODE': 'observer', 'TESTING': True}, observer=client.application.extensions['observer'],
                              verifier=TwoProviders()).test_client()
    assert unconfigured.get('/api/admin/overview', headers=ADMIN).json['error'] == 'staff_admin_unavailable'


def test_invite_sign_in_approve_grants_exactly_the_invited_scope(client, observer):
    before = snapshot(TEST_DSN)
    assert post(client, '/api/admin/invitations', {'email': 'x@example.test', 'role': 'operator',
                'scopes': [{'account': 'account-two', 'facility': 'facility-b'}]}).json['error'] == 'scope_not_permitted'
    assert post(client, '/api/admin/invitations', {'email': 'x@example.test', 'role': 'operator', 'scopes': []}).json['error'] == 'scope_required'
    assert post(client, '/api/admin/invitations', {'email': 'operator@example.test', 'role': 'operator',
                'scopes': [{'account': 'account-one', 'facility': 'facility-b'}]}).json['error'] == 'staff_exists'
    created = post(client, '/api/admin/invitations', {'email': 'New.Person@example.test', 'role': 'operator',
                   'scopes': [{'account': 'account-one', 'facility': 'facility-b'}]})
    assert created.status_code == 201
    invitation = created.json['id']
    newcomer, impostor = str(uuid4()), str(uuid4())
    # Sign-up alone grants nothing; it only becomes a pending request.
    assert client.get('/api/conversations', headers=h(f'sb:{newcomer}:new.person@example.test')).status_code == 403
    assert client.get('/api/me', headers=h(f'sb:{impostor}:attacker@example.test')).status_code == 403
    requests = {r['subject']: r for r in overview(client)['requests']}
    assert set(requests) == {newcomer, impostor} and requests[newcomer]['email_verified'] is True
    approve = lambda subject: post(client, f'/api/admin/invitations/{invitation}/approve', {'issuer': requests[subject]['issuer'], 'subject': subject})
    assert approve(impostor).json['error'] == 'email_mismatch'  # No account takeover by pairing another email.
    result = approve(newcomer)
    assert result.status_code == 200
    me = client.get('/api/me', headers=h('sb:' + newcomer)).json
    assert me['staffId'] == result.json['staffId'] and me['role'] == 'operator'
    assert {r['phone'] for r in client.get('/api/conversations', headers=h('sb:' + newcomer)).json['items']} == {PHONES['b']}
    assert approve(newcomer).json['error'] == 'invitation_not_pending'
    assert snapshot(TEST_DSN) == before
    with psycopg.connect(TEST_DSN) as conn:
        assert [r[0] for r in conn.execute('SELECT action FROM observer_control.staff_admin_events ORDER BY id')] == ['invite', 'approve']
        assert conn.execute("SELECT count(*) FROM observer_control.access_audit WHERE action='staff_admin'").fetchone()[0] == 2


def test_unverified_email_cannot_be_approved(client):
    invitation = post(client, '/api/admin/invitations', {'email': 'late@example.test', 'role': 'analyst',
                      'scopes': [{'account': 'account-one', 'facility': 'facility-a'}]}).json['id']
    client.get('/api/me', headers=h('synthetic:unverified-late'))
    request = overview(client)['requests'][0]
    assert request['email_verified'] is False
    assert post(client, f'/api/admin/invitations/{invitation}/approve', {'issuer': request['issuer'], 'subject': request['subject']}).json['error'] == 'email_not_verified'


def test_add_supabase_login_to_existing_staff_without_duplicate_profile(client):
    operator = next(s for s in overview(client)['staff'] if s['email'] == 'operator@example.test')
    assert post(client, '/api/admin/invitations', {'email': 'someone@example.test', 'staffId': operator['id']}).json['error'] == 'staff_email_mismatch'
    invitation = post(client, '/api/admin/invitations', {'email': 'operator@example.test', 'staffId': operator['id']}).json['id']
    login = str(uuid4())
    client.get('/api/me', headers=h(f'sb:{login}:operator@example.test'))
    request = overview(client)['requests'][0]
    assert post(client, f'/api/admin/invitations/{invitation}/approve', {'issuer': request['issuer'], 'subject': login}).json['staffId'] == operator['id']
    assert client.get('/api/me', headers=h('sb:' + login)).json['staffId'] == operator['id']
    staff = overview(client)['staff']
    assert len(staff) == 7 and {i['provider'] for i in next(s for s in staff if s['id'] == operator['id'])['identities']} == {'firebase', 'supabase'}
    second = post(client, '/api/admin/invitations', {'email': 'operator@example.test', 'staffId': operator['id']}).json['id']
    other_login = str(uuid4())
    client.get('/api/me', headers=h(f'sb:{other_login}:operator@example.test'))
    assert post(client, f'/api/admin/invitations/{second}/approve', {'issuer': request['issuer'], 'subject': other_login}).json['error'] == 'provider_already_linked'


def test_role_status_scope_changes_and_self_protection(client):
    staff = {s['email']: s for s in overview(client)['staff']}
    op, me = staff['operator@example.test'], staff['admin@example.test']
    assert post(client, f"/api/admin/staff/{op['id']}", {'status': 'suspended'}).status_code == 200
    assert client.get('/api/me', headers=h('synthetic:operator')).status_code == 403
    assert post(client, f"/api/admin/staff/{op['id']}", {'status': 'active', 'scopes': [{'account': 'account-one', 'facility': 'facility-b'}]}).status_code == 200
    assert {r['phone'] for r in client.get('/api/conversations', headers=h('synthetic:operator')).json['items']} == {PHONES['b']}
    assert post(client, f"/api/admin/staff/{op['id']}", {'role': 'analyst'}).status_code == 200
    assert client.get('/api/conversations', headers=h('synthetic:operator')).status_code == 403
    for body in ({'status': 'suspended'}, {'role': 'operator'}, {'scopes': []}):
        assert post(client, f"/api/admin/staff/{me['id']}", body).json['error'] == 'cannot_change_self'
    assert post(client, f"/api/admin/staff/{op['id']}", {'role': 'owner'}).json['error'] == 'invalid_role'
    assert post(client, f"/api/admin/staff/{op['id']}", {}).json['error'] == 'nothing_to_change'
    assert post(client, '/api/admin/staff/not-a-uuid', {'role': 'operator'}).json['error'] == 'invalid_identifier'
    # Scopes outside the admin's own facilities are preserved, never removed or granted.
    empty = staff['empty@example.test']
    post(client, f"/api/admin/staff/{empty['id']}", {'scopes': [{'account': 'account-one', 'facility': 'facility-a'}]})
    after = next(s for s in overview(client)['staff'] if s['id'] == empty['id'])
    assert after['scopes'] == [{'account': 'account-empty', 'facility': 'facility-empty'}, {'account': 'account-one', 'facility': 'facility-a'}]
    with psycopg.connect(TEST_DSN) as conn:
        assert conn.execute("SELECT count(*) FROM observer_control.staff_scopes WHERE staff_id=%s", (empty['id'],)).fetchone()[0] == 2


def test_revoke_dismiss_unlink(client):
    invitation = post(client, '/api/admin/invitations', {'email': 'gone@example.test', 'role': 'operator',
                      'scopes': [{'account': 'account-one', 'facility': 'facility-a'}]}).json['id']
    assert post(client, f'/api/admin/invitations/{invitation}/revoke', {}).status_code == 200
    assert post(client, f'/api/admin/invitations/{invitation}/revoke', {}).json['error'] == 'invitation_not_pending'
    client.get('/api/me', headers=h('sb:' + str(uuid4()) + ':noise@example.test'))
    request = overview(client)['requests'][0]
    assert post(client, '/api/admin/requests/dismiss', {'issuer': request['issuer'], 'subject': request['subject']}).status_code == 200
    assert overview(client)['requests'] == []
    other = next(s for s in overview(client)['staff'] if s['email'] == 'other@example.test')
    identity = other['identities'][0]
    assert post(client, '/api/admin/identities/unlink', {'issuer': identity['issuer'], 'subject': identity['subject']}).status_code == 200
    assert client.get('/api/me', headers=h('synthetic:other')).status_code == 403
    mine = next(s for s in overview(client)['staff'] if s['self'])['identities'][0]
    assert post(client, '/api/admin/identities/unlink', {'issuer': mine['issuer'], 'subject': mine['subject']}).json['error'] == 'cannot_change_self'


def test_health_and_readiness_use_the_restricted_logins(client, observer):
    assert client.get('/healthz').json == {'status': 'ok'}
    assert client.get('/readyz').json == {'status': 'ready'}
    observer.dsn = observer.dsn.replace('rudo_observer', 'rudo_test_owner')  # Wrong (privileged) login is refused.
    assert client.get('/readyz').status_code == 503
