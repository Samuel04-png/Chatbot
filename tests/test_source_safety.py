from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]


def test_browser_sources_have_no_privileged_provider_paths_or_tokens():
    paths=list(ROOT.glob('*.html'))+[ROOT/'js/rudo-auth.js',ROOT/'js/rudo-api.js',ROOT/'js/admin-shell.js']
    for path in paths:
        source=path.read_text()
        assert not re.search(r'(?:EAA[A-Za-z0-9]{30,}|Afqy[A-Za-z0-9_-]{25,}|sb_secret_[A-Za-z0-9_-]+|eyJ[A-Za-z0-9_.-]{40,})',source),path.name
        assert not re.search(r'upstash\.io|graph\.facebook\.com',source),path.name


def test_clinical_source_hash_matches_original_snapshot():
    import hashlib,json
    inventory=json.loads((ROOT/'docs/SOURCE_INVENTORY.json').read_text())
    baseline=next(row for row in inventory['files'] if row['path']=='js/risk-triage.js')
    assert hashlib.sha256((ROOT/'js/risk-triage.js').read_bytes()).hexdigest()==baseline['sha256']
