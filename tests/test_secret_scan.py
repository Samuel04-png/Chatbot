"""The secret scanner catches credential material (built at runtime so this file stays clean)."""
import base64
import json
from pathlib import Path

from scripts.check_secrets import main, scan

ROOT = Path(__file__).resolve().parents[1]


def jwt_with_role(role):
    seg = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip('=')
    return f"{seg({'alg': 'HS256', 'typ': 'JWT'})}.{seg({'role': role, 'iss': 'supabase'})}.{'s' * 43}"


def test_scanner_detects_each_secret_kind(tmp_path):
    (tmp_path / 'firebase-adminsdk-x.json').write_text('{}')
    (tmp_path / '.env').write_text('X=1')
    (tmp_path / 'a.py').write_text('\n'.join([
        'k = """-----BEGIN ' + 'PRIVATE KEY-----"""',
        '{"type": "service' + '_account"}',
        'key = "sb_secret' + '_' + 'A' * 30 + '"',
        'FIREBASE_SIGNER_KEY=' + 'Q' * 86 + '==',
        'url = "postgresql://postgres:' + 'hunter22pw' + '@db.abc.supabase.co:5432/postgres"',
        'service = "' + jwt_with_role('service_role') + '"',
        'anon = "' + jwt_with_role('anon') + '"',
        'local = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"']))
    found = {(name, line) for name, line in ((r, l) for _, l, r in scan(tmp_path))}
    assert found == {('credential_file_present', 0), ('private_key_block', 1), ('gcp_service_account', 2),
                     ('supabase_secret_key', 3), ('firebase_signer_key', 4), ('database_url_with_password', 5),
                     ('supabase_service_role_jwt', 6)}


def test_gitignored_credential_files_are_skipped_but_unignored_ones_fail(tmp_path):
    (tmp_path / '.gitignore').write_text('.env\nfirebase-service.json\n.local/\n')
    (tmp_path / '.env').write_text('FIREBASE_SIGNER_KEY=' + 'Q' * 86 + '==')
    (tmp_path / 'firebase-service.json').write_text('{"type": "service' + '_account"}')
    assert scan(tmp_path) == []
    (tmp_path / '.gitignore').write_text('.env\nfirebase-service.json\n.local/\nbackups/\n')
    (tmp_path / 'backups').mkdir()
    (tmp_path / 'backups' / 'dashboard.env').write_text('X=postgresql://u:' + 'longpassword1' + '@db.example.supabase.co/x')
    assert scan(tmp_path) == []  # Ignored folder: never committed.
    (tmp_path / 'copy-of-key.json').write_text('{"type": "service' + '_account"}')
    assert scan(tmp_path) == [('copy-of-key.json', 1, 'gcp_service_account')]


def test_repository_contains_no_secrets(capsys):
    assert main([str(ROOT)]) == 0, capsys.readouterr().out


def test_gitignore_covers_credentials_and_exports():
    ignored = (ROOT / '.gitignore').read_text().splitlines()
    for pattern in ('.env', 'firebase-service.json', 'supabase-service.json', '*firebase-adminsdk*.json',
                    '*service-account*.json', 'firebase-users*.json', 'auth-export*.json', '.local/', 'supabase/.temp/'):
        assert pattern in ignored, pattern
