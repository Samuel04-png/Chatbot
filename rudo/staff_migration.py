"""Staff-only Firebase Auth -> Supabase Auth migration foundation.

Server/CLI use only. Never logs password hashes, salts, signer keys, tokens or service-role keys.
Only identities that already hold an approved, active staff record are ever imported; patient
records and non-staff Firebase users are out of scope. Every imported identity is linked to its
existing staff record so roles and facility scopes are preserved, not re-derived.
"""
from dataclasses import dataclass
import base64
import binascii
import hashlib
import json
from urllib.parse import urlsplit

import psycopg
from psycopg.types.json import Jsonb
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .auth import FIREBASE_ISSUER_PREFIX, supabase_issuer
from .db import Database

REDACTED_HASH = base64.b64encode(b'REDACTED').decode()  # Returned when export lacks hash permission.


def _b64(value, name):
    """Accept standard or URL-safe base64 (Firebase exports vary); return decoded bytes."""
    if not isinstance(value, str) or not value:
        raise ValueError(f'{name} is missing')
    try:
        return base64.b64decode(value.replace('-', '+').replace('_', '/') + '=' * (-len(value) % 4), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError(f'{name} is not valid base64') from None


def _std(raw):
    return base64.b64encode(raw).decode()


@dataclass(frozen=True)
class HashParams:
    """Firebase project's SCRYPT hash_config. Values come from the environment only."""
    signer_key: bytes
    salt_separator: bytes
    rounds: int
    mem_cost: int

    @classmethod
    def from_env(cls, env):
        try:
            rounds, mem_cost = int(env.get('FIREBASE_ROUNDS', '')), int(env.get('FIREBASE_MEM_COST', ''))
        except ValueError:
            raise ValueError('FIREBASE_ROUNDS and FIREBASE_MEM_COST must be integers') from None
        if not 1 <= rounds <= 8 or not 1 <= mem_cost <= 14:
            raise ValueError('Firebase scrypt rounds must be 1-8 and mem_cost 1-14')
        return cls(_b64(env.get('FIREBASE_SIGNER_KEY'), 'FIREBASE_SIGNER_KEY'),
                   _b64(env.get('FIREBASE_SALT_SEPARATOR'), 'FIREBASE_SALT_SEPARATOR'), rounds, mem_cost)

    def __repr__(self):
        return f'HashParams(rounds={self.rounds}, mem_cost={self.mem_cost}, keys=<redacted>)'


def firebase_scrypt(password, salt_b64, params):
    """Firebase's modified scrypt: scrypt(pw, salt||sep, N=2^mem_cost, r=rounds, p=1, 32 bytes),
    used as an AES-256-CTR key (zero IV) to encrypt the signer key. Returns standard base64."""
    derived = hashlib.scrypt(password.encode('utf-8'), salt=_b64(salt_b64, 'salt') + params.salt_separator,
                             n=1 << params.mem_cost, r=params.rounds, p=1, dklen=32,
                             maxmem=256 * 1024 * 1024)
    encryptor = Cipher(algorithms.AES(derived), modes.CTR(b'\0' * 16)).encryptor()
    return _std(encryptor.update(params.signer_key) + encryptor.finalize())


def fbscrypt_hash(password_hash_b64, salt_b64, params):
    """Supabase Auth's Firebase-scrypt import format (parsed by GoTrue's $fbscrypt prefix handler).
    n is the exponent (N = 2^n); ss/sk/salt/hash are standard padded base64."""
    return ('$fbscrypt$v=1,n={n},r={r},p=1,ss={ss},sk={sk}${salt}${hash}'.format(
        n=params.mem_cost, r=params.rounds, ss=_std(params.salt_separator), sk=_std(params.signer_key),
        salt=_std(_b64(salt_b64, 'salt')), hash=_std(_b64(password_hash_b64, 'password hash'))))


def normalise_firebase_user(record):
    """Map a firebase_admin ExportedUserRecord (or equivalent dict) to a plain dict."""
    get = (lambda k: record.get(k)) if isinstance(record, dict) else (lambda k: getattr(record, k, None))
    providers = get('provider_data') or get('providers') or []
    provider_ids = sorted({p if isinstance(p, str) else (p.get('provider_id') if isinstance(p, dict) else p.provider_id)
                           for p in providers})
    password_hash = get('password_hash')
    if password_hash and 'password' not in provider_ids:
        provider_ids.append('password')
    return {'uid': get('uid'), 'email': (get('email') or '').strip() or None,
            'email_verified': bool(get('email_verified')), 'disabled': bool(get('disabled')),
            'display_name': get('display_name'), 'providers': sorted(provider_ids),
            'password_hash': password_hash, 'password_salt': get('password_salt')}


def classify(firebase_users, staff_rows, firebase_project):
    """Inventory: compare Firebase users with approved staff records for the Firebase issuer.
    Returns import candidates and every reason something is held back. Contains no hashes."""
    issuer = FIREBASE_ISSUER_PREFIX + firebase_project
    staff = {r['subject']: r for r in staff_rows if r['issuer'] == issuer}
    users = [normalise_firebase_user(u) for u in firebase_users]
    by_email = {}
    for user in users:
        if user['email']:
            by_email.setdefault(user['email'].lower(), []).append(user['uid'])
    report = {'firebase_project': firebase_project, 'issuer': issuer, 'firebase_users': len(users),
              'staff_records': len(staff), 'candidates': [], 'held': [], 'excluded_non_staff': 0,
              'staff_missing_in_firebase': sorted(set(staff) - {u['uid'] for u in users})}
    for user in users:
        row = staff.get(user['uid'])
        if row is None:
            report['excluded_non_staff'] += 1  # Not staff: never imported, not listed individually.
            continue
        reasons = []
        if row['status'] != 'active':
            reasons.append('staff_suspended')
        if user['email'] and row.get('email') and user['email'].lower() != row['email'].lower():
            reasons.append('email_differs_from_staff_record')
        if user['disabled']:
            reasons.append('firebase_user_disabled')
        if not user['email']:
            reasons.append('no_email')
        elif len(by_email[user['email'].lower()]) > 1:
            reasons.append('duplicate_email')
        elif not user['email_verified'] and 'password' not in user['providers']:
            reasons.append('unverified_email')
        if 'password' in user['providers'] and user['password_hash'] in (None, '', REDACTED_HASH):
            reasons.append('password_export_unavailable')
        unsupported = set(user['providers']) - {'password', 'google.com'}
        if unsupported:
            reasons.append('unsupported_provider:' + ','.join(sorted(unsupported)))
        entry = {'uid': user['uid'], 'staff_id': str(row['staff_id']), 'email': user['email'], 'role': row['role'],
                 'providers': user['providers'], 'email_verified': user['email_verified']}
        (report['held'] if reasons else report['candidates']).append({**entry, **({'reasons': reasons} if reasons else {})})
    return report


def import_payload(user, params, firebase_project):
    """Supabase Auth admin create-user body. Firebase UIDs are not UUIDs, so Supabase assigns a new id;
    the original UID is kept in app_metadata (server-controlled); both map to one internal staff id."""
    body = {'email': user['email'], 'email_confirm': bool(user['email_verified']),
            'app_metadata': {'firebase_uid': user['uid'], 'firebase_project': firebase_project,
                             'migrated_from': 'firebase'},
            'user_metadata': {'display_name': user['display_name']} if user.get('display_name') else {}}
    if 'password' in user['providers']:
        body['password_hash'] = fbscrypt_hash(user['password_hash'], user['password_salt'], params)
    return body


class SupabaseAdmin:
    """Minimal Supabase Auth admin client (service-role key, server/CLI only)."""
    def __init__(self, url, service_key, http=None):
        self.base = supabase_issuer(url)
        if not service_key:
            raise ValueError('SUPABASE_SERVICE_ROLE_KEY is required for the admin import')
        self._headers = {'apikey': service_key, 'Authorization': 'Bearer ' + service_key}
        if http is None:
            import requests
            http = requests
        self.http = http

    def _call(self, method, path, **kwargs):
        response = self.http.request(method, self.base + path, headers=self._headers, timeout=15, **kwargs)
        try:
            data = response.json()
        except ValueError:
            data = {}
        return response.status_code, data

    def users(self):
        page = 1
        while True:
            status, data = self._call('GET', '/admin/users', params={'page': page, 'per_page': 200})
            if status != 200:
                raise RuntimeError(f'Supabase admin list failed (HTTP {status})')
            batch = data.get('users', [])
            yield from batch
            if len(batch) < 200:
                return
            page += 1

    def create(self, body):
        status, data = self._call('POST', '/admin/users', json=body)
        if status in (200, 201):
            return data
        code = data.get('error_code') or data.get('code') or 'unknown'
        raise RuntimeError(f'Supabase admin create failed (HTTP {status}, {code})')


class LinkStore:
    """Owner/administrator connection to observer_control. Not the dashboard reader credential."""
    def __init__(self, dsn, allow_remote=False):
        Database(allow_remote=allow_remote).check_target(dsn)
        self.dsn = dsn

    def staff_rows(self):
        """Firebase login identities of staff, with the internal staff id, role and status."""
        sql = ("SELECT i.issuer,i.subject,s.id,s.role,s.status,s.email FROM observer_control.staff_identities i "
               "JOIN observer_control.staff s ON s.id=i.staff_id WHERE i.provider='firebase' ORDER BY i.subject")
        with psycopg.connect(self.dsn) as conn:
            return [dict(zip(('issuer', 'subject', 'staff_id', 'role', 'status', 'email'), row)) for row in conn.execute(sql)]

    def linked_subject(self, login_issuer, staff_id):
        with psycopg.connect(self.dsn) as conn:
            row = conn.execute('SELECT subject FROM observer_control.staff_identities WHERE issuer=%s AND staff_id=%s',
                               (login_issuer, staff_id)).fetchone()
        return row[0] if row else None

    def link(self, login_issuer, login_subject, staff_id, email, actor):
        """Attach an imported Supabase Auth identity to the existing internal staff id (one transaction)."""
        with psycopg.connect(self.dsn) as conn:
            conn.execute("INSERT INTO observer_control.staff_identities(issuer,subject,provider,staff_id,email,link_method,linked_by) "
                         "VALUES(%s,%s,'supabase',%s,%s,'auth_import',%s)", (login_issuer, login_subject, staff_id, email, actor))
            conn.execute("INSERT INTO observer_control.staff_admin_events(actor,action,target,detail) VALUES(%s,'auth_import_link',%s,%s)",
                         (actor, str(staff_id), Jsonb({'issuer': login_issuer, 'subject': login_subject})))

    def unlinked(self, login_issuer, subjects):
        """Login identities without a staff link: pending sign-ups."""
        with psycopg.connect(self.dsn) as conn:
            known = {r[0] for r in conn.execute('SELECT subject FROM observer_control.staff_identities WHERE issuer=%s', (login_issuer,))}
        return [s for s in subjects if s not in known]


def project_ref(url):
    host = urlsplit(url).hostname or ''
    return host.split('.')[0] if host.endswith('.supabase.co') else host


def run_import(report, firebase_users, params, admin, links, supabase_url, actor, execute=False, only_uid=None):
    """Idempotent: an already-linked staff member is skipped; a Supabase user created by an earlier,
    interrupted run (matched by app_metadata.firebase_uid) is linked rather than duplicated; an existing
    Supabase user with the same email but no Firebase marker is a conflict for manual review."""
    login_issuer = supabase_issuer(supabase_url)
    users = {u['uid']: u for u in (normalise_firebase_user(x) for x in firebase_users)}
    candidates = [c for c in report['candidates'] if only_uid is None or c['uid'] == only_uid]
    if only_uid and not candidates:
        raise ValueError('The requested UID is not an approved import candidate')
    existing = list(admin.users())
    by_marker = {(u.get('app_metadata') or {}).get('firebase_uid'): u for u in existing
                 if (u.get('app_metadata') or {}).get('firebase_project') == report['firebase_project']}
    by_email = {(u.get('email') or '').lower(): u for u in existing if u.get('email')}
    results = []
    for candidate in candidates:
        uid = candidate['uid']
        outcome = {'uid': uid}
        if links.linked_subject(login_issuer, candidate['staff_id']):
            outcome['result'] = 'already_linked'
        elif uid in by_marker:
            outcome['result'] = 'link_existing' if not execute else 'linked_existing'
            if execute:
                links.link(login_issuer, by_marker[uid]['id'], candidate['staff_id'], candidate['email'], actor)
        elif candidate['email'].lower() in by_email:
            outcome['result'] = 'conflict_email_exists'  # Never auto-link by email alone.
        else:
            body = import_payload(users[uid], params, report['firebase_project'])
            outcome['password'] = 'firebase_scrypt' if 'password_hash' in body else 'none (OAuth only)'
            if execute:
                created = admin.create(body)
                links.link(login_issuer, created['id'], candidate['staff_id'], candidate['email'], actor)
                outcome['result'] = 'created_and_linked'
            else:
                outcome['result'] = 'would_create'
        results.append(outcome)
    return results


def assert_no_secrets(value):
    """Defence in depth for anything the CLI scripts print or write to disk."""
    text = json.dumps(value, default=str)
    for marker in ('$fbscrypt$', 'sb_secret_', '-----BEGIN', '"password_hash"', '"password_salt"'):
        if marker in text:
            raise RuntimeError('Refusing to emit sensitive material')
    return value


def firebase_overview(firebase_users):
    """Firebase-only listing for building the approved staff/facility map. No hashes, no salts.
    Owner marks which accounts are staff and assigns role + facility scopes before any import."""
    users = [normalise_firebase_user(u) for u in firebase_users]
    counts = {}
    for user in users:
        for provider in user['providers'] or ['none']:
            counts[provider] = counts.get(provider, 0) + 1
    rows = [{'uid': u['uid'], 'email': u['email'], 'providers': u['providers'], 'email_verified': u['email_verified'],
             'disabled': u['disabled'], 'role': None, 'scopes': []} for u in sorted(users, key=lambda u: (u['email'] or '', u['uid']))]
    return {'firebase_users': len(users), 'disabled': sum(u['disabled'] for u in users),
            'by_provider': dict(sorted(counts.items())), 'accounts': rows,
            'instructions': 'Set role (admin/operator/analyst) and scopes [ACCOUNT:FACILITY] only for approved staff; leave others null.'}
