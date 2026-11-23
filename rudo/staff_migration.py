"""Firebase password-hash primitives and staff identity links shared by the account migration.

Server/CLI use only. Never logs password hashes, salts, signer keys, tokens or service-role keys.
The full-account migration (every Firebase account, staff or not) lives in rudo/firebase_migration.py.
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


def assert_no_secrets(value):
    """Defence in depth for anything the CLI scripts print or write to disk."""
    text = json.dumps(value, default=str)
    for marker in ('$fbscrypt$', 'sb_secret_', '-----BEGIN', '"password_hash"', '"password_salt"'):
        if marker in text:
            raise RuntimeError('Refusing to emit sensitive material')
    return value


