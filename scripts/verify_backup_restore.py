"""Verify an encrypted Rudo backup by restoring it into an ISOLATED scratch database on the LOCAL
Supabase stack (loopback :54322), then comparing with the dump itself and with live production
(read-only aggregate counts). Prints table names and counts only, never row contents.

Restored exactly: roles, application schemas (public: the six bot tables) and their data.
Counted, not restored: auth/storage platform tables (their schemas belong to Supabase service versions;
production runs newer ones than the local images). Their dump row counts are compared with production.
Plaintext exists only in a 0700 temp dir; the scratch database and temp dir are removed on exit.
Requires RUDO_BACKUP_PASSPHRASE. Usage: scripts/verify_backup_restore.sh backups/rudo-<stamp>.tar.enc
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.backup_split import split  # noqa: E402

PGBIN = Path(os.environ.get('RUDO_TEST_PGBIN', '/opt/homebrew/opt/postgresql@17/bin'))
LOCAL = os.environ.get('RUDO_RESTORE_LOCAL_URL', 'postgresql://postgres:postgres@127.0.0.1:54422/postgres')
SCRATCH = 'rudo_restore_check'
NAME = re.compile(r'^[A-Za-z0-9_]+\.[A-Za-z0-9_]+$')
BOT_TABLES = ['public.users', 'public.messages', 'public.referrals', 'public.orders', 'public.kv', 'public.user_state']


def psql(url, *args, check=True):
    return subprocess.run([str(PGBIN / 'psql'), url, '-X', '-q', *args], capture_output=True, text=True, check=check)


def linked_query(sql_text):
    with tempfile.NamedTemporaryFile('w', suffix='.sql', delete=False) as handle:
        handle.write('BEGIN READ ONLY; ' + sql_text + '; ROLLBACK;')
    try:
        run = subprocess.run(['supabase', 'db', 'query', '--linked', '-f', handle.name, '--output-format', 'json'],
                             capture_output=True, text=True, cwd=ROOT)
    finally:
        os.unlink(handle.name)
    if run.returncode != 0:
        raise SystemExit('Production read-only query failed: ' + (run.stdout + run.stderr).strip()[-400:])
    return json.JSONDecoder().raw_decode(run.stdout[run.stdout.index('{'):])[0]['rows'][0]['c']


def production_counts(tables):
    """Read-only. Tables absent in production are reported as such instead of failing the query."""
    names = ','.join(f"'{t}'" for t in tables)
    present = linked_query(f"SELECT coalesce(json_agg(n.nspname||'.'||c.relname),'[]') AS c FROM pg_class c "
                           f"JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname||'.'||c.relname IN ({names})")
    counts = linked_query('SELECT json_build_object(' + ','.join(f"'{t}',(SELECT count(*) FROM {t})" for t in present) + ') AS c') if present else {}
    return {t: counts.get(t, 'absent in production') for t in tables}


def main(archive):
    archive = Path(archive)
    if '@127.0.0.1:' not in LOCAL:
        raise SystemExit('Restore target must be the loopback local stack')
    passphrase = os.environ.get('RUDO_BACKUP_PASSPHRASE')
    if not passphrase:
        raise SystemExit('Set RUDO_BACKUP_PASSPHRASE (read -rs RUDO_BACKUP_PASSPHRASE && export RUDO_BACKUP_PASSPHRASE)')
    expected = Path(str(archive) + '.sha256').read_text().split()[0]
    if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
        raise SystemExit('Checksum mismatch: archive corrupted or altered')
    report = {'archive': archive.name, 'checksum': 'ok'}
    target = LOCAL.rsplit('/', 1)[0] + '/' + SCRATCH
    with tempfile.TemporaryDirectory() as work:
        os.chmod(work, 0o700)
        plain = Path(work) / 'b.tar'
        subprocess.run(['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '600000', '-pass', 'env:RUDO_BACKUP_PASSPHRASE',
                        '-in', str(archive), '-out', str(plain)], check=True)
        with tarfile.open(plain) as tar:
            # macOS tar adds AppleDouble '._*' metadata entries; only the three dump files are extracted.
            members = [m for m in tar.getmembers() if not Path(m.name).name.startswith('._')]
            names = sorted(m.name for m in members)
            if names != ['data.sql', 'roles.sql', 'schema.sql'] or not all(m.isfile() for m in members):
                raise SystemExit(f'Unexpected archive contents: {names}')
            tar.extractall(work, members=members, filter='data')
        report['decrypted'] = 'ok'
        dump_counts = split(Path(work) / 'data.sql', work)
        psql(LOCAL, '-c', f'DROP DATABASE IF EXISTS {SCRATCH}')
        psql(LOCAL, '-c', f'CREATE DATABASE {SCRATCH}')
        try:
            # A fresh database lacks what every Supabase database provides; recreate those containers so
            # only genuine backup defects remain as errors.
            psql(target, '-c', 'CREATE SCHEMA IF NOT EXISTS extensions; CREATE SCHEMA IF NOT EXISTS vault; '
                               'CREATE PUBLICATION supabase_realtime')
            roles = psql(target, '-f', str(Path(work) / 'roles.sql'), check=False)
            schema = psql(target, '-v', 'ON_ERROR_STOP=0', '-f', str(Path(work) / 'schema.sql'), check=False)
            errors = [line.split('ERROR:', 1)[1].strip()[:90] for line in schema.stderr.splitlines() if 'ERROR:' in line]
            # Supabase platform objects that every Supabase project already has (the CLI's dump strips them;
            # plain pg_dump includes them). Anything else is a genuine failure.
            platform = ('already exists', 'event trigger', 'function extensions.', 'pg_stat_statements',
                        'permission denied to change default privileges', 'grant options cannot be granted back')
            tolerated = [e for e in errors if any(marker in e for marker in platform)]
            # Built-in Supabase roles already exist on any target; reported for information only.
            report['roles_restore_messages'] = sum('ERROR:' in l for l in roles.stderr.splitlines())
            report['schema_restore_errors'] = {'supabase_platform_objects (expected)': len(tolerated),
                                               'other': sorted(set(e for e in errors if e not in tolerated))}
            data = psql(target, '-v', 'ON_ERROR_STOP=1', '--single-transaction', '-f', str(Path(work) / 'restorable.sql'), check=False)
            report['data_restore'] = 'ok' if data.returncode == 0 else 'FAILED: ' + data.stderr.strip()[:300]
            restored = {}
            if data.returncode == 0:
                for table in dump_counts['restorable']:
                    if NAME.match(table):
                        out = psql(target, '-At', '-c', f'SELECT count(*) FROM {table}')
                        restored[table] = int(out.stdout.strip())
        finally:
            psql(LOCAL, '-c', f'DROP DATABASE IF EXISTS {SCRATCH}', check=False)
    tables = [t for t in sorted(set(dump_counts['restorable']) | set(dump_counts['platform'])) if NAME.match(t)]
    live = production_counts(tables)
    report['tables'] = {t: {'in_backup': dump_counts['restorable'].get(t, dump_counts['platform'].get(t)),
                            'restored': restored.get(t, 'not restored (platform schema)' if t in dump_counts['platform'] else None),
                            'production_now': live.get(t)} for t in tables}
    missing_bot = [t for t in BOT_TABLES if t not in dump_counts['restorable']]
    exact = all(restored.get(t) == n for t, n in dump_counts['restorable'].items())
    report['bot_tables_missing_from_backup'] = missing_bot
    report['restored_equals_backup_for_every_application_table'] = exact and report['data_restore'] == 'ok'
    report['production_differences'] = {t: v for t, v in report['tables'].items() if v['in_backup'] != v['production_now']}
    ok = exact and report['data_restore'] == 'ok' and not missing_bot and not report['schema_restore_errors']['other']
    report['verdict'] = 'RESTORE VERIFIED' if ok else 'RESTORE NOT VERIFIED'
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1]) if len(sys.argv) == 2 else 'usage: verify_backup_restore.sh backups/rudo-<stamp>.tar.enc')
