"""Full-account Firebase -> Supabase migration engine: every account gets one outcome, import never grants
access, identity is matched by Firebase UID only, secrets never leave the encrypted export. Synthetic data."""
import base64
import json
import uuid

import pytest

from rudo import firebase_migration as fm
from rudo.staff_migration import HashParams
from scripts import migrate_firebase_auth as cli

PROJECT = 'synthetic-fb'
PARAMS = HashParams(b'\x01' * 64, b'\x07', 8, 14)
URL = 'http://127.0.0.1:54421'
HASH, SALT = base64.b64encode(b'h' * 32).decode(), base64.b64encode(b's' * 16).decode()


def acct(uid, email=None, providers=('password',), verified=True, disabled=False, phone=None, hashed=True, **extra):
    return fm.export_record({
        'localId': uid, 'email': email, 'emailVerified': verified, 'disabled': disabled, 'phoneNumber': phone,
        'displayName': uid.title(), 'createdAt': '1700000000000', 'lastSignedInAt': '1710000000000',
        'providerUserInfo': [{'providerId': p, 'rawId': f'{p}-{uid}', 'email': email} for p in providers],
        'passwordHash': (HASH if hashed else None) if 'password' in providers else None,
        'salt': SALT if 'password' in providers and hashed else None, **extra})


ACCOUNTS = [
    acct('staff', 'staff@example.test'),                                       # existing Firebase staff link
    acct('pending', 'pending@example.test'),                                   # unapproved / never staff
    acct('disabled', 'disabled@example.test', disabled=True),
    acct('unverified', 'unverified@example.test', verified=False),
    acct('google', 'google@example.test', providers=('google.com',)),
    acct('both', 'both@example.test', providers=('password', 'google.com')),
    acct('facebook', 'fb@example.test', providers=('facebook.com',)),
    acct('phone', None, providers=('phone',), phone='+260970000001'),
    acct('anon', None, providers=()),
    acct('dup1', 'dup@example.test'), acct('dup2', 'DUP@example.test'),
    acct('taken', 'taken@example.test'),                                       # email already used in Supabase
    acct('redacted', 'redacted@example.test', hashed=False),
    acct('mfa', 'mfa@example.test', mfaInfo=[{'mfaEnrollmentId': 'x', 'phoneInfo': '+260970000002', 'enrolledAt': '2025-01-01'}]),
    acct('claims', 'claims@example.test', customAttributes=json.dumps({'dawaMomRole': 'mother'})),
    acct('tenant', 'tenant@example.test', tenantId='t-1'),
]
ACCOUNTS[12]['password_hash'], ACCOUNTS[12]['password_salt'] = base64.b64encode(b'REDACTED').decode(), None
ACCOUNTS[12]['providers'].append({'provider': 'password', 'provider_uid': 'redacted', 'email': 'redacted@example.test'})
STAFF_ID = str(uuid.uuid4())


class FakeAdmin:
    def __init__(self, users=()):
        self.store = {u['id']: u for u in users}
        self.created, self.fail_once = [], set()

    def users(self):return list(self.store.values())
    def get(self, user_id):return self.store.get(user_id)

    def create(self, body):
        if body['id'] in self.store:return None, 'email_exists'
        user = {'id': body['id'], 'email': (body.get('email') or '').lower() or None, 'phone': (body.get('phone') or '').lstrip('+') or None,
                'app_metadata': body['app_metadata'], 'banned_until': '2125-01-01' if body.get('ban_duration') else None,
                'email_confirmed_at': 'now' if body.get('email_confirm') else None}
        self.store[body['id']] = user; self.created.append(body)
        if body['id'] in self.fail_once:  # Created, but the response was lost (interrupted run).
            self.fail_once.discard(body['id']); return None, 'network'
        return user, None

    def delete(self, user_id):return self.store.pop(user_id, None) is not None


class FakeLedger:
    def __init__(self, links=None):
        self.accounts, self.events, self.runs, self.links, self.staff_copies, self.oauth = {}, [], {}, links or {}, [], []

    def start(self, project, sha, mode, actor):
        run = str(uuid.uuid4()); self.runs[run] = {'sha': sha}; return run
    def finish(self, run, counts):self.runs[run]['counts'] = counts
    def staff_links(self, project):return dict(self.links)

    def record(self, run, project, record, decision, status, supabase_user_id=None, error=None):
        old = self.accounts.get(record['uid'], {})
        self.accounts[record['uid']] = {'firebase_uid': record['uid'], 'status': 'imported' if old.get('status') == 'imported' and status != 'imported' else status,
                                        'supabase_user_id': supabase_user_id or old.get('supabase_user_id'), 'error': error}
        self.events.append((record['uid'], status))

    def rows(self, project):return dict(self.accounts)
    def copy_staff_link(self, project, uid, issuer, actor):self.staff_copies.append(uid); return 'linked'
    def link_oauth(self, project, uid, provider, provider_uid):self.oauth.append((uid, provider, provider_uid)); return 'linked'


def taken_user():
    return {'id': str(uuid.uuid4()), 'email': 'taken@example.test', 'app_metadata': {}}


def test_every_account_gets_exactly_one_outcome_and_none_gains_access():
    facts, decisions = fm.plan(ACCOUNTS, PROJECT, [taken_user()], {'staff': STAFF_ID})
    by = {d['uid']: d for d in decisions}
    assert len(decisions) == len(ACCOUNTS) and set(by) == {a['uid'] for a in ACCOUNTS}
    assert {u for u, d in by.items() if d['action'] == 'create'} == {
        'staff', 'pending', 'disabled', 'unverified', 'google', 'both', 'facebook', 'phone', 'redacted', 'mfa', 'claims'}
    assert {u: d['remediation'][0] for u, d in by.items() if d['action'] == 'manual'} == {
        'anon': 'no_email_or_phone', 'dup1': 'duplicate_email_in_firebase', 'dup2': 'duplicate_email_in_firebase',
        'taken': 'email_used_by_other_supabase_user', 'tenant': 'firebase_tenant_user'}
    # Only the pre-existing Firebase staff link carries access over; nothing else is approved by importing.
    assert {u for u, d in by.items() if d['dashboard_access'] != 'none'} == {'staff'}
    assert by['staff']['staff_id'] == STAFF_ID and by['pending']['staff_id'] is None
    assert by['redacted']['password'] == 'needs_setup' and 'password_hash_unavailable_send_reset' in by['redacted']['remediation']
    assert by['google']['password'] == 'none' and 'google_sign_in_needs_supabase_google_provider' in by['google']['remediation']
    assert 'provider_not_migrated:facebook.com' in by['facebook']['remediation'] and 'password_setup_via_reset' in by['facebook']['remediation']
    assert 'sms_provider_required_for_phone_sign_in' in by['phone']['remediation']
    assert 'mfa_must_reenrol' in by['mfa']['remediation'] and 'email_unverified_must_confirm' in by['unverified']['remediation']
    counts = fm.report_counts(facts, decisions)
    assert counts['firebase_users'] == 16 and counts['staged_for_import'] == 11 and counts['manual_investigation'] == 5
    assert counts['password_preserved'] == 7 and counts['dashboard_access_granted_by_import'] == 0
    assert fm.assert_no_secrets(counts) and fm.assert_no_secrets(decisions)


def test_create_payload_preserves_identity_and_status_without_leaking_claims_into_jwt():
    _, decisions = fm.plan(ACCOUNTS, PROJECT, [], {})
    by = {d['uid']: d for d in decisions}
    rec = {a['uid']: a for a in ACCOUNTS}
    body = fm.create_payload(rec['disabled'], by['disabled'], PROJECT, PARAMS)
    assert body['id'] == fm.supabase_user_id(PROJECT, 'disabled') == by['disabled']['supabase_user_id']
    assert body['ban_duration'] == fm.BAN_FOREVER and body['email_confirm'] is True
    assert body['password_hash'].startswith('$fbscrypt$v=1,n=14,r=8,p=1,')
    assert body['app_metadata'] == {'firebase_uid': 'disabled', 'firebase_project': PROJECT, 'migrated_from': 'firebase'}
    assert fm.create_payload(rec['unverified'], by['unverified'], PROJECT, PARAMS)['email_confirm'] is False
    phone = fm.create_payload(rec['phone'], by['phone'], PROJECT, PARAMS)
    assert phone['phone'] == '+260970000001' and phone['phone_confirm'] is True and 'email' not in phone and 'password_hash' not in phone
    claims = fm.create_payload(rec['claims'], by['claims'], PROJECT, PARAMS)
    assert 'dawaMomRole' not in json.dumps(claims)  # Another app's claims never enter Supabase JWTs.
    assert fm.create_payload(rec['google'], by['google'], PROJECT, PARAMS).get('password_hash') is None


def test_execute_is_idempotent_restartable_and_never_matches_by_email():
    admin, ledger = FakeAdmin([taken_user()]), FakeLedger({'staff': STAFF_ID})
    dry, _ = fm.execute_plan(ACCOUNTS, PROJECT, 'a' * 64, admin, ledger, URL, PARAMS, 'tester')
    assert dry['mode'] == 'dry_run' and not admin.created and not ledger.accounts
    admin.fail_once.add(fm.supabase_user_id(PROJECT, 'pending'))  # Lost response on one create.
    first, _ = fm.execute_plan(ACCOUNTS, PROJECT, 'a' * 64, admin, ledger, URL, PARAMS, 'tester', execute=True)
    assert first['this_run'] == {'imported': 11, 'manual': 5, 'oauth_linked': 2, 'staff_linked': 1}
    assert ledger.staff_copies == ['staff'] and {u for u, *_ in ledger.oauth} == {'google', 'both'}
    assert len(admin.created) == 11
    second, _ = fm.execute_plan(ACCOUNTS, PROJECT, 'a' * 64, admin, ledger, URL, PARAMS, 'tester', execute=True)
    assert second['by_action']['already_imported'] == 11 and len(admin.created) == 11  # No duplicates.
    assert admin.store[next(u['id'] for u in admin.users() if u['email'] == 'taken@example.test')]['app_metadata'] == {}
    report = fm.reconcile(ACCOUNTS, PROJECT, admin, ledger)
    assert report['problems'] == 0 and report['coverage_complete'] and report['ledger_rows'] == 16
    assert report['ledger_by_status'] == {'imported': 11, 'manual': 5}


def test_reconcile_flags_missing_and_mismatched_accounts():
    admin, ledger = FakeAdmin(), FakeLedger()
    fm.execute_plan(ACCOUNTS[:3], PROJECT, 'a' * 64, admin, ledger, URL, PARAMS, 't', execute=True)
    admin.store[fm.supabase_user_id(PROJECT, 'disabled')]['banned_until'] = None
    report = fm.reconcile(ACCOUNTS[:4], PROJECT, admin, ledger)
    assert {(p['uid'], p['problem']) for p in report['problem_detail']} == {('unverified', 'missing_from_ledger'), ('disabled', 'disabled_not_banned')}
    assert report['coverage_complete'] is False


def test_rollback_deletes_only_users_this_migration_created():
    admin, ledger = FakeAdmin([taken_user()]), FakeLedger()
    fm.execute_plan(ACCOUNTS, PROJECT, 'a' * 64, admin, ledger, URL, PARAMS, 't', execute=True)
    assert fm.rollback_users(PROJECT, admin, ledger) == {'mode': 'dry_run', 'would_delete': 11} and len(admin.store) == 12
    assert fm.rollback_users(PROJECT, admin, ledger, execute=True) == {'mode': 'execute', 'deleted': 11}
    assert [u['email'] for u in admin.users()] == ['taken@example.test']


def test_owner_exclusions_are_reported_not_silent():
    _, decisions = fm.plan(ACCOUNTS, PROJECT, [], {}, exclusions={'claims': 'dawa_mom_consumer_owned_by_other_app'})
    d = next(d for d in decisions if d['uid'] == 'claims')
    assert d['action'] == 'excluded_by_owner' and d['remediation'][0] == 'dawa_mom_consumer_owned_by_other_app'


def test_encrypted_export_round_trip_outside_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(fm, 'KEY_PATH', tmp_path / 'cfg' / 'migration.key')
    path, digest = fm.encrypt_export(ACCOUNTS, tmp_path / 'out' / 'export.enc.json')
    raw = path.read_text()
    assert HASH not in raw and 'staff@example.test' not in raw  # Ciphertext only.
    assert oct(path.stat().st_mode)[-3:] == '600' and oct(fm.KEY_PATH.stat().st_mode)[-3:] == '600'
    records, again = fm.decrypt_export(path)
    assert records == json.loads(json.dumps(ACCOUNTS, sort_keys=True, default=str)) and again == digest
    blob = json.loads(raw); blob['data'] = base64.b64encode(b'x' * 40).decode(); path.write_text(json.dumps(blob))
    with pytest.raises(Exception):fm.decrypt_export(path)  # Tampering is detected (GCM tag).
    with pytest.raises(ValueError):fm.secure_write(fm.Path(__file__).resolve().parents[1] / 'leak.json', 'x')


def test_firebase_admin_sdk_shape_is_normalised():
    meta = type('M', (), {'creation_timestamp': 1700000000000, 'last_sign_in_timestamp': None, 'last_refresh_timestamp': None})()
    provider = type('P', (), {'provider_id': 'google.com', 'uid': 'g-sub-1', 'email': 'a@example.test'})()
    user = type('U', (), {'uid': 'u1', 'email': 'a@example.test', 'email_verified': True, 'phone_number': None, 'display_name': 'A',
                          'photo_url': None, 'disabled': False, 'tenant_id': None, 'provider_data': [provider], 'user_metadata': meta,
                          'custom_claims': None, 'multi_factor': None, 'password_hash': None, 'password_salt': None})()
    record = fm.export_record(user)
    assert record['created_at'].startswith('2023-11-14') and record['providers'][0]['provider_uid'] == 'g-sub-1'
    assert fm.account_facts(record)['provider_identities'] == [{'provider': 'google.com', 'provider_uid': 'g-sub-1', 'email': 'a@example.test'}]


def test_cli_guards_dry_run_by_default_and_never_prints_secrets(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fm, 'KEY_PATH', tmp_path / 'cfg' / 'migration.key')
    monkeypatch.setattr(fm, 'OUT_DIR', tmp_path / 'out')
    env = {'SUPABASE_URL': URL, 'SUPABASE_SERVICE_ROLE_KEY': 'sb_secret_synthetic', 'FIREBASE_SIGNER_KEY': base64.b64encode(b'\x01' * 64).decode(),
           'FIREBASE_SALT_SEPARATOR': 'Bw==', 'FIREBASE_ROUNDS': '8', 'FIREBASE_MEM_COST': '14'}
    exported = cli.main(['export', '--project', PROJECT], env=env, firebase_records=ACCOUNTS)
    assert exported['exported_accounts'] == 16
    admin, ledger = FakeAdmin(), FakeLedger()
    plan = cli.main(['plan', '--project', PROJECT, '--export', exported['file']], env=env, admin=admin, ledger=ledger)
    assert plan['mode'] == 'dry_run' and not admin.created
    for extra in ({}, {'RUDO_AUTH_IMPORT_ALLOWED_REF': 'other'}):
        with pytest.raises(SystemExit):
            cli.main(['import', '--project', PROJECT, '--export', exported['file'], '--execute', '--confirm-project', '127.0.0.1'],
                     env={**env, **extra}, admin=admin, ledger=ledger)
    one = cli.main(['import', '--project', PROJECT, '--export', exported['file'], '--execute', '--confirm-project', '127.0.0.1', '--limit', '1'],
                   env={**env, 'RUDO_AUTH_IMPORT_ALLOWED_REF': '127.0.0.1'}, admin=admin, ledger=ledger)
    assert one['this_run']['imported'] == 1 and len(admin.created) == 1
    printed = capsys.readouterr().out
    for secret in ('$fbscrypt$', HASH, SALT, 'sb_secret_synthetic'):
        assert secret not in printed
    worksheet = (tmp_path / 'out').glob('plan-*.json')
    assert all(HASH not in p.read_text() and oct(p.stat().st_mode)[-3:] == '600' for p in worksheet)


# ---------- Firestore data landing ----------
from rudo import firestore_migration as fsm  # noqa: E402
import datetime as _dt  # noqa: E402


class _Ref:
    def __init__(self, path):self.path, self.id = path, path.rsplit('/', 1)[-1]


class _Geo:
    latitude, longitude = -15.4, 28.3


def test_firestore_values_keep_their_types_and_hash_stably():
    when = _dt.datetime(2025, 1, 2, 3, 4, 5, tzinfo=_dt.timezone.utc)
    data = fsm.encode({'t': when, 'r': _Ref('mother/m1'), 'g': _Geo(), 'b': b'\x00\x01', 'n': [1, 2.5, None, {'x': True}]})
    assert data == {'t': {'__type': 'timestamp', 'value': '2025-01-02T03:04:05+00:00'}, 'r': {'__type': 'reference', 'path': 'mother/m1'},
                    'g': {'__type': 'geopoint', 'latitude': -15.4, 'longitude': 28.3}, 'b': {'__type': 'bytes', 'base64': 'AAE='},
                    'n': [1, 2.5, None, {'x': True}]}
    assert fsm.content_sha256({'a': 1, 'b': 2}) == fsm.content_sha256({'b': 2, 'a': 1})


def test_every_collection_has_an_owner_and_subcollections_inherit():
    assert fsm.owner_for('mobile_chats/c1/messages/m9') == 'dawamom' and fsm.owner_for('encounter/e1') == 'dawaclinician'
    assert fsm.owner_for('whatsapp_chats/w/messages/x') == 'rudo_or_unknown' and fsm.owner_for('new_collection/x') == 'unknown'
    assert fsm.account_owner('Mother') == 'dawamom' and fsm.account_owner('Doctor') == 'dawaclinician' and fsm.account_owner(None) == 'rudo_or_unknown'


class _DocLedger:
    def __init__(self):self.docs = {}
    def upsert_documents(self, rows):
        for row in rows:self.docs[row[1]] = row[10]
        return len(rows)
    def document_hashes(self, project):return dict(self.docs)


def test_document_import_is_idempotent_and_reconciled_by_path_and_hash():
    docs = [{'path': f'parity/p{i}', 'collection_id': 'parity', 'collection_path': 'parity', 'doc_id': f'p{i}', 'parent_path': None,
             'data': {'i': i}, 'create_time': None, 'update_time': None, 'content_sha256': fsm.content_sha256({'i': i})} for i in range(1200)]
    docs.append({'path': 'mobile_chats/c/messages/m', 'collection_id': 'messages', 'collection_path': 'mobile_chats/c/messages', 'doc_id': 'm',
                 'parent_path': 'mobile_chats/c', 'data': {}, 'create_time': None, 'update_time': None, 'content_sha256': fsm.content_sha256({})})
    summary = fsm.summarise(docs)
    assert summary['by_collection'] == {'mobile_chats/*/messages': 1, 'parity': 1200} and summary['by_owner_app'] == {'dawaclinician': 1200, 'dawamom': 1}
    ledger = _DocLedger()
    assert fsm.import_documents(docs, 'p', ledger, 'run') == 1201 and fsm.import_documents(docs, 'p', ledger, 'run') == 1201
    assert fsm.reconcile_documents(docs, 'p', ledger)['coverage_complete'] is True
    del ledger.docs['parity/p7']; ledger.docs['parity/p8'] = '0' * 64
    bad = fsm.reconcile_documents(docs, 'p', ledger)
    assert (bad['missing'], bad['content_mismatch'], bad['coverage_complete']) == (1, 1, False)
