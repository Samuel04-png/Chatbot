"""Environment checker never prints secrets and flags the compromised key; Firebase-only worksheet."""
import json
import os

from scripts import check_env, staff_inventory

SIGNER = 'Q' * 86 + '=='


def write_key(tmp_path, key_id):
    path = tmp_path / 'firebase-service.json'
    path.write_text(json.dumps({'type': 'service_account', 'project_id': 'p', 'private_key_id': key_id, 'private_key': 'PRIVATE-SENTINEL'}))
    return path


def status(rows):return {r['name']: r['status'] for r in rows}


def test_checker_reports_status_without_values(tmp_path, capsys):
    write_key(tmp_path, 'ab12cd34' + '0' * 32)
    env = {'SUPABASE_URL': 'https://abcd.supabase.co', 'SUPABASE_ANON_KEY': 'sb_publishable_SENTINEL1',
           'SUPABASE_SERVICE_ROLE_KEY': 'sb_secret_SENTINEL2', 'FIREBASE_PROJECT_ID': 'p',
           'GOOGLE_APPLICATION_CREDENTIALS': './firebase-service.json', 'FIREBASE_SIGNER_KEY': SIGNER,
           'FIREBASE_SALT_SEPARATOR': 'Bw==', 'FIREBASE_ROUNDS': '8', 'FIREBASE_MEM_COST': '14'}
    (tmp_path / '.env').write_text('\n'.join(f'{k}={v}' for k, v in env.items()))
    rows = check_env.check(check_env.parse(tmp_path / '.env'), root=tmp_path)
    assert {k: v for k, v in status(rows).items() if k in env} == {k: 'ok' for k in env}
    text = json.dumps(rows)
    for secret in ('SENTINEL1', 'SENTINEL2', SIGNER, 'PRIVATE-SENTINEL'):
        assert secret not in text
    assert 'project ref abcd' in text and 'key id ab12cd34' in text


def test_checker_flags_compromised_key_secret_in_browser_slot_and_unsafe_switches(tmp_path):
    write_key(tmp_path, '43a1573c' + '0' * 32)
    rows = check_env.check({'SUPABASE_URL': 'http://abcd.supabase.co', 'SUPABASE_ANON_KEY': 'sb_secret_x',
                            'FIREBASE_PROJECT_ID': 'p', 'GOOGLE_APPLICATION_CREDENTIALS': './firebase-service.json',
                            'FIREBASE_SIGNER_KEY': 'short', 'RUDO_ENABLE_MESSAGE_DELIVERY': 'true',
                            'RUDO_BROWSER_AUTH': 'okta'}, root=tmp_path)
    s = status(rows)
    assert s['GOOGLE_APPLICATION_CREDENTIALS'] == 'invalid' and 'COMPROMISED' in json.dumps(rows)
    assert s['SUPABASE_URL'] == s['SUPABASE_ANON_KEY'] == s['FIREBASE_SIGNER_KEY'] == s['RUDO_BROWSER_AUTH'] == 'invalid'
    assert s['RUDO_ENABLE_MESSAGE_DELIVERY'] == 'warning'
    (tmp_path / '.env').write_text('RUDO_ENABLE_REMOTE_WRITES=true\n')
    assert check_env.main([str(tmp_path / '.env')]) == 1


def test_firebase_only_worksheet_has_no_hash_material(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    users = [{'uid': 'b', 'email': 'b@example.test', 'email_verified': True, 'providers': ['google.com']},
             {'uid': 'a', 'email': 'a@example.test', 'email_verified': True, 'disabled': True,
              'password_hash': 'aGFzaA==', 'password_salt': 'c2FsdA=='}]
    report = staff_inventory.main(['--firebase-only'], env={'FIREBASE_PROJECT_ID': 'p', 'GOOGLE_APPLICATION_CREDENTIALS': 'x'},
                                  firebase_users=users)
    assert report['by_provider'] == {'google.com': 1, 'password': 1} and report['disabled'] == 1
    assert [a['uid'] for a in report['accounts']] == ['a', 'b'] and report['accounts'][0]['role'] is None
    written = (tmp_path / '.local/firebase-accounts-worksheet.json')
    assert 'aGFzaA' not in written.read_text() and 'c2FsdA' not in written.read_text()
    assert oct(written.stat().st_mode)[-3:] == '600'


def test_release_credentials_send_only_scram_verifiers(tmp_path):
    from scripts import release1_credentials as rc
    sql_path, env_path = rc.main(['--pooler-host', 'pooler.example.test'], out_dir=tmp_path / 'b')
    sql, env = sql_path.read_text(), env_path.read_text()
    assert oct(sql_path.stat().st_mode)[-3:] == oct(env_path.stat().st_mode)[-3:] == '600'
    assert sql.count("PASSWORD 'SCRAM-SHA-256$4096:") == 3 and sql.startswith('BEGIN;')
    for line in env.strip().splitlines()[:3]:
        password = line.split(':', 2)[2].split('@')[0]
        assert password not in sql  # Plaintext never appears in what is sent to the database.
        assert 'sslmode=verify-full' in line and '.cktfbpnxpfbyroqzuibc:' in line
    assert len(env.splitlines()[3].split('=', 1)[1]) >= 32
    # Known-answer check against RFC 7677's SCRAM-SHA-256 derivation (salt/iterations fixed).
    import base64
    v = rc.scram_verifier('pencil', 4096, base64.b64decode('W22ZaJ0SNY7soEsUEjb6gQ=='))
    assert v == 'SCRAM-SHA-256$4096:W22ZaJ0SNY7soEsUEjb6gQ==$WG5d8oPm3OtcPnkdi4Uo7BkeZkBFzpcXkuLmtbsT4qY=:wfPLwcE6nTWhTAmQ7tl2KeoiWGPlZqQxSrmfPwDl2dU='


def test_backup_split_restores_application_data_and_counts_platform_rows(tmp_path):
    from scripts.backup_split import split
    dump = tmp_path / 'data.sql'
    dump.write_text('SET session_replication_role = replica;\n'
                    'COPY "auth"."users" ("id", "email") FROM stdin;\nu1\tsecret@example.test\n\\.\n'
                    'COPY "public"."messages" ("id", "phone", "role", "message") FROM stdin;\n1\t2600\tuser\thi\n2\t2600\tbot\tok\n\\.\n'
                    'COPY "storage"."buckets" ("id") FROM stdin;\n\\.\n'
                    "SELECT pg_catalog.setval('\"public\".\"messages_id_seq\"', 2, true);\n"
                    "SELECT pg_catalog.setval('\"auth\".\"refresh_tokens_id_seq\"', 9, true);\n")
    counts = split(dump, tmp_path)
    assert counts == {'restorable': {'public.messages': 2}, 'platform': {'auth.users': 1, 'storage.buckets': 0}}
    restorable = (tmp_path / 'restorable.sql').read_text()
    assert 'secret@example.test' not in restorable and 'auth' not in restorable
    assert 'messages_id_seq' in restorable and restorable.count('\\.') == 1
    (tmp_path / 'bad.sql').write_text('COPY "public"."users" ("phone") FROM stdin;\n1\n')
    import pytest
    with pytest.raises(SystemExit):split(tmp_path / 'bad.sql', tmp_path)
