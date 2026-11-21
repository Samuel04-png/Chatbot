"""Identity verification. Staff authority always comes from the database, never from token claims."""
import base64
import json
import threading
from urllib.parse import urlsplit
from uuid import UUID

from .errors import ApiError

_lock = threading.Lock()
FIREBASE_ISSUER_PREFIX = 'https://securetoken.google.com/'


FIREBASE_JWKS_URL = 'https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com'


class FirebaseVerifier:
    def __init__(self, project_id, check_revoked=True, jwks_client=None, leeway=30):
        self.project_id = project_id
        # Revocation/disabled checks call the Firebase Admin API and need a (non-compromised) service
        # account. Without one, set RUDO_FIREBASE_CHECK_REVOKED=false: the token is then verified directly
        # against Google's public signing keys (signature, audience, issuer, expiry, auth time), with no
        # credentials needed; staff suspension in Supabase still takes effect on the next request.
        self.check_revoked = check_revoked
        self.app = None
        self._jwks = jwks_client
        self.leeway = leeway

    @property
    def issuer(self):
        return FIREBASE_ISSUER_PREFIX + self.project_id

    def _verify_signature_only(self, token):
        """Firebase's documented third-party-library verification (no Admin SDK credentials)."""
        import time
        import jwt
        try:
            header = jwt.get_unverified_header(token)
            if header.get('alg') != 'RS256' or not header.get('kid'):
                raise ApiError(401, 'invalid_identity')
            if self._jwks is None:
                self._jwks = jwt.PyJWKClient(FIREBASE_JWKS_URL, cache_keys=True, lifespan=3600, timeout=10)
            try:
                key = self._jwks.get_signing_key_from_jwt(token).key
            except jwt.PyJWKClientConnectionError:
                raise ApiError(503, 'identity_unavailable') from None
            claims = jwt.decode(token, key, algorithms=['RS256'], audience=self.project_id, issuer=self.issuer,
                                leeway=self.leeway, options={'require': ['exp', 'iat', 'sub', 'aud', 'iss', 'auth_time']})
        except ApiError:
            raise
        except (jwt.PyJWTError, ValueError, TypeError):
            raise ApiError(401, 'invalid_identity') from None
        subject = claims.get('sub')
        if not isinstance(subject, str) or not 0 < len(subject) <= 128 or claims['auth_time'] > time.time() + self.leeway:
            raise ApiError(401, 'invalid_identity')
        return {'subject': subject, 'issuer': self.issuer, 'provider': 'firebase',
                'email': claims.get('email'), 'email_verified': claims.get('email_verified') is True}

    def verify(self, token):
        if not self.project_id:
            raise ApiError(503, 'identity_unavailable')
        if not self.check_revoked:
            return self._verify_signature_only(token)
        from firebase_admin import auth, initialize_app, get_app
        with _lock:
            if self.app is None:
                # ADC is resolved server-side only; no hardcoded credential fallback.
                try:
                    self.app = get_app('rudo-' + self.project_id)
                except ValueError:
                    self.app = initialize_app(options={'projectId': self.project_id, 'httpTimeout': 10},
                                              name='rudo-' + self.project_id)
        try:
            claims = auth.verify_id_token(token, app=self.app, check_revoked=self.check_revoked)
        except (auth.ExpiredIdTokenError, auth.RevokedIdTokenError,
                auth.InvalidIdTokenError, auth.UserDisabledError, auth.UserNotFoundError, ValueError):
            raise ApiError(401, 'invalid_identity') from None
        except Exception:
            raise ApiError(503, 'identity_unavailable') from None
        if (claims.get('aud') != self.project_id or claims.get('iss') != self.issuer
                or not claims.get('sub') or claims.get('sub') != claims.get('uid')):
            raise ApiError(401, 'invalid_identity')
        return {'subject': claims['sub'], 'issuer': self.issuer, 'provider': 'firebase',
                'email': claims.get('email'), 'email_verified': claims.get('email_verified') is True}


def supabase_issuer(url):
    """Canonical Supabase Auth issuer. HTTPS only, except an explicit loopback development stack."""
    parts = urlsplit(url or '')
    loopback = parts.hostname in ('127.0.0.1', 'localhost')
    if (parts.scheme != 'https' and not (parts.scheme == 'http' and loopback)) or not parts.hostname \
            or parts.query or parts.fragment or parts.username or parts.password or parts.path not in ('', '/'):
        raise ValueError('SUPABASE_URL must be an https project origin')
    return f'{parts.scheme}://{parts.netloc}/auth/v1'


def _jwt_payload(token):
    try:
        segment = token.split('.')[1]
        return json.loads(base64.urlsafe_b64decode(segment + '=' * (-len(segment) % 4)))
    except (IndexError, ValueError, TypeError, UnicodeError):
        return None


def assert_browser_safe_key(key):
    """Refuse to hand a privileged Supabase key to the browser config endpoint."""
    if not key:
        raise ValueError('SUPABASE_ANON_KEY is required for browser sign-in')
    if key.startswith('sb_secret_'):
        raise ValueError('A Supabase secret key must never be served to browsers')
    if key.startswith('sb_publishable_'):
        return key
    payload = _jwt_payload(key)
    if not isinstance(payload, dict) or payload.get('role') != 'anon':
        raise ValueError('SUPABASE_ANON_KEY must be a publishable or anon-role key')
    return key


class SupabaseVerifier:
    """Verifies Supabase Auth access tokens against the project's asymmetric JWKS, then (by default)
    confirms with the Auth server that the session still exists and the user is not banned/deleted.
    HS256 shared-secret tokens are refused: the server never holds the project JWT secret."""
    ALGORITHMS = ('ES256', 'RS256')

    def __init__(self, url, anon_key, session_check=True, jwks_client=None, http=None, leeway=30):
        self.issuer = supabase_issuer(url)
        self.anon_key = anon_key
        self.session_check = session_check
        self.leeway = leeway
        self._jwks = jwks_client
        self._http = http

    def _keys(self):
        if self._jwks is None:
            import jwt
            self._jwks = jwt.PyJWKClient(self.issuer + '/.well-known/jwks.json', cache_keys=True,
                                         lifespan=600, timeout=5)
        return self._jwks

    def verify(self, token):
        import jwt
        try:
            header = jwt.get_unverified_header(token)
            if header.get('alg') not in self.ALGORITHMS or not header.get('kid'):
                raise ApiError(401, 'invalid_identity')
            try:
                key = self._keys().get_signing_key_from_jwt(token).key
            except jwt.PyJWKClientConnectionError:
                raise ApiError(503, 'identity_unavailable') from None
            claims = jwt.decode(token, key, algorithms=[header['alg']], audience='authenticated',
                                issuer=self.issuer, leeway=self.leeway,
                                options={'require': ['exp', 'iat', 'sub', 'iss', 'aud']})
        except ApiError:
            raise
        except (jwt.PyJWTError, ValueError, TypeError):
            raise ApiError(401, 'invalid_identity') from None
        subject = claims.get('sub')
        try:
            if str(UUID(subject)) != subject:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ApiError(401, 'invalid_identity') from None
        if claims.get('role') != 'authenticated' or claims.get('is_anonymous') is True:
            raise ApiError(401, 'invalid_identity')
        identity = {'subject': subject, 'issuer': self.issuer, 'provider': 'supabase',
                    'email': claims.get('email'), 'email_verified': False}
        if self.session_check:
            user = self._confirm_session(token, subject)
            identity['email'] = user.get('email') or identity['email']
            identity['email_verified'] = bool(user.get('email_confirmed_at'))
        return identity

    def _confirm_session(self, token, subject):
        http = self._http
        if http is None:
            import requests
            http = requests
        try:
            response = http.get(self.issuer + '/user', timeout=5,
                                headers={'apikey': self.anon_key, 'Authorization': 'Bearer ' + token})
        except Exception:
            raise ApiError(503, 'identity_unavailable') from None
        if response.status_code in (401, 403, 404):
            raise ApiError(401, 'invalid_identity')
        if response.status_code != 200:
            raise ApiError(503, 'identity_unavailable')
        try:
            user = response.json()
        except ValueError:
            raise ApiError(503, 'identity_unavailable') from None
        if not isinstance(user, dict) or user.get('id') != subject or user.get('deleted_at'):
            raise ApiError(401, 'invalid_identity')
        if user.get('banned_until') and user['banned_until'] not in ('none', ''):
            raise ApiError(401, 'invalid_identity')
        return user


class IssuerRouter:
    """Selects a verifier by the token's (unverified) issuer; the chosen verifier checks everything."""
    def __init__(self, verifiers):
        self.verifiers = {v.issuer: v for v in verifiers}

    def verify(self, token):
        payload = _jwt_payload(token) if isinstance(token, str) and token.count('.') == 2 else None
        verifier = self.verifiers.get(payload.get('iss')) if isinstance(payload, dict) else None
        if verifier is None:
            raise ApiError(401, 'invalid_identity')
        return verifier.verify(token)


def build_verifier(config):
    """RUDO_IDENTITY_PROVIDERS: 'firebase' (default), 'supabase' or 'firebase,supabase' for parallel run."""
    names = [n.strip() for n in config.get('IDENTITY_PROVIDERS', 'firebase').split(',') if n.strip()]
    if not names or len(set(names)) != len(names) or not set(names) <= {'firebase', 'supabase'}:
        raise ValueError('Unsupported RUDO_IDENTITY_PROVIDERS value')
    verifiers = []
    if 'firebase' in names:
        verifiers.append(FirebaseVerifier(config.get('FIREBASE_PROJECT_ID', ''),
                                          check_revoked=config.get('FIREBASE_CHECK_REVOKED', True)))
    if 'supabase' in names:
        verifiers.append(SupabaseVerifier(config.get('SUPABASE_URL', ''), config.get('SUPABASE_ANON_KEY', ''),
                                          session_check=config.get('SUPABASE_SESSION_CHECK', True)))
    return verifiers[0] if len(verifiers) == 1 else IssuerRouter(verifiers)


def browser_auth_config(config):
    """Only browser-safe values. Never includes service-role/secret keys or database URLs."""
    provider = config.get('BROWSER_AUTH', 'firebase')
    if provider not in ('firebase', 'supabase'):
        raise ValueError('Unsupported RUDO_BROWSER_AUTH value')
    result = {'provider': provider}
    if provider == 'supabase':
        supabase_issuer(config.get('SUPABASE_URL', ''))
        result['supabase'] = {'url': config['SUPABASE_URL'].rstrip('/'),
                              'anonKey': assert_browser_safe_key(config.get('SUPABASE_ANON_KEY', '')),
                              'google': bool(config.get('SUPABASE_GOOGLE_ENABLED'))}
    return result
