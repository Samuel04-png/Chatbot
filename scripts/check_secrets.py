"""Pre-commit / pre-`git init` secret scan. Prints file:line and rule only, never the matched value.
Exit 1 on any finding. Run: .venv/bin/python scripts/check_secrets.py [path]"""
import base64
import fnmatch
import json
import re
import sys
from pathlib import Path

SKIP_DIRS = {'.venv', 'node_modules', '.git', '__pycache__', '.pytest_cache', '.local', 'img'}
SKIP_SUFFIXES = {'.png', '.jpg', '.jpeg', '.avif', '.ico', '.gif', '.woff', '.woff2', '.ttf', '.eot', '.pyc'}
CREDENTIAL_NAMES = re.compile(r'(firebase-adminsdk|service[-_]account|^firebase-service\.json$|^supabase-service\.json$|^\.env$|\.pem$|\.p12$|\.key$)', re.I)
RULES = [
    ('private_key_block', re.compile(r'-----BEGIN (?:RSA |EC |ENCRYPTED )?PRIVATE KEY-----')),
    ('gcp_service_account', re.compile(r'"type"\s*:\s*"service_account"')),
    ('gcp_private_key_id', re.compile(r'"private_key_id"\s*:\s*"[0-9a-f]{40}"')),
    ('supabase_secret_key', re.compile(r'sb_secret_[A-Za-z0-9_-]{20,}')),
    ('firebase_signer_key', re.compile(r'(?i)(signer_key|FIREBASE_SIGNER_KEY)\s*[:=]\s*["\']?[A-Za-z0-9+/]{60,}={0,2}')),
    ('database_url_with_password', re.compile(r'postgres(?:ql)?://[^:\s/@]+:[^@\s]{6,}@(?!127\.0\.0\.1|localhost)')),
    ('meta_access_token', re.compile(r'EAA[A-Za-z0-9]{60,}')),
]
JWT = re.compile(r'eyJ[A-Za-z0-9_-]{10,}\.(eyJ[A-Za-z0-9_-]{10,})\.[A-Za-z0-9_-]{20,}')


def jwt_role(segment):
    try:
        return json.loads(base64.urlsafe_b64decode(segment + '=' * (-len(segment) % 4))).get('role')
    except Exception:
        return None


def ignored_patterns(root):
    """File-name patterns from .gitignore. Matching files never get committed, so local credential
    files such as .env and firebase-service.json are expected and skipped; they are counted, not read."""
    path = Path(root) / '.gitignore'
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith(('#', '!'))]


def scan(root, skipped=None):
    findings, patterns = [], ignored_patterns(root)
    for path in sorted(Path(root).rglob('*')):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts) or not path.is_file():
            continue
        ignored_dirs = [p.rstrip('/') for p in patterns if p.endswith('/')]
        if any(fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(str(rel), pattern) for pattern in patterns if not pattern.endswith('/')) \
                or any(str(rel).startswith(d + '/') or any(fnmatch.fnmatch(part, d) for part in rel.parts[:-1]) for d in ignored_dirs):
            if skipped is not None:
                skipped.append(str(rel))
            continue
        if CREDENTIAL_NAMES.search(path.name):
            findings.append((str(rel), 0, 'credential_file_present'))
            continue
        if path.suffix.lower() in SKIP_SUFFIXES or path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(errors='strict')
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for name, pattern in RULES:
                if pattern.search(line):
                    findings.append((str(rel), number, name))
            for match in JWT.finditer(line):
                if jwt_role(match.group(1)) in ('service_role', 'supabase_admin'):
                    findings.append((str(rel), number, 'supabase_service_role_jwt'))
    return findings


def main(argv=None):
    root = Path((argv or sys.argv[1:] or [Path(__file__).resolve().parents[1]])[0])
    skipped = []
    findings = scan(root, skipped)
    for rel, line, rule in findings:
        print(f'{rel}:{line}: {rule}')
    credentials = [f for f in skipped if CREDENTIAL_NAMES.search(Path(f).name)]
    if credentials:
        print(f'{len(credentials)} gitignored local credential file(s) present and not scanned (never commit them).')
    print(f'{len(findings)} potential secret(s) found.' if findings else 'No secrets found.')
    return 1 if findings else 0


if __name__ == '__main__':
    sys.exit(main())
