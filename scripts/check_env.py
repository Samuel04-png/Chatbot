"""Report which configuration variables are present, missing or invalid. Never prints secret values.
Only non-secret facts are shown: Supabase project ref, key type, key-file ID prefix, booleans.
Usage: .venv/bin/python scripts/check_env.py [path/to/.env]"""
import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rudo.auth import assert_browser_safe_key, supabase_issuer  # noqa: E402
from rudo.staff_migration import project_ref  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
COMPROMISED_KEY_IDS = ('43a1573c',)  # Exposed 2026-11-20; must never be used again.
STAGES = {'local': 'local synthetic work', 'staging': 'staging verification', 'production': 'production'}


def parse(path):
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def b64len(value):
    try:
        return len(base64.b64decode(value.replace('-', '+').replace('_', '/') + '=' * (-len(value) % 4), validate=True))
    except Exception:
        return None


def check(env, root=ROOT):
    rows = []

    def add(name, status, detail, needed):
        rows.append({'name': name, 'status': status, 'detail': detail, 'needed_for': needed})

    url = env.get('SUPABASE_URL', '')
    if not url:
        add('SUPABASE_URL', 'missing', '', 'staging')
    else:
        try:
            supabase_issuer(url)
            add('SUPABASE_URL', 'ok', f'project ref {project_ref(url)}', 'staging')
        except ValueError as exc:
            add('SUPABASE_URL', 'invalid', str(exc), 'staging')
    anon = env.get('SUPABASE_ANON_KEY', '')
    if not anon:
        add('SUPABASE_ANON_KEY', 'missing', '', 'staging')
    else:
        try:
            assert_browser_safe_key(anon)
            kind = 'publishable key' if anon.startswith('sb_publishable_') else 'legacy anon JWT'
            add('SUPABASE_ANON_KEY', 'ok', kind + ' (browser-safe)', 'staging')
        except ValueError as exc:
            add('SUPABASE_ANON_KEY', 'invalid', str(exc) + ' - REMOVE IT and rotate if it is a secret key', 'staging')
    service = env.get('SUPABASE_SERVICE_ROLE_KEY', '')
    if service:
        kind = 'secret key' if service.startswith('sb_secret_') else 'set'
        add('SUPABASE_SERVICE_ROLE_KEY', 'ok', kind + ' (server/CLI only)', 'staging import')
    else:
        add('SUPABASE_SERVICE_ROLE_KEY', 'missing', 'not needed until a staging import', 'staging import')
    for name in ('RUDO_IDENTITY_PROVIDERS', 'RUDO_BROWSER_AUTH'):
        value = env.get(name, 'firebase')
        allowed = {'RUDO_IDENTITY_PROVIDERS': ('firebase', 'supabase', 'firebase,supabase'),
                   'RUDO_BROWSER_AUTH': ('firebase', 'supabase')}[name]
        add(name, 'ok' if value in allowed else 'invalid', value if value in allowed else 'unsupported value', 'local')
    project = env.get('FIREBASE_PROJECT_ID', '')
    add('FIREBASE_PROJECT_ID', 'ok' if project else 'missing', project, 'staging')
    creds = env.get('GOOGLE_APPLICATION_CREDENTIALS', '')
    path = (root / creds) if creds and not Path(creds).is_absolute() else Path(creds) if creds else None
    if not creds:
        add('GOOGLE_APPLICATION_CREDENTIALS', 'missing', '', 'staging inventory/import')
    elif not path.is_file():
        add('GOOGLE_APPLICATION_CREDENTIALS', 'missing', 'points to a file that does not exist yet', 'staging inventory/import')
    else:
        try:
            data = json.loads(path.read_text())
            key_id = str(data.get('private_key_id', ''))
            if key_id.startswith(COMPROMISED_KEY_IDS):
                add('GOOGLE_APPLICATION_CREDENTIALS', 'invalid', 'this is the COMPROMISED key - delete it and use the new key', 'staging inventory/import')
            elif data.get('type') != 'service_account' or data.get('project_id') != project:
                add('GOOGLE_APPLICATION_CREDENTIALS', 'invalid', 'not a service-account key for FIREBASE_PROJECT_ID', 'staging inventory/import')
            else:
                add('GOOGLE_APPLICATION_CREDENTIALS', 'ok', f'key id {key_id[:8]}...', 'staging inventory/import')
        except (ValueError, OSError):
            add('GOOGLE_APPLICATION_CREDENTIALS', 'invalid', 'not readable JSON', 'staging inventory/import')
    signer, separator = env.get('FIREBASE_SIGNER_KEY', ''), env.get('FIREBASE_SALT_SEPARATOR', '')
    add('FIREBASE_SIGNER_KEY', 'missing' if not signer else 'ok' if b64len(signer) == 64 else 'invalid',
        '' if not signer else 'base64, 64 bytes' if b64len(signer) == 64 else 'expected base64 of 64 bytes', 'staging import')
    add('FIREBASE_SALT_SEPARATOR', 'missing' if not separator else 'ok' if b64len(separator) else 'invalid',
        '' if separator else '', 'staging import')
    for name, expected in (('FIREBASE_ROUNDS', '8'), ('FIREBASE_MEM_COST', '14')):
        value = env.get(name, '')
        add(name, 'ok' if value == expected else 'missing' if not value else 'check', value, 'staging import')
    remote = env.get('RUDO_OBSERVER_ALLOW_REMOTE') == 'true'
    for name, role in (('RUDO_OBSERVER_DATABASE_URL', 'rudo_observer'), ('RUDO_OBSERVER_AUDIT_DATABASE_URL', 'rudo_observer_audit'),
                       ('RUDO_STAFF_ADMIN_DATABASE_URL', 'rudo_staff_admin')):
        dsn = env.get(name, '')
        if not dsn:
            add(name, 'missing', f'login {role}; created by the Release 1 migration', 'production')
            continue
        try:
            from psycopg.conninfo import conninfo_to_dict
            info = conninfo_to_dict(dsn)
        except Exception:
            add(name, 'invalid', 'not a valid connection string', 'production');continue
        user = (info.get('user') or '').split('.')[0]
        problems = []
        if user != role:
            problems.append(f'must log in as {role}')
        if remote and info.get('sslmode') != 'verify-full':
            problems.append('sslmode=verify-full required')
        if remote and info.get('sslrootcert') and not Path(info['sslrootcert']).is_file() and not info['sslrootcert'].startswith('/app/'):
            problems.append('sslrootcert file not found')
        add(name, 'invalid' if problems else 'ok', '; '.join(problems) or f"{role} @ {info.get('host')}", 'production')
    secret = env.get('RUDO_CURSOR_SECRET', '')
    add('RUDO_CURSOR_SECRET', 'ok' if len(secret) >= 32 else ('invalid' if secret or remote else 'missing'),
        'set' if len(secret) >= 32 else '32+ random characters, required in production', 'production')
    origin = env.get('RUDO_ALLOWED_ORIGIN', '')
    add('RUDO_ALLOWED_ORIGIN', 'ok' if origin.startswith('https://') or not remote else 'invalid',
        origin or 'the dashboard https origin', 'production')
    add('RUDO_FIREBASE_CHECK_REVOKED', 'ok', env.get('RUDO_FIREBASE_CHECK_REVOKED', 'true') + (
        ' (needs a NEW service-account key)' if env.get('RUDO_FIREBASE_CHECK_REVOKED', 'true') != 'false' else
        ' (revocation via staff suspension only until a new key exists)'), 'production')
    for name in ('RUDO_CONTROL_ADMIN_DATABASE_URL', 'RUDO_OBSERVER_SOURCE_ID', 'RUDO_AUTH_IMPORT_ALLOWED_REF'):
        add(name, 'ok' if env.get(name) else 'missing', 'set' if env.get(name) else 'needed at release time', 'release')
    for name in ('RUDO_ENABLE_REMOTE_WRITES', 'RUDO_ENABLE_MESSAGE_DELIVERY', 'RUDO_STAFF_ADMIN_ALLOW_REMOTE'):
        value = env.get(name, 'false')
        add(name, 'ok' if value == 'false' else 'warning', 'disabled' if value == 'false' else 'ENABLED - must stay false', 'safety')
    if env.get('RUDO_MODE', 'observer') != 'observer':
        add('RUDO_MODE', 'warning', 'not observer', 'safety')
    return rows


def main(argv=None):
    path = Path((argv or sys.argv[1:] or [ROOT / '.env'])[0])
    if not path.exists():
        print(f'{path} not found');return 1
    rows = check(parse(path))
    width = max(len(r['name']) for r in rows)
    for r in rows:
        print(f"{r['name']:<{width}}  {r['status']:<8} {r['needed_for']:<24} {r['detail']}")
    return 1 if any(r['status'] in ('invalid', 'warning') for r in rows) else 0


if __name__ == '__main__':
    sys.exit(main())
