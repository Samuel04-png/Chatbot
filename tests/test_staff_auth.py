"""Supabase Auth verification, browser-key safety and Firebase-scrypt import format. No network."""
import base64
import json
import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app import create_app
from rudo.auth import (IssuerRouter, SupabaseVerifier, assert_browser_safe_key, browser_auth_config, build_verifier,
                       supabase_issuer)
from rudo.errors import ApiError
from rudo.staff_migration import HashParams, assert_no_secrets, fbscrypt_hash, firebase_scrypt

URL = 'https://abcdefghijklmnopqrst.supabase.co'
ISS = URL + '/auth/v1'
KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())


def unsigned(payload):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip('=')
    return f"{enc({'alg': 'none'})}.{enc(payload)}.sig"


class Keys:
    def __init__(self, key=KEY, fail=False):self.key,self.fail=key,fail
    def get_signing_key_from_jwt(self, token):
        if self.fail:raise jwt.PyJWKClientConnectionError('down')
        return type('K', (), {'key': self.key.public_key()})()


class Response:
    def __init__(self, status, body=None):self.status_code,self.body=status,body
    def json(self):
        if self.body is None:raise ValueError()
        return self.body


class Http:
    def __init__(self, response=None, error=None):self.response,self.error,self.calls=response,error,[]
    def get(self, url, **kw):
        self.calls.append((url, kw['headers']))
        if self.error:raise self.error
        return self.response


def token(sub=None, key=KEY, alg='ES256', kid='k1', **overrides):
    now = int(time.time())
    claims = {'iss': ISS, 'aud': 'authenticated', 'sub': sub or str(uuid4()), 'role': 'authenticated',
              'exp': now + 600, 'iat': now, 'session_id': str(uuid4()), **overrides}
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={'kid': kid} if kid else None), claims


def verifier(http=None, keys=None, check=True):
    return SupabaseVerifier(URL, 'sb_publishable_x', session_check=check, jwks_client=keys or Keys(),
                            http=http or Http(Response(200, {})))


def test_valid_supabase_token_with_live_session():
    value, claims = token()
    http = Http(Response(200, {'id': claims['sub']}))
    http.response.body['email'] = 'staff@example.test'; http.response.body['email_confirmed_at'] = '2026-11-01T00:00:00Z'
    assert verifier(http).verify(value) == {'issuer': ISS, 'subject': claims['sub'], 'provider': 'supabase',
                                            'email': 'staff@example.test', 'email_verified': True}
    url, headers = http.calls[0]
    assert url == ISS + '/user' and headers['Authorization'] == 'Bearer ' + value and headers['apikey'] == 'sb_publishable_x'


@pytest.mark.parametrize('overrides', [{'iss': 'https://evil.supabase.co/auth/v1'}, {'aud': 'anon'}, {'role': 'anon'},
                                       {'role': 'service_role'}, {'is_anonymous': True}, {'sub': 'not-a-uuid'},
                                       {'exp': int(time.time()) - 3600}, {'aud': None}, {'exp': None}])
def test_invalid_claims_rejected(overrides):
    value, _ = token(**overrides)
    with pytest.raises(ApiError) as exc:verifier(check=False).verify(value)
    assert exc.value.status == 401


def test_wrong_signature_hs256_missing_kid_and_garbage_rejected():
    for value in (token(key=OTHER_KEY)[0], jwt.encode({'sub': str(uuid4())}, 'x' * 32, algorithm='HS256', headers={'kid': 'k'}),
                  token(kid=None)[0], 'not-a-jwt', unsigned({'iss': ISS})):
        with pytest.raises(ApiError) as exc:verifier(check=False).verify(value)
        assert exc.value.status == 401


@pytest.mark.parametrize('response,status', [(Response(401, {}), 401), (Response(403, {}), 401), (Response(500, {}), 503),
                                             (Response(200, None), 503), (Response(200, {'id': 'someone-else'}), 401),
                                             (Response(200, 'banned_until'), 401)])
def test_session_check_outcomes(response, status):
    value, claims = token()
    if response.body == 'banned_until':response.body = {'id': claims['sub'], 'banned_until': '2999-01-01T00:00:00Z'}
    with pytest.raises(ApiError) as exc:verifier(Http(response)).verify(value)
    assert exc.value.status == status


def test_identity_service_outages_fail_closed():
    value, _ = token()
    for v in (verifier(Http(error=OSError('down'))), verifier(keys=Keys(fail=True))):
        with pytest.raises(ApiError) as exc:v.verify(value)
        assert exc.value.status == 503


def test_router_uses_issuer_then_full_verification():
    class Fake:
        issuer = 'https://securetoken.google.com/synthetic'
        def verify(self, t):return {'issuer': self.issuer, 'subject': 'fb'}
    router = IssuerRouter([Fake(), verifier(check=False)])
    value, claims = token()
    assert router.verify(value)['subject'] == claims['sub']
    assert router.verify(unsigned({'iss': Fake.issuer}))['subject'] == 'fb'
    for bad in ('x', unsigned({'iss': 'https://unknown'}), unsigned(['list']), 'a.b.c'):
        with pytest.raises(ApiError):router.verify(bad)


def test_build_verifier_and_issuer_validation():
    assert build_verifier({'FIREBASE_PROJECT_ID': 'p'}).issuer == 'https://securetoken.google.com/p'
    assert isinstance(build_verifier({'IDENTITY_PROVIDERS': 'firebase,supabase', 'SUPABASE_URL': URL}), IssuerRouter)
    assert build_verifier({'IDENTITY_PROVIDERS': 'supabase', 'SUPABASE_URL': URL}).issuer == ISS
    for bad in ('', 'okta', 'firebase,firebase'):
        with pytest.raises(ValueError):build_verifier({'IDENTITY_PROVIDERS': bad})
    assert supabase_issuer('http://127.0.0.1:54321') == 'http://127.0.0.1:54321/auth/v1'
    for bad in ('http://abc.supabase.co', 'https://u:p@abc.supabase.co', 'https://abc.supabase.co/rest', 'https://abc.supabase.co?x=1', ''):
        with pytest.raises(ValueError):supabase_issuer(bad)


def test_privileged_keys_never_reach_browser_config():
    anon = jwt.encode({'role': 'anon'}, 'x' * 32, algorithm='HS256')
    service = jwt.encode({'role': 'service_role'}, 'x' * 32, algorithm='HS256')
    assert assert_browser_safe_key(anon) == anon and assert_browser_safe_key('sb_publishable_abc') == 'sb_publishable_abc'
    for bad in ('', 'sb_secret_abc', service, 'random'):
        with pytest.raises(ValueError):assert_browser_safe_key(bad)
    with pytest.raises(ValueError):
        create_app({'MODE': 'observer', 'BROWSER_AUTH': 'supabase', 'SUPABASE_URL': URL, 'SUPABASE_ANON_KEY': 'sb_secret_x'}, observer=object())
    with pytest.raises(ValueError):browser_auth_config({'BROWSER_AUTH': 'other'})
    assert browser_auth_config({}) == {'provider': 'firebase'}


def supabase_app():
    return create_app({'MODE': 'observer', 'TESTING': True, 'BROWSER_AUTH': 'supabase', 'SUPABASE_URL': URL,
                       'SUPABASE_ANON_KEY': 'sb_publishable_synthetic', 'SUPABASE_SERVICE_ROLE_KEY': 'sb_secret_never',
                       'SUPABASE_GOOGLE_ENABLED': True}, observer=object(), verifier=verifier())


def test_auth_config_endpoint_and_pages_in_supabase_mode():
    client = supabase_app().test_client()
    response = client.get('/api/auth-config')
    assert response.json == {'provider': 'supabase', 'supabase': {'url': URL, 'anonKey': 'sb_publishable_synthetic', 'google': True}}
    assert b'sb_secret' not in response.data
    page = client.get('/observer.html')
    html = page.get_data(as_text=True)
    assert 'supabase-js@2.45.4' in html and 'js/rudo-supabase-auth.js' in html
    assert 'firebasejs' not in html and 'js/rudo-auth.js' not in html
    assert URL in page.headers['Content-Security-Policy']
    for name in ('staff-login', 'staff-reset'):
        assert client.get(f'/{name}.html').status_code == 200
    assert client.get('/js/rudo-supabase-auth.js').status_code == 200
    csp = page.headers['Content-Security-Policy']
    assert 'firebase' not in csp and 'gstatic' not in csp and 'googleapis' not in csp
    # Old Firebase login links lead to the Supabase pages.
    for old, target in (('login', 'staff-login.html'), ('register', 'staff-login.html#request'),
                        ('forgot-password', 'staff-reset.html'), ('reset-password', 'staff-reset.html')):
        response = client.get(f'/{old}.html')
        assert response.status_code == 302 and response.headers['Location'].endswith(target)


def test_firebase_remains_default_browser_path():
    client = create_app({'MODE': 'observer', 'TESTING': True}, observer=object(), verifier=verifier()).test_client()
    assert client.get('/api/auth-config').json == {'provider': 'firebase'}
    html = client.get('/observer.html').get_data(as_text=True)
    assert 'firebasejs' in html and 'supabase-js' not in html


# Firebase's published scrypt test vector (github.com/firebase/scrypt README), not project values.
VECTOR = {'FIREBASE_SIGNER_KEY': 'jxspr8Ki0RYycVU8zykbdLGjFQ3McFUH0uiiTvC8pVMXAn210wjLNmdZJzxUECKbm0QsEmYUSDzZvpjeJ9WmXA==',
          'FIREBASE_SALT_SEPARATOR': 'Bw==', 'FIREBASE_ROUNDS': '8', 'FIREBASE_MEM_COST': '14'}


def test_firebase_scrypt_matches_published_vector():
    params = HashParams.from_env(VECTOR)
    assert firebase_scrypt('user1password', '42xEC+ixf3L2lw==', params) == \
        'lSrfV15cpx95/sZS2W9c9Kp6i/LVgQNDNC/qzrCnh1SAyZvqmZqAjTdn3aoItz+VHjoZilo78198JAdRuid5lQ=='
    assert 'jxspr' not in repr(params)


def test_fbscrypt_format_normalises_urlsafe_base64():
    params = HashParams.from_env(VECTOR)
    value = fbscrypt_hash('lSrfV15cpx95_sZS2W9c9Kp6i_LVgQNDNC_qzrCnh1SAyZvqmZqAjTdn3aoItz-VHjoZilo78198JAdRuid5lQ', '42xEC-ixf3L2lw', params)
    assert value.startswith('$fbscrypt$v=1,n=14,r=8,p=1,ss=Bw==,sk=jxspr8Ki0RYycVU8')
    assert value.endswith('$42xEC+ixf3L2lw==$lSrfV15cpx95/sZS2W9c9Kp6i/LVgQNDNC/qzrCnh1SAyZvqmZqAjTdn3aoItz+VHjoZilo78198JAdRuid5lQ==')


@pytest.mark.parametrize('change', [{'FIREBASE_ROUNDS': '9'}, {'FIREBASE_MEM_COST': 'x'}, {'FIREBASE_SIGNER_KEY': ''},
                                    {'FIREBASE_SALT_SEPARATOR': '***'}])
def test_hash_params_validation(change):
    with pytest.raises(ValueError):HashParams.from_env({**VECTOR, **change})


def test_output_guard_blocks_secret_material():
    assert_no_secrets({'uid': 'x', 'result': 'would_create'})
    for bad in ({'h': '$fbscrypt$v=1'}, {'k': 'sb_secret_x'}, {'password_hash': 'x'}, {'p': '-----BEGIN ' + 'PRIVATE KEY-----'}):
        with pytest.raises(RuntimeError):assert_no_secrets(bad)


# Firebase ID tokens verified without Admin SDK credentials (RUDO_FIREBASE_CHECK_REVOKED=false).
from cryptography.hazmat.primitives.asymmetric import rsa
from rudo.auth import FirebaseVerifier
RSA_KEY, RSA_OTHER = rsa.generate_private_key(public_exponent=65537, key_size=2048), rsa.generate_private_key(public_exponent=65537, key_size=2048)


def firebase_token(key=RSA_KEY, alg='RS256', kid='fk', **overrides):
    now = int(time.time())
    claims = {'iss': 'https://securetoken.google.com/dawa-ca263', 'aud': 'dawa-ca263', 'sub': 'firebase-uid-1',
              'auth_time': now - 60, 'iat': now - 60, 'exp': now + 3000, 'email': 'staff@example.test', 'email_verified': True, **overrides}
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, key, algorithm=alg, headers={'kid': kid} if kid else None)


def firebase_verifier(fail=False):
    return FirebaseVerifier('dawa-ca263', check_revoked=False, jwks_client=Keys(RSA_KEY, fail))


def test_firebase_signature_only_verification_without_credentials():
    assert firebase_verifier().verify(firebase_token()) == {
        'subject': 'firebase-uid-1', 'issuer': 'https://securetoken.google.com/dawa-ca263', 'provider': 'firebase',
        'email': 'staff@example.test', 'email_verified': True}
    assert firebase_verifier().verify(firebase_token(email_verified='true'))['email_verified'] is False
    now = int(time.time())
    for bad in (firebase_token(key=RSA_OTHER), firebase_token(kid=None), firebase_token(aud='other-project'),
                firebase_token(iss='https://securetoken.google.com/other'), firebase_token(exp=now - 3600),
                firebase_token(sub=''), firebase_token(sub='x' * 129), firebase_token(auth_time=now + 3600),
                firebase_token(auth_time=None), firebase_token(iat=None), 'garbage',
                jwt.encode({'sub': 'x'}, 'k' * 32, algorithm='HS256', headers={'kid': 'fk'})):
        with pytest.raises(ApiError) as exc:firebase_verifier().verify(bad)
        assert exc.value.status == 401
    with pytest.raises(ApiError) as exc:firebase_verifier(fail=True).verify(firebase_token())
    assert exc.value.status == 503
