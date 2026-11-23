"""Release rehearsal on a LOCAL Supabase stack (Supabase's own Postgres image, real roles, real Auth).

Loopback only. Synthetic rows only. Steps:
 1. Create the six bot tables from the production schema dump (schema only) or the fixture.
 2. Snapshot ACLs/policies/RLS of the bot tables. Write synthetic rows as service_role (the bot's role).
 3. Apply supabase/migrations/20261121120000_rudo_staff_control.sql as "postgres" (non-superuser) in one transaction.
 4. Verify: service_role still reads/writes all six tables; anon/authenticated/service_role have no access
    to observer_control; restricted logins see only mapped rows and minimal columns.
 5. End to end: real Supabase Auth sign-in (ES256) -> Flask SupabaseVerifier -> observer -> staff admin approval.
 6. Apply the rollback; verify bot-table ACLs/policies/RLS are identical to step 2; repeat apply+rollback.
Usage: SUPABASE_URL=http://127.0.0.1:54321 SUPABASE_ANON_KEY=... SUPABASE_SERVICE_ROLE_KEY=... \
  SUPABASE_LOCAL_DB_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres \
  .venv/bin/python scripts/verify_migration_supabase_local.py [production-public-schema.sql]
"""
import json
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.release1_credentials import scram_verifier  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MIGRATION = ROOT / 'supabase/migrations/20261121120000_rudo_staff_control.sql'
ROLLBACK = ROOT / 'supabase/rollback/20261121120000_rudo_staff_control.down.sql'
REPLIES = ROOT / 'supabase/migrations/20261121150000_rudo_staff_replies.sql'
REPLIES_ROLLBACK = ROOT / 'supabase/rollback/20261121150000_rudo_staff_replies.down.sql'
TABLES = ('users', 'messages', 'referrals', 'orders', 'kv', 'user_state')
SOURCE = 'rehearsal-source'


def state(conn):
    """Everything about the bot tables that the migration must leave as it found it."""
    return conn.execute('''SELECT json_build_object(
      'acl',(SELECT json_object_agg(relname,coalesce(relacl::text,'')) FROM pg_class WHERE relnamespace='public'::regnamespace AND relname=ANY(%s)),
      'rls',(SELECT json_object_agg(relname,relrowsecurity::text||relforcerowsecurity::text) FROM pg_class WHERE relnamespace='public'::regnamespace AND relname=ANY(%s)),
      'policies',(SELECT coalesce(json_agg(tablename||'.'||policyname ORDER BY 1),'[]') FROM pg_policies WHERE schemaname='public'),
      'column_acl',(SELECT coalesce(json_agg(table_name||'.'||column_name||':'||grantee||':'||privilege_type ORDER BY 1),'[]')
                    FROM information_schema.column_privileges WHERE table_schema='public' AND table_name=ANY(%s)
                    AND grantee NOT IN ('postgres','anon','authenticated','service_role','supabase_admin')),
      'schema_acl',(SELECT nspacl::text FROM pg_namespace WHERE nspname='public'))''', (list(TABLES),) * 3).fetchone()[0]


def bot_round_trip(conn):
    """Simulate the bot's service_role reads and writes on every table, then undo them."""
    with conn.transaction(force_rollback=True):
        conn.execute('SET LOCAL ROLE service_role')
        conn.execute("INSERT INTO public.users(phone,user_id,language,step,state) VALUES('260999000001','B1','english','s','{}')")
        conn.execute("INSERT INTO public.messages(phone,role,message,message_en) VALUES('260999000001','user','hi','hi')")
        conn.execute("UPDATE public.messages SET message_en='x' WHERE phone='260999000001'")
        conn.execute("INSERT INTO public.referrals(phone,source) VALUES('260999000001','Chelstone Clinic flyer')")
        conn.execute("INSERT INTO public.orders(phone,product,quantity,status) VALUES('260999000001','p',1,'pending')")
        conn.execute("INSERT INTO public.kv(key,value) VALUES('rehearsal','v')")
        conn.execute("DELETE FROM public.kv WHERE key='rehearsal'")
        conn.execute('SELECT count(*) FROM public.user_state').fetchone()
        return conn.execute("SELECT count(*) FROM public.messages WHERE phone='260999000001'").fetchone()[0] == 1


def main():
    url, anon, service = os.environ['SUPABASE_URL'], os.environ['SUPABASE_ANON_KEY'], os.environ['SUPABASE_SERVICE_ROLE_KEY']
    db = os.environ['SUPABASE_LOCAL_DB_URL']
    if urlsplit(url).hostname != '127.0.0.1' or urlsplit(db).hostname != '127.0.0.1':
        raise SystemExit('Loopback local stack only')
    checks = {}
    schema_dump = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    with psycopg.connect(db, autocommit=True) as conn:
        if conn.execute('SELECT current_user').fetchone()[0] != 'postgres' or conn.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()[0]:
            raise SystemExit('Must run as the non-superuser "postgres" role, as on Supabase')
        if conn.execute("SELECT 1 FROM pg_namespace WHERE nspname='observer_control'").fetchone():
            conn.execute(ROLLBACK.read_text())
        for table in TABLES:
            conn.execute(f'DROP TABLE IF EXISTS public.{table} CASCADE')
        if schema_dump:
            dump_sql = schema_dump.read_text()
            if re.search(r'^\s*(INSERT|COPY)\b', dump_sql, re.M | re.I):
                raise SystemExit('Schema dump must not contain data')
            conn.execute(dump_sql)
            checks['bot_tables_from'] = 'production schema-only dump'
        else:
            conn.execute((ROOT / 'staging/observer/source_fixture.sql').read_text())
            for table in TABLES:
                conn.execute(f'GRANT ALL ON public.{table} TO anon,authenticated,service_role')
            checks['bot_tables_from'] = 'synthetic fixture'
        before = state(conn)
        checks['bot_service_role_round_trip_before'] = bot_round_trip(conn)
        # Synthetic rows written the way the bot writes them.
        conn.execute('SET ROLE service_role')
        for i, (phone, source) in enumerate([('260000000501', 'Chelstone Clinic flyer'), ('260000000502', "N'gombe Clinic Poster 1"),
                                             ('260000000503', 'Cancer Awareness')]):
            conn.execute("INSERT INTO public.users(phone,user_id,language,step,state) VALUES(%s,%s,'english','menu','{}')", (phone, f'R{i}'))
            conn.execute("INSERT INTO public.messages(phone,role,message,message_en) VALUES(%s,'user','Rehearsal question','INTERNAL')", (phone,))
            conn.execute("INSERT INTO public.messages(phone,role,message) VALUES(%s,'bot','Rehearsal answer')", (phone,))
            conn.execute('INSERT INTO public.referrals(phone,source) VALUES(%s,%s)', (phone, source))
        conn.execute("INSERT INTO public.orders(phone,product,quantity,status,address) VALUES('260000000501','Rehearsal product',1,'pending','ADDRESS')")
        conn.execute('RESET ROLE')
    # 3. Apply exactly as the release will: one transaction, role postgres.
    with psycopg.connect(db) as conn:
        conn.execute(MIGRATION.read_text())
    with psycopg.connect(db) as conn:
        conn.execute(REPLIES.read_text())
    checks['migration_applied_as_postgres'] = True
    checks['replies_migration_applied_as_postgres'] = True
    passwords = {r: secrets.token_urlsafe(24) for r in ('rudo_observer', 'rudo_observer_audit', 'rudo_staff_admin', 'rudo_sender')}
    with psycopg.connect(db, autocommit=True) as conn:
        for role, password in passwords.items():
            # Same method as the release: only a locally computed SCRAM verifier reaches the server.
            conn.execute(sql.SQL('ALTER ROLE {} PASSWORD {}').format(sql.Identifier(role), sql.Literal(scram_verifier(password))))
        after = state(conn)
        checks['bot_service_role_round_trip_after'] = bot_round_trip(conn)
        added_columns = sorted(set(after['column_acl']) - set(before['column_acl']))
        checks['bot_tables_diff'] = {
            'table_acl_unchanged': after['acl'] == before['acl'], 'rls_unchanged': after['rls'] == before['rls'],
            'schema_acl_change': [before['schema_acl'], after['schema_acl']] if before['schema_acl'] != after['schema_acl'] else 'unchanged',
            'policies_added': sorted(set(after['policies']) - set(before['policies'])),
            'policies_removed': sorted(set(before['policies']) - set(after['policies'])),
            'column_grants_added': added_columns,
            'column_grants_removed': sorted(set(before['column_acl']) - set(after['column_acl']))}
        diff = checks['bot_tables_diff']
        checks['only_change_on_bot_tables_is_rudo_observer'] = (
            diff['table_acl_unchanged'] and diff['rls_unchanged'] and not diff['policies_removed'] and not diff['column_grants_removed']
            and diff['policies_added'] == [f'{t}.rudo_observer_read' for t in ('messages', 'orders', 'referrals', 'users')]
            and all(':rudo_observer:SELECT' in c for c in added_columns)
            and (diff['schema_acl_change'] == 'unchanged' or 'rudo_observer=U' in diff['schema_acl_change'][1]))
        checks['policies_unchanged_by_replies_migration'] = sorted(set(after['policies']) - set(before['policies'])) == [
            f'{t}.rudo_observer_read' for t in ('messages', 'orders', 'referrals', 'users')]
        for role in ('anon', 'authenticated', 'service_role'):
            checks[f'{role}_has_no_observer_control_access'] = not conn.execute(
                "SELECT has_schema_privilege(%s,'observer_control','USAGE')", (role,)).fetchone()[0]
        # Facilities, one staff admin (Supabase login created below), mappings for two of three phones.
        conn.execute("INSERT INTO observer_control.facilities(source_id,account_id,facility_id,display_name) VALUES"
                     "(%s,'rudo-whatsapp','chelstone-clinic','Chelstone Clinic'),(%s,'rudo-whatsapp','ngombe-clinic','Ngombe Clinic')", (SOURCE, SOURCE))
    for role in ('rudo_observer', 'rudo_observer_audit', 'rudo_staff_admin', 'rudo_sender'):
        dsn = make_conninfo(db, user=role, password=passwords[role])
        with psycopg.connect(dsn, autocommit=True) as conn:
            for statement in ('SELECT message_en FROM public.messages', 'SELECT * FROM public.kv', 'SELECT address FROM public.orders',
                        'INSERT INTO public.messages(phone,role,message) VALUES($$x$$,$$bot$$,$$x$$)',
                        'SELECT * FROM observer_control.staff_identities', 'CREATE TABLE public.rudo_probe(x int)'):
                try:
                    conn.execute(statement)
                    checks[f'{role}_denied: {statement[:40]}'] = False
                except (psycopg.errors.InsufficientPrivilege, psycopg.errors.ReadOnlySqlTransaction):
                    pass
        checks[f'{role}_least_privilege'] = not any(k.startswith(f'{role}_denied') for k in checks)
    # 5. Real Supabase Auth sign-in -> Flask -> restricted database.
    auth = url.rstrip('/') + '/auth/v1'
    email, password = f'rehearsal-admin-{secrets.token_hex(3)}@example.test', 'Rehearsal-' + secrets.token_urlsafe(12)
    created = requests.post(auth + '/admin/users', headers={'apikey': service, 'Authorization': 'Bearer ' + service},
                            json={'email': email, 'password': password, 'email_confirm': True}, timeout=10).json()
    token = requests.post(auth + '/token?grant_type=password', headers={'apikey': anon},
                          json={'email': email, 'password': password}, timeout=10).json()['access_token']
    from app import create_app
    config = {'MODE': 'observer', 'IDENTITY_PROVIDERS': 'supabase', 'BROWSER_AUTH': 'supabase', 'SUPABASE_URL': url,
              'SUPABASE_ANON_KEY': anon, 'OBSERVER_SOURCE_ID': SOURCE, 'CURSOR_SECRET': secrets.token_urlsafe(32),
              'OBSERVER_DATABASE_URL': make_conninfo(db, user='rudo_observer', password=passwords['rudo_observer']),
              'OBSERVER_AUDIT_DATABASE_URL': make_conninfo(db, user='rudo_observer_audit', password=passwords['rudo_observer_audit']),
              'STAFF_ADMIN_DATABASE_URL': make_conninfo(db, user='rudo_staff_admin', password=passwords['rudo_staff_admin'])}
    client = create_app(config).test_client()
    headers = {'Authorization': 'Bearer ' + token}
    checks['ready_endpoint'] = client.get('/readyz').json
    pending = client.get('/api/me', headers=headers)
    checks['real_supabase_signup_pending'] = pending.status_code == 403 and pending.json['error'] == 'staff_required'
    with psycopg.connect(db) as conn:  # Owner bootstrap of the first admin (as staff_admin.py bootstrap-admin does).
        sid = conn.execute("INSERT INTO observer_control.staff(email,role,created_by) VALUES(%s,'admin','rehearsal') RETURNING id", (email,)).fetchone()[0]
        conn.execute("INSERT INTO observer_control.staff_identities VALUES(%s,%s,'supabase',%s,%s,'bootstrap','rehearsal')",
                     (auth, created['id'], sid, email))
        conn.execute("INSERT INTO observer_control.staff_scopes(staff_id,source_id,account_id,facility_id,granted_by) VALUES(%s,%s,'rudo-whatsapp','chelstone-clinic','rehearsal')",
                     (sid, SOURCE))
        conn.execute("INSERT INTO observer_control.source_mappings(source_id,phone,account_id,facility_id,approved,approved_by) VALUES"
                     "(%s,'260000000501','rudo-whatsapp','chelstone-clinic',true,'rehearsal'),(%s,'260000000502','rudo-whatsapp','ngombe-clinic',true,'rehearsal')",
                     (SOURCE, SOURCE))
    me = client.get('/api/me', headers=headers).json
    checks['real_supabase_admin_resolves_to_staff_id'] = me.get('staffId') == str(sid) and me.get('provider') == 'supabase'
    rows = client.get('/api/conversations', headers=headers).json['items']
    checks['facility_scope_enforced'] = [r['phone'] for r in rows] == ['260000000501']
    history = client.get('/api/conversations/' + rows[0]['id'], headers=headers).json['messages']
    checks['history_ordered_and_minimal'] = [m['role'] for m in history] == ['user', 'bot'] and 'message_en' not in history[0]
    checks['orders_scoped'] = [o['product'] for o in client.get('/api/orders', headers=headers).json['items']] == ['Rehearsal product']
    checks['analytics_scoped'] = client.get('/api/analytics', headers=headers).json['counts']['captured_messages'] == 2
    invite = client.post('/api/admin/invitations', headers=headers, json={'email': 'nurse@example.test', 'role': 'operator',
                         'scopes': [{'account': 'rudo-whatsapp', 'facility': 'chelstone-clinic'}]})
    checks['admin_invite_via_rudo_staff_admin'] = invite.status_code == 201
    with psycopg.connect(db, autocommit=True) as conn:
        checks['bot_service_role_round_trip_with_dashboard_active'] = bot_round_trip(conn)
    # 6. Rollback, compare, and prove the cycle is repeatable.
    with psycopg.connect(db, autocommit=True) as conn:
        conn.execute(REPLIES_ROLLBACK.read_text())
        conn.execute(ROLLBACK.read_text())
        checks['rollback_restores_bot_table_state'] = state(conn) == before
        checks['rollback_keeps_bot_rows'] = conn.execute('SELECT count(*) FROM public.messages').fetchone()[0] == 6
    with psycopg.connect(db) as conn:
        conn.execute(MIGRATION.read_text())
    with psycopg.connect(db) as conn:
        conn.execute(REPLIES.read_text())
    with psycopg.connect(db, autocommit=True) as conn:
        conn.execute(REPLIES_ROLLBACK.read_text())
        conn.execute(ROLLBACK.read_text())
        checks['second_apply_and_rollback_cycle'] = state(conn) == before
        checks['bot_service_role_round_trip_after_rollback'] = bot_round_trip(conn)
    print(json.dumps(checks, indent=2, default=str))
    return checks


if __name__ == '__main__':
    main()
