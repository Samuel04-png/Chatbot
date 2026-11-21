from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
from uuid import uuid4
import json
import psycopg
import pytest
from conftest import ISSUER,TEST_DSN
from rudo.db import Database
from rudo.errors import ApiError
from rudo.importer import plan,apply_local,reconcile_local
from scripts.apply_local_migrations import apply

IDENTITY={'issuer':ISSUER,'subject':'operator'}


def test_migrations_repeat_and_no_public_tables(database):
    apply(TEST_DSN)
    with psycopg.connect(TEST_DSN) as c:
        assert c.execute('SELECT count(*) FROM rudo_local_migrations.ledger').fetchone()[0]==1
        assert c.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()[0]==0
        assert c.execute("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='rudo' AND c.relkind='r' AND NOT c.relrowsecurity").fetchone()[0]==0


def test_direct_rls_and_grants(database):
    with database.transaction(IDENTITY) as c:
        assert c.execute('SELECT count(*) AS n FROM rudo.conversations').fetchone()['n']==1
        assert c.execute("SELECT count(*) AS n FROM rudo.messages").fetchone()['n']==0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("UPDATE rudo.staff_memberships SET role='admin'")
    with database.transaction({'issuer':ISSUER,'subject':'unknown'}) as c:
        assert c.execute('SELECT count(*) AS n FROM rudo.conversations').fetchone()['n']==0
    with database.transaction({'issuer':'wrong-issuer','subject':'operator'}) as c:
        assert c.execute('SELECT count(*) AS n FROM rudo.conversations').fetchone()['n']==0
    with database.transaction({'issuer':ISSUER,'subject':'analyst'}) as c:
        assert c.execute('SELECT count(*) AS n FROM rudo.conversations').fetchone()['n']==0
        assert c.execute('SELECT * FROM rudo.analytics()').fetchone()['conversations']==1
    with psycopg.connect(TEST_DSN) as c:
        assert not c.execute("SELECT EXISTS(SELECT 1 FROM pg_namespace n,LATERAL aclexplode(n.nspacl) a WHERE n.nspname='rudo' AND a.grantee=0 AND a.privilege_type='USAGE')").fetchone()[0]
        assert not c.execute("SELECT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace,LATERAL aclexplode(p.proacl) a WHERE n.nspname='rudo' AND a.grantee=0 AND a.privilege_type='EXECUTE')").fetchone()[0]


def test_remote_connection_guard():
    with pytest.raises(ApiError) as exc:Database().check_target('postgresql://db.cktfbpnxpfbyroqzuibc.supabase.co/postgres')
    assert exc.value.code=='remote_database_disabled'


def test_order_concurrent_update(database):
    def update(status):
        try:return database.change_status(IDENTITY,'orders',database.test_ids['order'],status,1)['status']
        except ApiError as e:return e.code
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(update,['paid','cancelled']))
    assert result.count('version_conflict')==1


def test_state_expiry_and_atomic_acquire(database):
    with psycopg.connect(TEST_DSN) as c:
        c.execute("INSERT INTO rudo.expiring_state VALUES('expired','{}',now()-interval '1 second')")
        c.execute("INSERT INTO rudo.expiring_state VALUES('permanent','{}',NULL)")
    assert database.state_get('expired') is None
    assert database.state_get('permanent')=={}
    assert not database.state_acquire('permanent',{},60)
    def acquire(_):return database.state_acquire('expired',{'synthetic':True},60)
    with ThreadPoolExecutor(max_workers=4) as pool:assert list(pool.map(acquire,range(4))).count(True)==1


def export_fixture():
    snapshot=datetime(2026,1,1,tzinfo=timezone.utc)
    return {'captured_at':snapshot.isoformat(),'source_alias':'synthetic', 'records':[
        {'key':'conversation:260000000011','type':'string','pttl_ms':-1,'value':json.dumps([
            {'role':'user','message':'same','timestamp':'2025-12-31T23:59:59Z'},
            {'role':'user','message':'same','timestamp':'2025-12-31T23:59:59Z'},
            {'text':'No source timestamp','role':'custom'}])},
        {'key':'orders:synthetic','type':'string','pttl_ms':-1,'value':json.dumps(json.dumps({'status':'paid','price':'ZMW 12.50','createdAt':'2025-12-31T00:00:00Z'}))},
        {'key':'referrals:synthetic','type':'string','pttl_ms':-1,'value':{'source':'Mandebvu Clinic Poster 1'}},
        {'key':'orders:expired','type':'string','pttl_ms':100,'value':{}},
        {'key':'orders:ttl','type':'string','pttl_ms':100000,'value':{'status':'pending'}},
        {'key':'cache:excluded','type':'string','pttl_ms':-1,'value':{}},
        {'key':'orders:bad','type':'hash','pttl_ms':-1,'value':{}},
    ]}


def test_import_dryrun_counts_and_idempotency(database):
    doc=export_fixture();now=datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(seconds=1)
    records,counts=plan(doc,now)
    assert counts=={'discovered':7,'accepted':4,'quarantined':1,'expired':1,'excluded':1}
    assert len(records)==4
    # Expiring records are retained in expiry-aware state, not permanent business tables.
    assert records[-1]['expiry']==datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(seconds=100)
    first=apply_local(TEST_DSN,records,'clinic-a','synthetic-account')
    second=apply_local(TEST_DSN,records,'clinic-a','synthetic-account')
    assert first=={'inserted':4,'skipped':0} and second=={'inserted':0,'skipped':4}
    assert reconcile_local(TEST_DSN,records)=={'expected':4,'matched':4,'mismatched':0}
    with psycopg.connect(TEST_DSN) as c:
        rows=c.execute('SELECT message,occurred_at,role FROM rudo.messages ORDER BY source_ordinal').fetchall()
        assert len(rows)==3 and rows[0][0]==rows[1][0]=='same' and rows[2][1] is None
        assert rows[2][2]=='custom'
        assert c.execute("SELECT created_at FROM rudo.conversations WHERE phone='260000000011'").fetchone()[0] is None
    assert database.state_get(str(records[-1]['id'])) is None  # elapsed absolute TTL never renewed
    doc['records'][0]['value']='[]'
    changed,_=plan(doc,now)
    with pytest.raises(ValueError,match='source_conflict'):apply_local(TEST_DSN,changed,'clinic-a','synthetic-account')


def test_missing_timezone_quarantined():
    doc=export_fixture();doc['records']=[{'key':'orders:test','type':'string','pttl_ms':-1,'value':{'timestamp':'2026-01-01'}}]
    records,counts=plan(doc,datetime(2026,1,1,tzinfo=timezone.utc))
    assert records==[] and counts['quarantined']==1


def test_export_duplicate_conflict_is_not_silently_ignored():
    doc=export_fixture();doc['records']=[doc['records'][0],{**doc['records'][0],'value':'[]'}]
    with pytest.raises(ValueError,match='inconsistent_snapshot'):
        plan(doc,datetime(2026,1,1,tzinfo=timezone.utc))


def test_remote_tls_must_verify_hostname():
    with pytest.raises(ApiError) as exc:
        Database(allow_remote=True).check_target('postgresql://example.test/postgres?sslmode=prefer')
    assert exc.value.code=='verified_database_tls_required'


def test_hostaddr_cannot_bypass_remote_guard():
    with pytest.raises(ApiError) as exc:
        Database().check_target('postgresql://127.0.0.1/rudo_test?hostaddr=192.0.2.1')
    assert exc.value.code=='remote_database_disabled'
