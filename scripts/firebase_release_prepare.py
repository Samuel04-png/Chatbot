"""Prepare (do NOT apply) the Firebase migration release for owner approval.

Writes, mode 600 in the gitignored backups/ folder:
  firebase-apply.sql    BOTH migrations + the rudo_migrator SCRAM verifier in ONE transaction (all or nothing)
  firebase-migrator.env RUDO_MIGRATOR_DATABASE_URL (pooler, sslmode=verify-full) for the import CLI
The plaintext migrator password exists only in firebase-migrator.env; the SQL carries only its SCRAM verifier.
Apply (after approval): supabase db query --linked -f backups/firebase-apply.sql
"""
import hashlib
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.release1_credentials import scram_verifier  # noqa: E402

MIGRATIONS = ['20261123063840_firebase_account_migration.sql', '20261123085525_firebase_data_landing.sql']
REF, POOLER = 'cktfbpnxpfbyroqzuibc', 'aws-1-eu-west-1.pooler.supabase.com'


def write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(text)


def main(out_dir=ROOT / 'backups'):
    password = secrets.token_urlsafe(32)
    parts = ['BEGIN;']
    for name in MIGRATIONS:
        body = (ROOT / 'supabase/migrations' / name).read_text()
        parts += [f'-- ===== {name} (sha256 {hashlib.sha256(body.encode()).hexdigest()[:16]}) =====', body]
    parts += [f"ALTER ROLE rudo_migrator PASSWORD '{scram_verifier(password)}';", 'COMMIT;']
    out_dir.mkdir(exist_ok=True, mode=0o700)
    apply_sql = out_dir / 'firebase-apply.sql'
    write_private(apply_sql, '\n'.join(parts) + '\n')
    cert = ROOT / 'deploy/certs/prod-supabase.crt'
    write_private(out_dir / 'firebase-migrator.env',
                  f'RUDO_MIGRATOR_DATABASE_URL=postgresql://rudo_migrator.{REF}:{quote(password, safe="")}@{POOLER}:5432/postgres'
                  f'?sslmode=verify-full&sslrootcert={cert}\nRUDO_MIGRATOR_ALLOW_REMOTE=true\n')
    digest = hashlib.sha256(apply_sql.read_bytes()).hexdigest()
    print(f'Prepared {apply_sql} (sha256 {digest}) and backups/firebase-migrator.env. Nothing was applied.')
    return apply_sql, digest


if __name__ == '__main__':
    main()
