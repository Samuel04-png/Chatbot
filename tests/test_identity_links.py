"""One internal staff id per person; Firebase and Supabase logins map to it. Import is staff-only,
idempotent and leaves no secrets. Runs against the exact production migration file."""
from uuid import uuid4

import psycopg
import pytest

from app import create_app
from conftest import TEST_DSN
from rudo.auth import supabase_issuer
from rudo.errors import ApiError
from rudo.observer import reference
from rudo.staff_migration import HashParams, LinkStore, classify, firebase_scrypt, run_import
from rudo.synthetic import ISSUER, PHONES, SOURCE, SyntheticVerifier, bootstrap, clear_source, snapshot, staff_id
from scripts import migrate_staff_auth

SB_URL = 'http://127.0.0.1:54321'
SB_ISSUER = supabase_issuer(SB_URL)
PROJECT = 'synthetic-test'  # ISSUER == https://securetoken.google.com/synthetic-test
PARAMS = HashParams(b'\x01' * 64, b'\x07', 8, 14)


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


class FakeAdmin:
    def __init__(self, users=()):self.existing,self.created=list(users),[]
    def users(self):return iter(self.existing)
    def create(self, body):
        user = {'id': str(uuid4()), 'email': body['email'], 'app_metadata': body['app_metadata']}
        self.created.append(body);self.existing.append(user);return user


def firebase_user(uid, email, providers=('password',), verified=True, disabled=False, hashed=True):
    salt = 'c2FsdHNhbHQ='
    return {'uid': uid, 'email': email, 'email_verified': verified, 'disabled': disabled, 'display_name': uid,
            'providers': list(providers),
            'password_hash': firebase_scrypt('pw-' + uid, salt, PARAMS) if hashed and 'password' in providers else None,
            'password_salt': salt}


USERS = [firebase_user('operator', 'operator@example.test'),
         firebase_user('admin', 'admin@example.test', providers=('google.com',)),
         firebase_user('analyst', 'dup@example.test'), firebase_user('second-account', 'DUP@example.test'),
         firebase_user('disabled', 'disabled@example.test'),
         firebase_user('other', 'other@example.test', disabled=True),
         firebase_user('empty', 'different@example.test'),
         firebase_user('patient-or-public-user', 'public@example.test')]


def test_inventory_is_staff_only_and_explains_every_hold(observer):
    report = classify(USERS, LinkStore(TEST_DSN).staff_rows(), PROJECT)
    assert [c['uid'] for c in report['candidates']] == ['operator', 'admin']
    assert report['candidates'][0]['staff_id'] == str(sid('operator'))
    assert {h['uid']: h['reasons'] for h in report['held']} == {
        'analyst': ['email_differs_from_staff_record', 'duplicate_email'],
        'second-account': ['email_differs_from_staff_record', 'duplicate_email'],
        'disabled': ['staff_suspended'], 'other': ['firebase_user_disabled'], 'empty': ['email_differs_from_staff_record']}
    assert report['excluded_non_staff'] == 1 and 'public@example.test' not in str(report)
    assert '$fbscrypt$' not in str(report) and "'password_hash'" not in str(report)


def test_import_dry_run_then_execute_is_idempotent_and_maps_to_staff_ids(observer, client):
    links, admin = LinkStore(TEST_DSN), FakeAdmin([{'id': str(uuid4()), 'email': 'unrelated@example.test'}])
    before = snapshot(TEST_DSN)
    report = classify(USERS, links.staff_rows(), PROJECT)
    assert {r['result'] for r in run_import(report, USERS, PARAMS, admin, links, SB_URL, 'a')} == {'would_create'} and not admin.created
    done = run_import(report, USERS, PARAMS, admin, links, SB_URL, 'a', execute=True)
    assert {r['uid']: (r['result'], r['password']) for r in done} == {
        'operator': ('created_and_linked', 'firebase_scrypt'), 'admin': ('created_and_linked', 'none (OAuth only)')}
    assert {r['result'] for r in run_import(report, USERS, PARAMS, admin, links, SB_URL, 'a', execute=True)} == {'already_linked'}
    assert len(admin.created) == 2
    login = links.linked_subject(SB_ISSUER, sid('operator'))
    assert client.get('/api/me', headers=bearer('sb:' + login)).json['staffId'] == str(sid('operator'))
    assert snapshot(TEST_DSN) == before  # Bot tables untouched.


def test_import_recovers_interrupted_run_and_refuses_email_collisions(observer):
    links = LinkStore(TEST_DSN)
    orphan = {'id': str(uuid4()), 'email': 'operator@example.test', 'app_metadata': {'firebase_uid': 'operator', 'firebase_project': PROJECT}}
    squatter = {'id': str(uuid4()), 'email': 'ADMIN@example.test', 'app_metadata': {}}
    admin = FakeAdmin([orphan, squatter])
    report = classify(USERS, links.staff_rows(), PROJECT)
    results = {r['uid']: r['result'] for r in run_import(report, USERS, PARAMS, admin, links, SB_URL, 'a', execute=True)}
    assert results == {'operator': 'linked_existing', 'admin': 'conflict_email_exists'} and admin.created == []
    assert links.linked_subject(SB_ISSUER, sid('operator')) == orphan['id']
    assert links.linked_subject(SB_ISSUER, sid('admin')) is None
    with pytest.raises(ValueError):run_import(report, USERS, PARAMS, admin, links, SB_URL, 'a', only_uid='analyst')


def test_migration_cli_guards_and_single_account_first(observer, capsys):
    env = {'SUPABASE_URL': SB_URL, 'FIREBASE_PROJECT_ID': PROJECT, 'RUDO_CONTROL_ADMIN_DATABASE_URL': TEST_DSN,
           'FIREBASE_SIGNER_KEY': 'AQ==', 'FIREBASE_SALT_SEPARATOR': 'Bw==', 'FIREBASE_ROUNDS': '8', 'FIREBASE_MEM_COST': '14'}
    admin = FakeAdmin()
    for argv, extra in ((['--execute', '--actor', 'a'], {}),
                        (['--execute', '--confirm-project', '127', '--actor', 'a'], {'RUDO_AUTH_IMPORT_ALLOWED_REF': 'other'})):
        with pytest.raises(SystemExit):
            migrate_staff_auth.main(argv, env={**env, **extra}, firebase_users=USERS, admin=admin)
    assert migrate_staff_auth.main(['--actor', 'a'], env=env, firebase_users=USERS, admin=admin)['mode'] == 'dry-run' and not admin.created
    summary = migrate_staff_auth.main(['--execute', '--confirm-project', '127.0.0.1', '--only-uid', 'operator', '--actor', 'a'],
                                      env={**env, 'RUDO_AUTH_IMPORT_ALLOWED_REF': '127.0.0.1'}, firebase_users=USERS, admin=admin)
    assert [r['result'] for r in summary['results']] == ['created_and_linked'] and len(admin.created) == 1
    printed = capsys.readouterr().out
    assert '$fbscrypt$' not in printed and '"password_hash"' not in printed


def test_link_store_refuses_remote_targets():
    with pytest.raises(ApiError):LinkStore('postgresql://u@db.example.supabase.co:5432/postgres')
