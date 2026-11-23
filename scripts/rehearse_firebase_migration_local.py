"""Full-account Firebase -> Supabase migration rehearsal on a LOCAL Supabase stack (real Supabase Auth and
Postgres images; loopback only; synthetic accounts and synthetic Firebase hash parameters).

Proves on the Auth version in use: Firebase scrypt passwords sign in unchanged; disabled stay disabled;
unverified stay unverified; accounts without a usable hash can set a password by email and keep their id;
Google identities are pre-linked by Google subject; only an existing Firebase staff link carries dashboard
access; imported non-staff see no patient rows; re-runs create nothing; reconciliation covers every account;
bot tables are byte-identical; rollback removes only what the migration created.

Usage: SUPABASE_URL=http://127.0.0.1:54421 SUPABASE_ANON_KEY=... SUPABASE_SERVICE_ROLE_KEY=... \
  SUPABASE_LOCAL_DB_URL=postgresql://postgres:postgres@127.0.0.1:54422/postgres MAILPIT_URL=http://127.0.0.1:54424 \
  .venv/bin/python scripts/rehearse_firebase_migration_local.py
"""
import base64
import hashlib
import html
import json
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse, urlsplit

import psycopg
import requests
from psycopg import sql
from psycopg.conninfo import make_conninfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rudo import firebase_migration as fm  # noqa: E402
from rudo.staff_migration import HashParams, firebase_scrypt  # noqa: E402
from scripts.release1_credentials import scram_verifier  # noqa: E402

M = ROOT / 'supabase/migrations'
R = ROOT / 'supabase/rollback'
STAFF, REPLIES, FIREBASE = '20261121120000_rudo_staff_control', '20261121150000_rudo_staff_replies', '20261123063840_firebase_account_migration'
TABLES = ('users', 'messages', 'referrals', 'orders', 'kv', 'user_state')
PROJECT, SOURCE = 'rehearsal-firebase', 'rehearsal-source'
FB_ISSUER = 'https://securetoken.google.com/' + PROJECT


def bot_snapshot(conn):
    data = {t: conn.execute(f'SELECT md5(coalesce(string_agg(t::text, \'|\' ORDER BY t::text), \'\')) FROM public.{t} t').fetchone()[0] for t in TABLES}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def reset(db, admin):
    with psycopg.connect(db, autocommit=True) as conn:
        if conn.execute("SELECT 1 FROM pg_namespace WHERE nspname='firebase_migration'").fetchone():
            for (uid,) in conn.execute("SELECT supabase_user_id FROM firebase_migration.accounts WHERE supabase_user_id IS NOT NULL").fetchall():
                admin.delete(str(uid))
            conn.execute((R / f'{FIREBASE}.down.sql').read_text())
        if conn.execute("SELECT to_regclass('observer_control.staff_replies')").fetchone()[0]:
            conn.execute((R / f'{REPLIES}.down.sql').read_text())
        if conn.execute("SELECT 1 FROM pg_namespace WHERE nspname='observer_control'").fetchone():
            conn.execute((R / f'{STAFF}.down.sql').read_text())
        for table in TABLES:
            conn.execute(f'DROP TABLE IF EXISTS public.{table} CASCADE')
        conn.execute((ROOT / 'staging/observer/source_fixture.sql').read_text())
        for table in TABLES:
            conn.execute(f'GRANT ALL ON public.{table} TO anon,authenticated,service_role')
        conn.execute("SET ROLE service_role")
        for phone in ('260000000601', '260000000602'):
            conn.execute("INSERT INTO public.users(phone,user_id,language,step,state) VALUES(%s,'R','english','menu','{}')", (phone,))
            conn.execute("INSERT INTO public.messages(phone,role,message) VALUES(%s,'user','Rehearsal question')", (phone,))
        conn.execute('RESET ROLE')


def latest_link(mail, email, subject):
    msgs = requests.get(f'{mail}/api/v1/search', params={'query': f'to:{email}'}, timeout=10).json()['messages']
    msg = next(m for m in msgs if subject in m['Subject'].lower())
    body = requests.get(f"{mail}/api/v1/message/{msg['ID']}", timeout=10).json()['HTML']
    return html.unescape(re.findall(r'href="([^"]+/auth/v1/verify[^"]+)"', body)[0])


def main():
    url, anon, service = os.environ['SUPABASE_URL'], os.environ['SUPABASE_ANON_KEY'], os.environ['SUPABASE_SERVICE_ROLE_KEY']
    db, mail = os.environ['SUPABASE_LOCAL_DB_URL'], os.environ.get('MAILPIT_URL', 'http://127.0.0.1:54424')
    if {urlsplit(url).hostname, urlsplit(db).hostname, urlsplit(mail).hostname} != {'127.0.0.1'}:
        raise SystemExit('Loopback local stack only')
    health = requests.get(url + '/auth/v1/health', headers={'apikey': anon}, timeout=10).json()
    checks, failures = {'auth_version': health.get('version')}, []

    def check(name, ok, detail=None):
        checks[name] = bool(ok) if detail is None else {'ok': bool(ok), 'detail': detail}
        if not ok:
            failures.append(name)

    admin = fm.AuthAdmin(url, service)
    reset(db, admin)
    with psycopg.connect(db, autocommit=True) as conn:
        before = bot_snapshot(conn)
    for name in (STAFF, REPLIES, FIREBASE):
        with psycopg.connect(db) as conn:  # One transaction each, as "postgres" - exactly as in production.
            conn.execute((M / f'{name}.sql').read_text())
    pw = {r: secrets.token_urlsafe(24) for r in ('rudo_migrator', 'rudo_observer')}
    with psycopg.connect(db, autocommit=True) as conn:
        for role, password in pw.items():
            conn.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(role), sql.Literal(scram_verifier(password))))
        conn.execute("INSERT INTO observer_control.facilities(source_id,account_id,facility_id,display_name) VALUES(%s,'acct','fac','Rehearsal clinic')", (SOURCE,))
        staff_id = conn.execute("INSERT INTO observer_control.staff(email,display_name,role,status,created_by) VALUES('staff@example.test','Rehearsal staff','operator','active','rehearsal') RETURNING id").fetchone()[0]
        conn.execute("INSERT INTO observer_control.staff_identities(issuer,subject,provider,staff_id,email,link_method,linked_by) VALUES(%s,'staff','firebase',%s,'staff@example.test','bootstrap','rehearsal')", (FB_ISSUER, staff_id))
        conn.execute("INSERT INTO observer_control.staff_scopes(staff_id,source_id,account_id,facility_id,granted_by) VALUES(%s,%s,'acct','fac','rehearsal')", (staff_id, SOURCE))
        conn.execute("INSERT INTO observer_control.source_mappings(source_id,phone,account_id,facility_id,approved,approved_by) VALUES(%s,'260000000601','acct','fac',true,'rehearsal')", (SOURCE,))
    migrator_dsn = make_conninfo(db, user='rudo_migrator', password=pw['rudo_migrator'])
    observer_dsn = make_conninfo(db, user='rudo_observer', password=pw['rudo_observer'])
    ledger = fm.Ledger(migrator_dsn)

    # Synthetic Firebase project with real Firebase-scrypt hashes (computed exactly as Firebase does).
    params = HashParams(os.urandom(64), b'\x07', 8, 14)
    passwords = {}

    def account(uid, email=None, providers=('password',), verified=True, disabled=False, phone=None, hashed=True, **extra):
        rec = {'localId': uid, 'email': email, 'emailVerified': verified, 'disabled': disabled, 'phoneNumber': phone, 'displayName': uid,
               'createdAt': '1700000000000', 'providerUserInfo': [{'providerId': p, 'rawId': f'{p.split(".")[0]}-sub-{uid}', 'email': email} for p in providers], **extra}
        if 'password' in providers and hashed:
            salt = base64.b64encode(os.urandom(16)).decode()
            passwords[uid] = secrets.token_urlsafe(16)
            rec.update(passwordHash=firebase_scrypt(passwords[uid], salt, params), salt=salt)
        return fm.export_record(rec)

    sfx = secrets.token_hex(3)
    accounts = [account('staff', 'staff@example.test'), account('pending', f'pending-{sfx}@example.test'),
                account('disabled', f'disabled-{sfx}@example.test', disabled=True),
                account('unverified', f'unverified-{sfx}@example.test', verified=False),
                account('google', f'google-{sfx}@example.test', providers=('google.com',)),
                account('both', f'both-{sfx}@example.test', providers=('password', 'google.com')),
                account('phone', None, providers=('phone',), phone='+26097' + str(secrets.randbelow(10 ** 7)).zfill(7)),
                account('anon', None, providers=()),
                account('dup1', f'dup-{sfx}@example.test'), account('dup2', f'DUP-{sfx}@example.test'),
                account('redacted', f'redacted-{sfx}@example.test', hashed=False),
                account('claims', f'claims-{sfx}@example.test', customAttributes=json.dumps({'dawaMomRole': 'mother'})),
                account('taken', f'taken-{sfx}@example.test')]
    accounts[10]['providers'].append({'provider': 'password', 'provider_uid': 'redacted', 'email': accounts[10]['email']})
    squatter, _ = admin.create({'email': f'taken-{sfx}@example.test', 'password': secrets.token_urlsafe(16), 'email_confirm': True})
    export_sha = hashlib.sha256(json.dumps(accounts, sort_keys=True).encode()).hexdigest()

    dry, _ = fm.execute_plan(accounts, PROJECT, export_sha, admin, ledger, url, params, 'rehearsal')
    check('dry_run_writes_nothing', dry['mode'] == 'dry_run' and not ledger.rows(PROJECT))
    run1, _ = fm.execute_plan(accounts, PROJECT, export_sha, admin, ledger, url, params, 'rehearsal', execute=True)
    check('first_run_outcomes', run1['this_run'] == {'imported': 9, 'manual': 4, 'oauth_linked': 2, 'staff_linked': 1}, run1['this_run'])
    run2, _ = fm.execute_plan(accounts, PROJECT, export_sha, admin, ledger, url, params, 'rehearsal', execute=True)
    check('rerun_creates_nothing', run2['by_action'].get('already_imported') == 9 and run2['this_run'].get('staff_already_linked') == 1, run2['this_run'])
    rec = fm.reconcile(accounts, PROJECT, admin, ledger)
    check('reconciliation_complete', rec['coverage_complete'] and rec['ledger_rows'] == 13, {k: rec[k] for k in ('ledger_by_status', 'problems')})

    H = {'apikey': anon, 'Content-Type': 'application/json'}
    def signin(email, password):
        return requests.post(f'{url}/auth/v1/token?grant_type=password', headers=H, json={'email': email, 'password': password}, timeout=10)
    by = {a['uid']: a for a in accounts}
    for uid in ('staff', 'pending', 'both', 'claims'):
        r = signin(by[uid]['email'], passwords[uid])
        check(f'firebase_password_works:{uid}', r.status_code == 200 and r.json()['user']['id'] == fm.supabase_user_id(PROJECT, uid))
    check('wrong_password_refused', signin(by['pending']['email'], 'wrong-' + passwords['pending']).status_code == 400)
    r = signin(by['disabled']['email'], passwords['disabled'])
    check('disabled_account_refused', r.status_code == 400 and r.json().get('error_code') == 'user_banned', r.json().get('error_code'))
    r = signin(by['unverified']['email'], passwords['unverified'])
    check('unverified_email_refused_until_confirmed', r.status_code == 400 and r.json().get('error_code') == 'email_not_confirmed', r.json().get('error_code'))
    # No usable hash: password set through the reset email; the same imported user id is kept.
    reset_to = 'http://localhost:8080/staff-reset.html?mode=update'
    requests.post(f'{url}/auth/v1/recover', headers=H, params={'redirect_to': reset_to}, json={'email': by['redacted']['email']}, timeout=10)
    loc = requests.get(latest_link(mail, by['redacted']['email'], 'reset'), allow_redirects=False, timeout=10).headers['Location']
    token = parse_qs(urlparse(loc).fragment)['access_token'][0]
    new_pw = secrets.token_urlsafe(16)
    requests.put(f'{url}/auth/v1/user', headers={**H, 'Authorization': 'Bearer ' + token}, json={'password': new_pw}, timeout=10)
    r = signin(by['redacted']['email'], new_pw)
    check('password_setup_keeps_identity', r.status_code == 200 and r.json()['user']['id'] == fm.supabase_user_id(PROJECT, 'redacted'))

    with psycopg.connect(db, autocommit=True) as conn:
        google = conn.execute("SELECT user_id::text,provider_id FROM auth.identities WHERE provider='google' ORDER BY provider_id").fetchall()
        check('google_identity_prelinked_by_subject', google == sorted([(fm.supabase_user_id(PROJECT, 'both'), 'google-sub-both'),
                                                                       (fm.supabase_user_id(PROJECT, 'google'), 'google-sub-google')], key=lambda x: x[1]), google)
        phone = conn.execute('SELECT phone IS NOT NULL,phone_confirmed_at IS NOT NULL,email FROM auth.users WHERE id=%s', (fm.supabase_user_id(PROJECT, 'phone'),)).fetchone()
        check('phone_user_imported_confirmed', phone == (True, True, None))
        meta = conn.execute('SELECT raw_app_meta_data::text FROM auth.users WHERE id=%s', (fm.supabase_user_id(PROJECT, 'claims'),)).fetchone()[0]
        check('foreign_claims_not_in_jwt_metadata', 'dawaMomRole' not in meta)
        check('foreign_claims_kept_in_ledger', conn.execute("SELECT custom_claims->>'dawaMomRole' FROM firebase_migration.accounts WHERE firebase_uid='claims'").fetchone()[0] == 'mother')
        check('squatter_untouched', conn.execute('SELECT raw_app_meta_data ? %s FROM auth.users WHERE id=%s', ('firebase_uid', squatter['id'])).fetchone()[0] is False)
        links = conn.execute("SELECT provider,subject,staff_id FROM observer_control.staff_identities ORDER BY provider").fetchall()
        check('staff_link_copied_to_same_staff_id', links == [('firebase', 'staff', staff_id), ('supabase', fm.supabase_user_id(PROJECT, 'staff'), staff_id)])
        check('no_staff_or_requests_created_by_import', conn.execute('SELECT (SELECT count(*) FROM observer_control.staff),(SELECT count(*) FROM observer_control.identity_requests)').fetchone() == (1, 0))
        for role in ('anon', 'authenticated', 'service_role'):
            try:
                with conn.transaction():
                    conn.execute(sql.SQL('SET LOCAL ROLE {}').format(sql.Identifier(role)))
                    conn.execute('SELECT count(*) FROM firebase_migration.accounts')
                check(f'{role}_cannot_read_ledger', False)
            except psycopg.errors.InsufficientPrivilege:
                check(f'{role}_cannot_read_ledger', True)
    with psycopg.connect(migrator_dsn, autocommit=True) as conn:
        for statement in ('SELECT count(*) FROM public.users', 'SELECT count(*) FROM auth.users', 'SELECT count(*) FROM observer_control.staff',
                          "INSERT INTO auth.identities(provider_id,user_id,identity_data,provider) VALUES('x',gen_random_uuid(),'{}','google')",
                          'DELETE FROM firebase_migration.events'):
            try:
                conn.execute(statement); check('migrator_denied:' + statement[:40], False)
            except (psycopg.errors.InsufficientPrivilege, psycopg.errors.RaiseException):
                check('migrator_denied:' + statement[:40], True)
        try:
            conn.execute("SELECT firebase_migration.link_oauth_identity(%s,'pending','google','attacker-sub')", (PROJECT,))
            check('oauth_link_refuses_identity_not_in_firebase_record', False)
        except psycopg.errors.InvalidParameterValue:
            check('oauth_link_refuses_identity_not_in_firebase_record', True)
    issuer = url.rstrip('/') + '/auth/v1'
    def visible_patients(subject):
        with psycopg.connect(observer_dsn) as conn:
            conn.execute("SELECT set_config('observer.issuer',%s,true),set_config('observer.subject',%s,true),set_config('observer.source',%s,true)",
                         (issuer, subject, SOURCE))
            return conn.execute('SELECT count(*) FROM public.users').fetchone()[0]
    check('migrated_staff_sees_own_facility_only', visible_patients(fm.supabase_user_id(PROJECT, 'staff')) == 1)
    for uid in ('pending', 'both', 'claims', 'disabled', 'phone'):
        check(f'imported_nonstaff_sees_no_patients:{uid}', visible_patients(fm.supabase_user_id(PROJECT, uid)) == 0)
    with psycopg.connect(db, autocommit=True) as conn:
        check('bot_tables_unchanged', bot_snapshot(conn) == before)

    rb = fm.rollback_users(PROJECT, admin, ledger, execute=True)
    with psycopg.connect(db) as conn:
        conn.execute((R / f'{FIREBASE}.down.sql').read_text())
    with psycopg.connect(db, autocommit=True) as conn:
        remaining = conn.execute("SELECT count(*) FROM auth.users WHERE raw_app_meta_data->>'migrated_from'='firebase'").fetchone()[0]
        links = conn.execute("SELECT provider FROM observer_control.staff_identities").fetchall()
        check('rollback_removes_only_migration_users', rb['deleted'] == 9 and remaining == 0 and
              conn.execute('SELECT count(*) FROM auth.users WHERE id=%s', (squatter['id'],)).fetchone()[0] == 1)
        check('rollback_keeps_original_firebase_staff_link', links == [('firebase',)])
        check('rollback_drops_schema_and_role', conn.execute("SELECT (SELECT count(*) FROM pg_namespace WHERE nspname='firebase_migration'),(SELECT count(*) FROM pg_roles WHERE rolname='rudo_migrator')").fetchone() == (0, 0))
        check('bot_tables_unchanged_after_rollback', bot_snapshot(conn) == before)
    with psycopg.connect(db) as conn:  # Re-apply after rollback works.
        conn.execute((M / f'{FIREBASE}.sql').read_text())
    check('reapply_after_rollback', True)
    admin.delete(squatter['id'])
    out = {'passed': sum(1 for k, v in checks.items() if k != 'auth_version' and (v is True or (isinstance(v, dict) and v['ok']))),
           'failed': failures, 'checks': checks}
    print(json.dumps(fm.assert_no_secrets(out), indent=2, default=str))
    (ROOT / '.local').mkdir(exist_ok=True)
    (ROOT / '.local/firebase-migration-rehearsal.json').write_text(json.dumps(out, indent=2, default=str))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()
