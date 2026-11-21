"""Owner CLI: first-admin bootstrap, facilities and phone->facility mappings (dry run by default)."""
import json
from pathlib import Path

import psycopg
import pytest

from conftest import TEST_DSN
from rudo.synthetic import PHONES, SOURCE, bootstrap, clear_source
from scripts import staff_admin

ROOT = Path(__file__).resolve().parents[1]
ENV = {'RUDO_CONTROL_ADMIN_DATABASE_URL': TEST_DSN, 'RUDO_OBSERVER_SOURCE_ID': SOURCE, 'FIREBASE_PROJECT_ID': 'synthetic-test'}


@pytest.fixture
def fresh():
    """Migration applied, synthetic bot rows present, but no staff/facilities/mappings yet."""
    bootstrap(TEST_DSN)
    with psycopg.connect(TEST_DSN) as conn:
        for table in ('staff_scopes', 'staff_identities', 'staff', 'source_mappings', 'facilities'):
            conn.execute(f'DELETE FROM observer_control.{table}')
    yield
    clear_source(TEST_DSN)


def run(*argv):return staff_admin.main(list(argv), env=ENV)


def test_bootstrap_first_admin_only_once(fresh):
    run('facility-add', '--account', 'rudo-whatsapp', '--facility', 'chelstone-clinic', '--name', 'Chelstone Clinic', '--actor', 'owner')
    with pytest.raises(SystemExit):run('bootstrap-admin', '--email', 'tari@example.test', '--actor', 'owner')
    sid = run('bootstrap-admin', '--email', 'Tari@example.test', '--name', 'Tari', '--firebase-uid', 'firebase-uid-1',
              '--scope', 'rudo-whatsapp:chelstone-clinic', '--actor', 'owner')
    with psycopg.connect(TEST_DSN) as conn:
        assert conn.execute('SELECT email,role,status FROM observer_control.staff WHERE id=%s', (sid,)).fetchone() == ('tari@example.test', 'admin', 'active')
        assert conn.execute('SELECT provider,link_method FROM observer_control.staff_identities WHERE staff_id=%s', (sid,)).fetchone() == ('firebase', 'bootstrap')
    with pytest.raises(SystemExit, match='already exists'):
        run('bootstrap-admin', '--email', 'b@example.test', '--firebase-uid', 'x', '--scope', 'rudo-whatsapp:chelstone-clinic', '--actor', 'owner')
    with pytest.raises(SystemExit):run('facility-add', '--actor', 'owner')


def test_referral_rule_mapping_is_dry_run_first_and_skips_ambiguity(fresh, tmp_path):
    for account, facility in (('account-one', 'facility-a'), ('account-one', 'facility-b'), ('holding', 'unassigned')):
        run('facility-add', '--account', account, '--facility', facility, '--name', facility, '--actor', 'owner')
    with psycopg.connect(TEST_DSN) as conn:  # Second referral for 'a' from another facility makes it ambiguous.
        conn.execute("INSERT INTO public.referrals(phone,source) VALUES(%s,'Synthetic b Poster 2')", (PHONES['a'],))
    rules = tmp_path / 'rules.json'
    rules.write_text(json.dumps([{'pattern': r'synthetic (a|c)\b', 'account': 'account-one', 'facility': 'facility-a'},
                                 {'pattern': r'synthetic b\b', 'account': 'account-one', 'facility': 'facility-b'}]))
    dry = run('map-referrals', '--rules', str(rules), '--actor', 'owner')
    assert dry['mode'] == 'dry-run' and dry['per_facility'] == {'account-one:facility-a': 1, 'account-one:facility-b': 1}
    assert dry['ambiguous_phones_skipped'] == 1
    with psycopg.connect(TEST_DSN) as conn:
        assert conn.execute('SELECT count(*) FROM observer_control.source_mappings').fetchone()[0] == 0
    done = run('map-referrals', '--rules', str(rules), '--actor', 'owner', '--execute')
    assert done['phones'] == 2
    remaining = run('map-remaining', '--account', 'holding', '--facility', 'unassigned', '--actor', 'owner', '--execute')
    with psycopg.connect(TEST_DSN) as conn:
        total = conn.execute('SELECT count(*) FROM (SELECT phone FROM public.users UNION SELECT phone FROM public.messages) p').fetchone()[0]
        assert conn.execute('SELECT count(DISTINCT phone) FROM observer_control.source_mappings').fetchone()[0] == total
        assert remaining['phones'] == total - 2
        assert [r[0] for r in conn.execute('SELECT action FROM observer_control.staff_admin_events ORDER BY id')][-2:] == ['map_phones', 'map_phones']
    with pytest.raises(SystemExit, match='Unknown facilities'):
        run('map-remaining', '--account', 'nope', '--facility', 'nope', '--actor', 'owner')


def test_csv_mapping_pending_listing_and_emergency_suspend(fresh, tmp_path):
    run('facility-add', '--account', 'rudo-whatsapp', '--facility', 'ngombe-clinic', '--name', "N'gombe Clinic", '--actor', 'owner')
    mapping = tmp_path / 'm.csv'
    mapping.write_text(f"phone,account,facility\n{PHONES['c']},rudo-whatsapp,ngombe-clinic\n")
    assert run('map-csv', '--file', str(mapping), '--actor', 'owner', '--execute')['phones'] == 1
    sid = run('bootstrap-admin', '--email', 'tari@example.test', '--firebase-uid', 'u1', '--scope', 'rudo-whatsapp:ngombe-clinic', '--actor', 'owner')
    with psycopg.connect(TEST_DSN) as conn:
        conn.execute("SELECT observer_control.record_identity_request('iss','sub','firebase','New@example.test',true)")
    assert run('pending')[0]['email'] == 'new@example.test'
    run('suspend', '--email', 'TARI@example.test', '--actor', 'owner')
    with psycopg.connect(TEST_DSN) as conn:
        assert conn.execute('SELECT status FROM observer_control.staff WHERE id=%s', (sid,)).fetchone()[0] == 'suspended'
    with pytest.raises(SystemExit):run('suspend', '--email', 'nobody@example.test', '--actor', 'owner')
    with pytest.raises(SystemExit):staff_admin.main(['pending'], env={**ENV, 'RUDO_OBSERVER_SOURCE_ID': ''})


def test_facility_rules_file_is_valid():
    import re
    rules = json.loads((ROOT / 'deploy/facility_rules.json').read_text())
    assert {r['facility'] for r in rules} == {'mandebvu-pharmacy', 'mandebvu-clinic', 'ngombe-clinic', 'chelstone-clinic', 'avondale-clinic'}
    first = lambda text: next(r['facility'] for r in rules if re.search(r['pattern'], text, re.I))
    assert first('Mandebvu Pharmacy flyer') == 'mandebvu-pharmacy' and first('Mandebvu Clinic Poster 1') == 'mandebvu-clinic'
    assert {first(t) for t in ("N'gombe Clinic flyer", 'ngombe flyer', "the Ng'ombe flyer", 'ngombef flyer')} == {'ngombe-clinic'}
    assert first('chelston Clinic flyer') == 'chelstone-clinic' and first('Avondale Clinic flyer') == 'avondale-clinic'
    assert not any(re.search(r['pattern'], 'Cancer Awareness', re.I) for r in rules)
