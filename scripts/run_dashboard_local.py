"""Run the PRODUCTION dashboard on this machine only (http://localhost:8080), Supabase Auth login (Mode C).
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
# Browser-safe Supabase values only (URL + publishable key) come from .env; never the service-role key.
public = dict(line.split('=', 1) for line in (ROOT / '.env').read_text().splitlines() if line.startswith(('SUPABASE_URL=', 'SUPABASE_ANON_KEY=')))
if public.get('SUPABASE_URL', '').rstrip('/') != 'https://cktfbpnxpfbyroqzuibc.supabase.co' or not public.get('SUPABASE_ANON_KEY'):
    raise SystemExit('.env must hold the production SUPABASE_URL and SUPABASE_ANON_KEY (publishable key)')
env.update(public)
env.update({'RUDO_MODE': 'observer', 'RUDO_OBSERVER_ALLOW_REMOTE': 'true', 'RUDO_OBSERVER_SOURCE_ID': 'rudo-production',
            'RUDO_IDENTITY_PROVIDERS': 'supabase', 'RUDO_BROWSER_AUTH': 'supabase',
            'SUPABASE_GOOGLE_ENABLED': 'false', 'RUDO_SUPABASE_SESSION_CHECK': 'true', 'RUDO_ALLOWED_ORIGIN': 'http://localhost:8080',
            'RUDO_TRUST_PROXY': 'false', 'PORT': '8080',
            'WEB_CONCURRENCY': '1', 'RUDO_THREADS': '8'})  # One process: all requests share warm pools.
# Staff replies switch on only when everything they need is present (otherwise the app stays read-only).
needed = ('RUDO_SENDER_DATABASE_URL', 'WHATSAPP_TOKEN', 'WHATSAPP_PHONE_NUMBER_ID')
env['RUDO_ENABLE_STAFF_REPLIES'] = 'true' if all(env.get(k) for k in needed) else 'false'
env.setdefault('WHATSAPP_API_VERSION', 'v19.0')  # Same Graph API version as the bot.
print('Staff replies:', 'ON' if env['RUDO_ENABLE_STAFF_REPLIES'] == 'true' else
      'off (missing: ' + ', '.join(k for k in needed if not env.get(k)) + ')', flush=True)
os.chdir(ROOT)
os.execvpe(str(ROOT / '.venv/bin/gunicorn'), ['gunicorn', '-c', 'deploy/gunicorn.conf.py', '--bind', '127.0.0.1:8080', 'wsgi:app'], env)
