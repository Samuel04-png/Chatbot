"""Release 1: generate passwords for the three restricted logins WITHOUT sending plaintext to the database.

Postgres stores SCRAM-SHA-256 verifiers; we compute them locally and set them with ALTER ROLE ... PASSWORD
'<verifier>'. Outputs (both 0600, gitignored backups/ folder):
  backups/release1-set-passwords.sql   verifiers only (safe to send; not reusable as passwords)
  backups/release1-dashboard.env       the dashboard's connection strings: copy into the hosting platform's
                                       secret settings, then DELETE this file.
Usage: .venv/bin/python scripts/release1_credentials.py --pooler-host aws-1-eu-west-1.pooler.supabase.com
"""
import argparse
import base64
import hashlib
import hmac
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
ROLES = {'rudo_observer': 'RUDO_OBSERVER_DATABASE_URL', 'rudo_observer_audit': 'RUDO_OBSERVER_AUDIT_DATABASE_URL',
         'rudo_staff_admin': 'RUDO_STAFF_ADMIN_DATABASE_URL'}


def scram_verifier(password, iterations=4096, salt=None):
    salt = salt or secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations)
    client_key = hmac.new(salted, b'Client Key', hashlib.sha256).digest()
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.new(salted, b'Server Key', hashlib.sha256).digest()
    b64 = lambda raw: base64.b64encode(raw).decode()
    return f'SCRAM-SHA-256${iterations}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}'


def set_password_sql(passwords):
    lines = ['BEGIN;']
    for role, password in passwords.items():
        lines.append(f"ALTER ROLE {role} PASSWORD '{scram_verifier(password)}';")
    lines.append('COMMIT;')
    return '\n'.join(lines) + '\n'


def main(argv=None, out_dir=ROOT / 'backups'):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--pooler-host', required=True)
    parser.add_argument('--project-ref', default='cktfbpnxpfbyroqzuibc')
    parser.add_argument('--sslrootcert', default='/app/deploy/certs/prod-supabase.crt')
    args = parser.parse_args(argv)
    passwords = {role: secrets.token_urlsafe(32) for role in ROLES}
    out_dir.mkdir(exist_ok=True, mode=0o700)
    sql_path, env_path = out_dir / 'release1-set-passwords.sql', out_dir / 'release1-dashboard.env'
    for path, content in ((sql_path, set_password_sql(passwords)), (env_path, '\n'.join(
            f'{var}=postgresql://{role}.{args.project_ref}:{quote(passwords[role], safe="")}@{args.pooler_host}:5432/postgres'
            f'?sslmode=verify-full&sslrootcert={args.sslrootcert}' for role, var in ROLES.items())
            + f'\nRUDO_CURSOR_SECRET={secrets.token_urlsafe(48)}\n')):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(content)
    print(f'Wrote {sql_path} (verifiers only) and {env_path} (secrets: copy to hosting settings, then delete).')
    return sql_path, env_path


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
