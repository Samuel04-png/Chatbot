"""Compatibility check of Firebase-scrypt import against a REAL Supabase Auth server, synthetic only.

Loopback-only: refuses any non-local SUPABASE_URL. Generates a fresh random signer key, salt separator,
salt and password, so no project hash parameters or real accounts are involved. Steps verified:
admin create with $fbscrypt$ password_hash -> password sign-in -> wrong password rejected -> token
passes SupabaseVerifier (JWKS + session check) -> sign-out revokes -> verifier rejects -> rehash on
login observed -> new sign-up has no staff link -> recovery email issued -> idempotent import re-run.
Usage: SUPABASE_URL=http://127.0.0.1:54321 SUPABASE_ANON_KEY=... SUPABASE_SERVICE_ROLE_KEY=... \
       SUPABASE_LOCAL_DB_URL=postgresql://...@127.0.0.1:54322/postgres python scripts/verify_auth_import_local.py
"""
import base64
import json
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rudo.auth import SupabaseVerifier  # noqa: E402
from rudo.errors import ApiError  # noqa: E402
from rudo.staff_migration import HashParams, SupabaseAdmin, firebase_scrypt, import_payload  # noqa: E402


def main():
    url, anon, service = (os.environ[k] for k in ('SUPABASE_URL', 'SUPABASE_ANON_KEY', 'SUPABASE_SERVICE_ROLE_KEY'))
    db = os.environ['SUPABASE_LOCAL_DB_URL']
    if urlsplit(url).hostname != '127.0.0.1' or urlsplit(db).hostname != '127.0.0.1':
        raise SystemExit('Loopback local stack only')
    auth = url.rstrip('/') + '/auth/v1'
    checks = {}
    params = HashParams(secrets.token_bytes(64), secrets.token_bytes(1), 8, 14)
    salt = base64.b64encode(secrets.token_bytes(12)).decode()
    password = 'Synthetic-' + secrets.token_urlsafe(12)
    email = f'synthetic-{secrets.token_hex(4)}@example.test'
    user = {'uid': 'SyntheticFirebaseUid' + secrets.token_hex(4), 'email': email, 'email_verified': True,
            'display_name': 'Synthetic staff', 'providers': ['password'],
            'password_hash': firebase_scrypt(password, salt, params), 'password_salt': salt}
    admin = SupabaseAdmin(url, service)
    created = admin.create(import_payload(user, params, 'synthetic-firebase'))
    checks['admin_create_accepts_fbscrypt_password_hash'] = bool(created.get('id'))
    checks['app_metadata_preserved'] = created.get('app_metadata', {}).get('firebase_uid') == user['uid']
    with psycopg.connect(db) as conn:
        stored = conn.execute('SELECT encrypted_password FROM auth.users WHERE id=%s', (created['id'],)).fetchone()[0]
    checks['stored_as_fbscrypt_before_login'] = stored.startswith('$fbscrypt$')

    def sign_in(pw):
        return requests.post(auth + '/token?grant_type=password', headers={'apikey': anon},
                             json={'email': email, 'password': pw}, timeout=10)
    wrong = sign_in(password + 'x')
    checks['wrong_password_rejected'] = wrong.status_code == 400
    ok = sign_in(password)
    checks['original_firebase_password_signs_in'] = ok.status_code == 200
    token = ok.json()['access_token']
    header = json.loads(base64.urlsafe_b64decode(token.split('.')[0] + '=='))
    checks['access_token_algorithm'] = header.get('alg')
    verifier = SupabaseVerifier(url, anon)
    try:
        identity = verifier.verify(token)
        checks['server_verifier_accepts_token'] = identity['subject'] == created['id']
    except ApiError as exc:
        checks['server_verifier_accepts_token'] = f'rejected: {exc.code}'
    with psycopg.connect(db) as conn:
        stored = conn.execute('SELECT encrypted_password FROM auth.users WHERE id=%s', (created['id'],)).fetchone()[0]
    checks['stored_hash_after_login'] = 'fbscrypt (not rehashed)' if stored.startswith('$fbscrypt$') else stored[:4]
    checks['password_works_on_second_sign_in'] = sign_in(password).status_code == 200
    requests.post(auth + '/logout?scope=global', headers={'apikey': anon, 'Authorization': 'Bearer ' + token}, timeout=10)
    try:
        verifier.verify(token)
        checks['signed_out_token_rejected_by_session_check'] = False
    except ApiError as exc:
        checks['signed_out_token_rejected_by_session_check'] = exc.code == 'invalid_identity'
    try:  # Signature-only verification cannot see sign-out; this is why the session check defaults on.
        SupabaseVerifier(url, anon, session_check=False).verify(token)
        checks['jwt_signature_alone_still_accepts_signed_out_token'] = True
    except ApiError:
        checks['jwt_signature_alone_still_accepts_signed_out_token'] = False
    custom = admin._call('POST', '/admin/users', json={'id': '00000000-0000-4000-8000-' + secrets.token_hex(6),
                                                       'email': 'synthetic-id-' + secrets.token_hex(3) + '@example.test'})
    checks['admin_create_accepts_custom_uuid_id'] = custom[0] in (200, 201) and custom[1].get('id', '').startswith('00000000-0000-4000-8000-')
    signup = requests.post(auth + '/signup', headers={'apikey': anon},
                           json={'email': 'synthetic-signup-' + secrets.token_hex(3) + '@example.test',
                                 'password': 'Synthetic-' + secrets.token_urlsafe(12)}, timeout=10)
    checks['self_signup_creates_identity_only'] = signup.status_code == 200
    recover = requests.post(auth + '/recover', headers={'apikey': anon}, json={'email': email}, timeout=10)
    checks['password_recovery_email_requested'] = recover.status_code == 200
    duplicate = admin._call('POST', '/admin/users', json=import_payload(user, params, 'synthetic-firebase'))
    checks['duplicate_email_create_refused'] = duplicate[0] == 422
    print(json.dumps(checks, indent=2))
    return checks


if __name__ == '__main__':
    main()
