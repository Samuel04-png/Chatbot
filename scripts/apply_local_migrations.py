"""Local-loopback-only migration runner with checksums. Never uses linked CLI settings."""
import hashlib
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rudo.db import Database
import psycopg


def apply(dsn):
    Database().check_target(dsn)  # hard-coded remote prohibition for this tool
    with psycopg.connect(dsn) as c:
        c.execute('SELECT pg_advisory_xact_lock(761120)')
        c.execute('CREATE SCHEMA IF NOT EXISTS rudo_local_migrations')
        c.execute('REVOKE ALL ON SCHEMA rudo_local_migrations FROM PUBLIC')
        c.execute('''CREATE TABLE IF NOT EXISTS rudo_local_migrations.ledger
                     (name text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())''')
        for path in sorted((Path(__file__).resolve().parents[1]/'staging/private').glob('*.sql')):
            text=path.read_text();checksum=hashlib.sha256(text.encode()).hexdigest()
            old=c.execute('SELECT checksum FROM rudo_local_migrations.ledger WHERE name=%s',(path.name,)).fetchone()
            if old:
                if old[0]!=checksum:raise RuntimeError('Migration checksum mismatch; refusing schema drift')
                continue
            c.execute(text)
            c.execute('INSERT INTO rudo_local_migrations.ledger(name,checksum) VALUES(%s,%s)',(path.name,checksum))


if __name__=='__main__':
    apply(os.environ.get('RUDO_LOCAL_DATABASE_URL',''))
    print('Local migrations verified/applied. Remote targets are prohibited by this tool.')
