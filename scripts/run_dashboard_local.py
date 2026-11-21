"""Run the PRODUCTION dashboard on this machine only (http://localhost:8080), Firebase login (Mode A).
Reads the restricted database logins from backups/release1-dashboard.env (0600, gitignored) without
printing them, then starts gunicorn bound to 127.0.0.1. Ctrl+C stops it."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
secrets = ROOT / 'backups/release1-dashboard.env'
if oct(secrets.stat().st_mode)[-3:] != '600':
    raise SystemExit('backups/release1-dashboard.env must be readable only by you (chmod 600)')
env = dict(os.environ)
env.update(line.split('=', 1) for line in secrets.read_text().splitlines() if '=' in line)
env.update({'RUDO_MODE': 'observer', 'RUDO_OBSERVER_ALLOW_REMOTE': 'true', 'RUDO_OBSERVER_SOURCE_ID': 'rudo-production',
            'FIREBASE_PROJECT_ID': 'dawa-ca263', 'RUDO_IDENTITY_PROVIDERS': 'firebase', 'RUDO_BROWSER_AUTH': 'firebase',
            'RUDO_FIREBASE_CHECK_REVOKED': 'false', 'RUDO_ALLOWED_ORIGIN': 'http://localhost:8080',
            'RUDO_TRUST_PROXY': 'false', 'PORT': '8080',
            'WEB_CONCURRENCY': '1', 'RUDO_THREADS': '8'})  # One process: all requests share warm pools.
os.chdir(ROOT)
os.execvpe(str(ROOT / '.venv/bin/gunicorn'), ['gunicorn', '-c', 'deploy/gunicorn.conf.py', '--bind', '127.0.0.1:8080', 'wsgi:app'], env)
