"""Full Firebase Auth -> Supabase Auth account migration (every account, not only staff).

Rules (see docs/auth-migration/FULL_MIGRATION.md):
- Every Firebase account receives exactly one recorded outcome; nothing is skipped silently.
- Importing never grants dashboard access. Access exists only through observer_control.staff_identities,
  which is copied solely from an EXISTING Firebase staff link (same internal staff id, same role/scopes).
- Identity is matched only by Firebase UID: a deterministic Supabase user id (uuid5 of project+UID) plus
  app_metadata.firebase_uid. Never by email. An email/phone already used by a different Supabase user is
  a conflict for manual review.
- Disabled Firebase accounts are imported banned. Unverified emails stay unverified.
- Password hashes, salts and signer keys never reach stdout, logs or unencrypted files.
"""
import base64
import collections
import datetime as dt
import hashlib
import json
import os
import re
import uuid
from pathlib import Path

from .staff_migration import REDACTED_HASH, fbscrypt_hash

OUT_DIR = Path(os.environ.get('RUDO_MIGRATION_DIR', '~/.rudo-migration')).expanduser()
KEY_PATH = Path(os.environ.get('RUDO_MIGRATION_KEY', '~/.config/rudo/migration.key')).expanduser()
NAMESPACE = uuid.UUID('6f9d1f3e-2b8c-5a47-9e1d-7c3b5a2f8e61')  # Fixed: deterministic ids across reruns.
BAN_FOREVER = '876000h'  # ~100 years: GoTrue's way to keep an account disabled.
EMAIL_RE = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,63}$')
PHONE_RE = re.compile(r'^\+[1-9][0-9]{6,14}$')
LINKABLE_IDPS = {'google.com': 'google'}  # Firebase provider -> Supabase provider for identity rows.


# ---------- secure local files ----------

def secure_write(path, text):
    """Write outside the repository, owner-only, creating the folder 0700."""
    path = Path(path).expanduser()
    repo = Path(__file__).resolve().parents[1]
    if repo in path.resolve().parents:
        raise ValueError('Migration files must live outside the Git repository')
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as handle:
        handle.write(text)
    return path


def _key(create=False):
    if not KEY_PATH.exists():
        if not create:
            raise FileNotFoundError(f'Migration key {KEY_PATH} is missing')
        KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(KEY_PATH.parent, 0o700)
        fd = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as handle:
            handle.write(os.urandom(32))
    if oct(KEY_PATH.stat().st_mode)[-3:] != '600':
        raise PermissionError(f'{KEY_PATH} must be mode 600')
    return KEY_PATH.read_bytes()


def encrypt_export(records, path):
    """AES-256-GCM. The key file lives in ~/.config/rudo, separate from the export folder."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    plaintext = json.dumps(records, sort_keys=True, default=str).encode()
    nonce = os.urandom(12)
    blob = {'v': 1, 'alg': 'AES-256-GCM', 'sha256': hashlib.sha256(plaintext).hexdigest(), 'records': len(records),
            'nonce': base64.b64encode(nonce).decode(),
            'data': base64.b64encode(AESGCM(_key(create=True)).encrypt(nonce, plaintext, b'rudo-firebase-export')).decode()}
    return secure_write(path, json.dumps(blob)), blob['sha256']


def decrypt_export(path):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    blob = json.loads(Path(path).expanduser().read_text())
    plaintext = AESGCM(_key()).decrypt(base64.b64decode(blob['nonce']), base64.b64decode(blob['data']), b'rudo-firebase-export')
    if hashlib.sha256(plaintext).hexdigest() != blob['sha256']:
        raise ValueError('Export checksum mismatch')
    return json.loads(plaintext), blob['sha256']


# ---------- normalisation ----------

def _ms_to_iso(value):
    if value in (None, '', 0):
        return None
    try:
        return dt.datetime.fromtimestamp(int(value) / 1000, dt.timezone.utc).isoformat()
    except (TypeError, ValueError):
        return str(value)


def export_record(user):
    """firebase_admin ExportedUserRecord (or a Firebase CLI auth:export dict) -> plain dict, secrets included.
    Only ever stored encrypted."""
    if isinstance(user, dict) and 'localId' in user:  # firebase auth:export JSON shape
        mfa = [{'type': 'phone' if f.get('phoneInfo') else 'totp' if f.get('totpInfo') is not None else 'other',
                'enrolled_at': f.get('enrolledAt'), 'phone': f.get('phoneInfo')} for f in user.get('mfaInfo', [])]
        return {'uid': user['localId'], 'email': user.get('email'), 'email_verified': bool(user.get('emailVerified')),
                'phone': user.get('phoneNumber'), 'display_name': user.get('displayName'), 'photo_url': user.get('photoUrl'),
                'disabled': bool(user.get('disabled')), 'tenant_id': user.get('tenantId'),
                'providers': [{'provider': p.get('providerId'), 'provider_uid': p.get('rawId'), 'email': p.get('email')}
                              for p in user.get('providerUserInfo', [])],
                'created_at': _ms_to_iso(user.get('createdAt')), 'last_sign_in_at': _ms_to_iso(user.get('lastSignedInAt')),
                'last_refresh_at': user.get('lastRefreshAt'),
                'custom_claims': json.loads(user['customAttributes']) if user.get('customAttributes') else {},
                'mfa': mfa, 'password_hash': user.get('passwordHash'), 'password_salt': user.get('salt')}
    get = (lambda k: user.get(k)) if isinstance(user, dict) else (lambda k: getattr(user, k, None))
    meta = get('user_metadata')
    mget = (lambda k: meta.get(k)) if isinstance(meta, dict) else (lambda k: getattr(meta, k, None))
    factors = getattr(get('multi_factor'), 'enrolled_factors', None) or (get('mfa') if isinstance(user, dict) else None) or []
    mfa = [f if isinstance(f, dict) else {'type': getattr(f, 'factor_id', 'other'),
                                          'enrolled_at': str(getattr(f, 'enrollment_time', '') or ''),
                                          'phone': getattr(f, 'phone_number', None)} for f in factors]
    providers = []
    for p in get('provider_data') or get('providers') or []:
        pget = (lambda k: p.get(k)) if isinstance(p, dict) else (lambda k: getattr(p, k, None))
        providers.append({'provider': pget('provider_id') or pget('provider'), 'provider_uid': pget('uid') or pget('provider_uid'),
                          'email': pget('email')})
    return {'uid': get('uid'), 'email': get('email'), 'email_verified': bool(get('email_verified')),
            'phone': get('phone_number') or get('phone'), 'display_name': get('display_name'), 'photo_url': get('photo_url'),
            'disabled': bool(get('disabled')), 'tenant_id': get('tenant_id'), 'providers': providers,
            'created_at': _ms_to_iso(mget('creation_timestamp')) if meta else get('created_at'),
            'last_sign_in_at': _ms_to_iso(mget('last_sign_in_timestamp')) if meta else get('last_sign_in_at'),
            'last_refresh_at': _ms_to_iso(mget('last_refresh_timestamp')) if meta else get('last_refresh_at'),
            'custom_claims': get('custom_claims') or {}, 'mfa': mfa,
            'password_hash': get('password_hash'), 'password_salt': get('password_salt')}


def _hash_usable(record):
    return bool(record.get('password_hash')) and record['password_hash'] != REDACTED_HASH and bool(record.get('password_salt'))


def account_facts(user):
    """Secret-free view of one account (for worksheets, reports and the mapping table)."""
    r = user if isinstance(user, dict) and 'providers' in user and 'uid' in user and 'password_hash' in user else export_record(user)
    provider_ids = sorted({p['provider'] for p in r['providers'] if p.get('provider')})
    has_hash = _hash_usable(r)
    if r.get('password_hash') and 'password' not in provider_ids:
        provider_ids.append('password')
    return {'uid': r['uid'], 'email': (r.get('email') or '').strip() or None, 'email_verified': r['email_verified'],
            'phone': r.get('phone'), 'display_name': r.get('display_name'), 'photo_url': r.get('photo_url'),
            'disabled': r['disabled'], 'tenant_id': r.get('tenant_id'), 'providers': sorted(provider_ids),
            'provider_identities': [{'provider': p['provider'], 'provider_uid': p.get('provider_uid'), 'email': p.get('email')}
                                    for p in r['providers'] if p.get('provider') not in (None, 'password', 'phone')],
            'created_at': r.get('created_at'), 'last_sign_in_at': r.get('last_sign_in_at'),
            'custom_claim_keys': sorted((r.get('custom_claims') or {}).keys()),
            'mfa_factor_types': sorted(f.get('type') or 'other' for f in r.get('mfa') or []),
            'password_hash_present': has_hash, 'password_hash_redacted': r.get('password_hash') == REDACTED_HASH,
            'anonymous': not provider_ids and not r.get('email') and not r.get('phone')}


def summarise_accounts(facts):
    providers = collections.Counter(p for f in facts for p in (f['providers'] or ['none']))
    emails = collections.Counter(f['email'].lower() for f in facts if f['email'])
    year = collections.Counter((f['created_at'] or '????')[:4] for f in facts)
    recent = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)
    def _recent(f):
        try:
            return f['last_sign_in_at'] and dt.datetime.fromisoformat(f['last_sign_in_at']) >= recent
        except ValueError:
            return False
    return {'total_users': len(facts), 'by_provider': dict(sorted(providers.items())),
            'email_present': sum(bool(f['email']) for f in facts), 'email_verified': sum(f['email_verified'] for f in facts),
            'phone_present': sum(bool(f['phone']) for f in facts), 'disabled': sum(f['disabled'] for f in facts),
            'anonymous': sum(f['anonymous'] for f in facts), 'password_hash_exportable': sum(f['password_hash_present'] for f in facts),
            'password_hash_redacted': sum(f['password_hash_redacted'] for f in facts),
            'mfa_enrolled': sum(bool(f['mfa_factor_types']) for f in facts),
            'custom_claims_present': sum(bool(f['custom_claim_keys']) for f in facts),
            'custom_claim_keys': sorted({k for f in facts for k in f['custom_claim_keys']}),
            'tenant_users': sum(bool(f['tenant_id']) for f in facts),
            'duplicate_email_groups': sum(1 for c in emails.values() if c > 1),
            'signed_in_last_90_days': sum(bool(_recent(f)) for f in facts), 'created_by_year': dict(sorted(year.items()))}


# ---------- planning ----------

def supabase_user_id(project, uid):
    return str(uuid.uuid5(NAMESPACE, f'{project}:{uid}'))


def plan(records, project, supabase_users, staff_links, exclusions=None):
    """One decision per Firebase account. supabase_users: existing Supabase Auth users (dicts);
    staff_links: {firebase_uid: staff_id} from observer_control.staff_identities (firebase issuer);
    exclusions: {uid: reason} decided by the owner (still reported, never silent)."""
    exclusions = exclusions or {}
    facts = [account_facts(r) for r in records]
    emails = collections.Counter(f['email'].lower() for f in facts if f['email'])
    by_id = {u['id']: u for u in supabase_users}
    by_email = {(u.get('email') or '').lower(): u for u in supabase_users if u.get('email')}
    by_phone = {(u.get('phone') or '').lstrip('+'): u for u in supabase_users if u.get('phone')}
    decisions = []
    for record, f in zip(records, facts):
        target = supabase_user_id(project, f['uid'])
        d = {'uid': f['uid'], 'supabase_user_id': target, 'remediation': [], 'staff_id': staff_links.get(f['uid'])}
        existing = by_id.get(target)
        marker = (existing or {}).get('app_metadata', {}).get('firebase_uid') if existing else None
        email = f['email'].lower() if f['email'] else None
        if f['uid'] in exclusions:
            d['action'], d['remediation'] = 'excluded_by_owner', [exclusions[f['uid']]]
        elif existing and marker == f['uid']:
            d['action'] = 'already_imported'
        elif existing:
            d['action'], d['remediation'] = 'manual', ['supabase_id_collision']
        elif f['tenant_id']:
            d['action'], d['remediation'] = 'manual', ['firebase_tenant_user']
        elif email and emails[email] > 1:
            d['action'], d['remediation'] = 'manual', ['duplicate_email_in_firebase']
        elif email and not EMAIL_RE.match(email):
            d['action'], d['remediation'] = 'manual', ['invalid_email']
        elif email and email in by_email:
            d['action'], d['remediation'] = 'manual', ['email_used_by_other_supabase_user']  # Never auto-linked.
        elif f['phone'] and f['phone'].lstrip('+') in by_phone:
            d['action'], d['remediation'] = 'manual', ['phone_used_by_other_supabase_user']
        elif not email and not (f['phone'] and PHONE_RE.match(f['phone'])):
            d['action'], d['remediation'] = 'manual', ['no_email_or_phone' if f['anonymous'] else 'no_usable_login_identifier']
        else:
            d['action'] = 'create'
        # Password and sign-in consequences (reported for every account, including manual ones).
        if 'password' in f['providers']:
            d['password'] = 'preserved' if f['password_hash_present'] else 'needs_setup'
            if not f['password_hash_present']:
                d['remediation'].append('password_hash_unavailable_send_reset')
        else:
            d['password'] = 'none'
        if email and not f['email_verified']:
            d['remediation'].append('email_unverified_must_confirm')
        for identity in f['provider_identities']:
            if identity['provider'] not in LINKABLE_IDPS:
                d['remediation'].append('provider_not_migrated:' + identity['provider'])
        if any(i['provider'] in LINKABLE_IDPS for i in f['provider_identities']):
            d['remediation'].append('google_sign_in_needs_supabase_google_provider')
        if f['phone'] and not email:
            d['remediation'].append('sms_provider_required_for_phone_sign_in')
        if f['mfa_factor_types']:
            d['remediation'].append('mfa_must_reenrol')  # Firebase does not export MFA secrets.
        if d['password'] in ('none',) and not f['phone'] and not any(i['provider'] in LINKABLE_IDPS for i in f['provider_identities']) and email:
            d['remediation'].append('password_setup_via_reset')
        d['disabled'] = f['disabled']
        d['dashboard_access'] = 'staff_link' if d['staff_id'] else 'none'
        decisions.append(d)
    assert len(decisions) == len(records) and len({d['uid'] for d in decisions}) == len(records)
    return facts, decisions


def create_payload(record, decision, project, params):
    """Supabase Auth admin create-user body. app_metadata carries only the Firebase marker; Firebase custom
    claims are NOT copied into the JWT (they may belong to another application) - they stay in the mapping table."""
    f = account_facts(record)
    body = {'id': decision['supabase_user_id'],
            'app_metadata': {'firebase_uid': f['uid'], 'firebase_project': project, 'migrated_from': 'firebase'},
            'user_metadata': {k: v for k, v in (('display_name', f['display_name']), ('avatar_url', f['photo_url'])) if v}}
    if f['email']:
        body['email'], body['email_confirm'] = f['email'], bool(f['email_verified'])
    if f['phone'] and PHONE_RE.match(f['phone']):
        body['phone'], body['phone_confirm'] = f['phone'], True  # Firebase phone numbers are SMS-verified.
    if decision['password'] == 'preserved':
        body['password_hash'] = fbscrypt_hash(record['password_hash'], record['password_salt'], params)
    if f['disabled']:
        body['ban_duration'] = BAN_FOREVER
    return body


def report_counts(facts, decisions):
    actions = collections.Counter(d['action'] for d in decisions)
    remediation = collections.Counter(r for d in decisions for r in d['remediation'])
    importable = [d for d in decisions if d['action'] in ('create', 'already_imported')]
    return {'firebase_users': len(facts), 'decisions': len(decisions), 'by_action': dict(sorted(actions.items())),
            'staged_for_import': len(importable),
            'password_preserved': sum(d['password'] == 'preserved' for d in importable),
            'password_setup_required': sum(d['password'] == 'needs_setup' or 'password_setup_via_reset' in d['remediation'] for d in importable),
            'manual_investigation': actions.get('manual', 0), 'excluded_by_owner': actions.get('excluded_by_owner', 0),
            'imported_disabled': sum(d['disabled'] for d in importable),
            'staff_links_preserved': sum(bool(d['staff_id']) for d in importable),
            'dashboard_access_granted_by_import': 0, 'remediation': dict(sorted(remediation.items()))}


def assert_no_secrets(value):
    text = json.dumps(value, default=str)
    for marker in ('$fbscrypt$', 'sb_secret_', '-----BEGIN', '"password_hash":', '"password_salt":'):
        if marker in text:
            raise RuntimeError('Refusing to emit sensitive material')
    return value


def source_sha256(record):
    """Fingerprint of the secret-free account facts plus claims (detects source changes between runs)."""
    payload = {**account_facts(record), 'custom_claims': record.get('custom_claims') or {}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


# ---------- ledger (rudo_migrator login, firebase_migration schema) ----------

class Ledger:
    def __init__(self, dsn, allow_remote=False):
        from .db import Database
        Database(allow_remote=allow_remote).check_target(dsn)
        self.dsn = dsn

    def _conn(self):
        import psycopg
        return psycopg.connect(self.dsn, autocommit=True)

    def start(self, project, export_sha, mode, actor):
        with self._conn() as c:
            return str(c.execute('INSERT INTO firebase_migration.runs(firebase_project,export_sha256,mode,actor) VALUES(%s,%s,%s,%s) RETURNING id',
                                 (project, export_sha, mode, actor)).fetchone()[0])

    def finish(self, run_id, counts):
        from psycopg.types.json import Jsonb
        with self._conn() as c:
            c.execute('UPDATE firebase_migration.runs SET finished_at=now(),counts=%s WHERE id=%s', (Jsonb(counts), run_id))

    def staff_links(self, project):
        with self._conn() as c:
            return {uid: str(sid) for uid, sid, _ in c.execute('SELECT * FROM firebase_migration.firebase_staff_links(%s)', (project,))}

    def rows(self, project):
        with self._conn() as c:
            cur = c.execute('SELECT firebase_uid,supabase_user_id,status,password_status,disabled,email,phone,staff_id '
                            'FROM firebase_migration.accounts WHERE firebase_project=%s', (project,))
            cols = [d.name for d in cur.description]
            return {r[0]: dict(zip(cols, r)) for r in cur}

    def record(self, run_id, project, record, decision, status, supabase_user_id=None, error=None):
        from psycopg.types.json import Jsonb
        f = account_facts(record)
        with self._conn() as c, c.transaction():
            c.execute('''INSERT INTO firebase_migration.accounts AS a(firebase_project,firebase_uid,supabase_user_id,planned_user_id,email,
                         email_verified,phone,display_name,photo_url,disabled,tenant_id,providers,provider_identities,custom_claims,
                         mfa_factor_types,firebase_created_at,firebase_last_sign_in_at,password_status,status,remediation,source_sha256,
                         last_run,error_code)
                         VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                         ON CONFLICT(firebase_project,firebase_uid) DO UPDATE SET
                           supabase_user_id=coalesce(EXCLUDED.supabase_user_id,a.supabase_user_id),
                           status=CASE WHEN a.status='imported' AND EXCLUDED.status<>'imported' THEN a.status ELSE EXCLUDED.status END,
                           email=EXCLUDED.email,email_verified=EXCLUDED.email_verified,phone=EXCLUDED.phone,
                           display_name=EXCLUDED.display_name,photo_url=EXCLUDED.photo_url,disabled=EXCLUDED.disabled,
                           providers=EXCLUDED.providers,provider_identities=EXCLUDED.provider_identities,custom_claims=EXCLUDED.custom_claims,
                           mfa_factor_types=EXCLUDED.mfa_factor_types,password_status=EXCLUDED.password_status,remediation=EXCLUDED.remediation,
                           source_sha256=EXCLUDED.source_sha256,last_run=EXCLUDED.last_run,error_code=EXCLUDED.error_code,updated_at=now()''',
                      (project, f['uid'], supabase_user_id, decision['supabase_user_id'], f['email'], f['email_verified'], f['phone'],
                       f['display_name'], f['photo_url'], f['disabled'], f['tenant_id'], f['providers'], Jsonb(f['provider_identities']),
                       Jsonb(record.get('custom_claims') or {}), f['mfa_factor_types'], f['created_at'], f['last_sign_in_at'],
                       decision['password'], status, decision['remediation'], source_sha256(record), run_id, error))
            c.execute('INSERT INTO firebase_migration.events(run_id,firebase_uid,event,detail) VALUES(%s,%s,%s,%s)',
                      (run_id, f['uid'], status if not error else 'failed', Jsonb({'action': decision['action'], **({'error': error} if error else {})})))

    def copy_staff_link(self, project, uid, issuer, actor):
        with self._conn() as c:
            return c.execute('SELECT firebase_migration.copy_staff_link(%s,%s,%s,%s)', (project, uid, issuer, actor)).fetchone()[0]

    def link_oauth(self, project, uid, provider, provider_uid):
        with self._conn() as c:
            return c.execute('SELECT firebase_migration.link_oauth_identity(%s,%s,%s,%s)', (project, uid, provider, provider_uid)).fetchone()[0]


class AuthAdmin:
    """Supabase Auth admin API (service-role key; CLI only). Never logs request bodies."""
    def __init__(self, url, service_key, http=None):
        from .auth import supabase_issuer
        self.base = supabase_issuer(url)
        if not service_key:
            raise ValueError('SUPABASE_SERVICE_ROLE_KEY is required')
        self._headers = {'apikey': service_key, 'Authorization': 'Bearer ' + service_key}
        if http is None:
            import requests
            http = requests
        self.http = http

    def _call(self, method, path, **kw):
        r = self.http.request(method, self.base + path, headers=self._headers, timeout=30, **kw)
        try:
            data = r.json()
        except ValueError:
            data = {}
        return r.status_code, data

    def users(self):
        page = 1
        while True:
            status, data = self._call('GET', '/admin/users', params={'page': page, 'per_page': 1000})
            if status != 200:
                raise RuntimeError(f'Supabase admin list failed (HTTP {status})')
            batch = data.get('users', [])
            yield from batch
            if len(batch) < 1000:
                return
            page += 1

    def get(self, user_id):
        status, data = self._call('GET', f'/admin/users/{user_id}')
        return data if status == 200 else None

    def create(self, body):
        status, data = self._call('POST', '/admin/users', json=body)
        if status in (200, 201):
            return data, None
        return None, str(data.get('error_code') or data.get('code') or f'http_{status}')[:80]

    def delete(self, user_id):
        status, _ = self._call('DELETE', f'/admin/users/{user_id}')
        return status in (200, 204)


def execute_plan(records, project, export_sha, admin, ledger, supabase_url, params, actor, execute=False,
                 only_uid=None, limit=None, exclusions=None, link_oauth=True):
    """Idempotent and restartable: deterministic user ids + ledger + app_metadata marker. Dry run writes nothing."""
    from .auth import supabase_issuer
    issuer = supabase_issuer(supabase_url)
    existing = list(admin.users())
    staff_links = ledger.staff_links(project) if ledger else {}
    facts, decisions = plan(records, project, existing, staff_links, exclusions)
    counts = report_counts(facts, decisions)
    if not execute:
        return {'mode': 'dry_run', **counts}, decisions
    run_id = ledger.start(project, export_sha, 'execute', actor)
    by_uid = {r['uid']: r for r in records}
    processed, outcome = 0, collections.Counter()
    for d in decisions:
        if only_uid and d['uid'] != only_uid:
            continue
        if limit is not None and processed >= limit:
            break
        record = by_uid[d['uid']]
        if d['action'] in ('manual', 'excluded_by_owner'):
            ledger.record(run_id, project, record, d, d['action'])
            outcome[d['action']] += 1
            continue
        processed += 1
        user_id, error = None, None
        if d['action'] == 'already_imported':
            user_id = d['supabase_user_id']
        else:
            created, error = admin.create(create_payload(record, d, project, params))
            if created:
                user_id = created['id']
            else:
                again = admin.get(d['supabase_user_id'])  # Created by an interrupted earlier run?
                if again and (again.get('app_metadata') or {}).get('firebase_uid') == d['uid']:
                    user_id, error = again['id'], None
        if not user_id:
            ledger.record(run_id, project, record, d, 'failed', error=error or 'create_failed')
            outcome['failed'] += 1
            continue
        ledger.record(run_id, project, record, d, 'imported', supabase_user_id=user_id)
        outcome['imported'] += 1
        if link_oauth:
            for identity in account_facts(record)['provider_identities']:
                if identity['provider'] in LINKABLE_IDPS and identity.get('provider_uid'):
                    outcome['oauth_' + ledger.link_oauth(project, d['uid'], LINKABLE_IDPS[identity['provider']], identity['provider_uid'])] += 1
        if d['staff_id']:
            outcome['staff_' + ledger.copy_staff_link(project, d['uid'], issuer, actor)] += 1
    summary = {'mode': 'execute', 'run_id': run_id, **counts, 'this_run': dict(sorted(outcome.items()))}
    ledger.finish(run_id, summary)
    return summary, decisions


def reconcile(records, project, admin, ledger):
    """Every source account must be in the ledger with a terminal status; every imported row must match
    a Supabase user carrying the same Firebase marker, email, phone and ban state."""
    rows = ledger.rows(project)
    users = {u['id']: u for u in admin.users()}
    problems = []
    for record in records:
        f = account_facts(record)
        row = rows.get(f['uid'])
        if not row:
            problems.append((f['uid'], 'missing_from_ledger')); continue
        if row['status'] in ('staged', 'failed'):
            problems.append((f['uid'], 'not_terminal:' + row['status'])); continue
        if row['status'] != 'imported':
            continue
        u = users.get(str(row['supabase_user_id']))
        if not u:
            problems.append((f['uid'], 'supabase_user_missing')); continue
        if (u.get('app_metadata') or {}).get('firebase_uid') != f['uid']:
            problems.append((f['uid'], 'marker_mismatch'))
        if (u.get('email') or None) != (f['email'].lower() if f['email'] else None):
            problems.append((f['uid'], 'email_mismatch'))
        if f['disabled'] and not u.get('banned_until'):
            problems.append((f['uid'], 'disabled_not_banned'))
        if bool(u.get('email_confirmed_at')) != (bool(f['email']) and f['email_verified']):
            problems.append((f['uid'], 'verification_mismatch'))
    status = collections.Counter(r['status'] for r in rows.values())
    migrated = sum(1 for u in users.values() if (u.get('app_metadata') or {}).get('firebase_project') == project)
    return {'source_accounts': len(records), 'ledger_rows': len(rows), 'ledger_by_status': dict(sorted(status.items())),
            'supabase_users_with_firebase_marker': migrated, 'supabase_users_total': len(users),
            'problems': len(problems), 'problem_detail': [{'uid': u, 'problem': p} for u, p in problems][:200],
            'coverage_complete': not problems and len(rows) >= len(records)}


def rollback_users(project, admin, ledger, execute=False):
    """Delete only Supabase users that this migration created (ledger id AND Firebase marker)."""
    rows = ledger.rows(project)
    targets = []
    for row in rows.values():
        if row['supabase_user_id']:
            u = admin.get(str(row['supabase_user_id']))
            if u and (u.get('app_metadata') or {}).get('migrated_from') == 'firebase' and \
                    (u.get('app_metadata') or {}).get('firebase_uid') == row['firebase_uid']:
                targets.append(str(row['supabase_user_id']))
    deleted = sum(admin.delete(t) for t in targets) if execute else 0
    return {'mode': 'execute' if execute else 'dry_run', 'would_delete' if not execute else 'deleted': deleted if execute else len(targets)}
