from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime,timezone
import json
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest

from app import create_app
from conftest import TEST_DSN
from rudo.synthetic import bootstrap,clear_source,snapshot,SyntheticVerifier,SyntheticBot,ISSUER,SOURCE,PHONES,adapter
from rudo.observer import reference,Observer,AccessAudit


def auth(subject='operator'):return {'Authorization':'Bearer synthetic:'+subject}

def identity(subject='operator'):return {'issuer':ISSUER,'subject':subject}

def ref(name):return reference(SOURCE,PHONES[name])


@pytest.fixture
def observer():
    value=bootstrap(TEST_DSN)
    with psycopg.connect(TEST_DSN) as conn:conn.execute('DROP SCHEMA IF EXISTS rudo CASCADE')
    yield value
    clear_source(TEST_DSN)


@pytest.fixture
def observer_app(observer):
    return create_app({'MODE':'observer','TESTING':True},observer=observer,verifier=SyntheticVerifier())


@pytest.fixture
def client(observer_app):return observer_app.test_client()


@pytest.mark.parametrize('route',['/api/me','/api/conversations','/api/orders','/api/referrals','/api/analytics'])
def test_observer_auth_required(client,route):assert client.get(route).status_code==401


@pytest.mark.parametrize('subject,status',[('unknown',403),('disabled',403),('expired',401),('revoked',401),('invalid',401)])
def test_observer_identity_denials(client,subject,status):assert client.get('/api/conversations',headers=auth(subject)).status_code==status


def test_scope_mappings_no_ambiguous_or_unmapped_records(client,observer):
    rows=client.get('/api/conversations',headers=auth()).json['items']
    assert {x['phone'] for x in rows}=={PHONES['a'],PHONES['empty'],PHONES['history_only']}
    for name in ('b','c','unmapped','ambiguous','inconsistent'):
        assert client.get('/api/conversations/'+ref(name),headers=auth()).status_code==404
    assert {x['phone'] for x in client.get('/api/conversations',headers=auth('other')).json['items']}=={PHONES['b']}
    assert {x['phone'] for x in client.get('/api/conversations',headers=auth('second-account')).json['items']}=={PHONES['c']}
    assert len(client.get('/api/conversations',headers=auth('admin')).json['items'])==5
    assert client.get('/api/conversations?account=account-two',headers=auth()).status_code==403
    assert client.get('/api/conversations?account=account-two&facility=facility-b',headers=auth('admin')).status_code==403


def test_membership_revocation_and_mapping_ambiguity_take_effect(client):
    assert client.get('/api/conversations/'+ref('a'),headers=auth()).status_code==200
    with psycopg.connect(TEST_DSN) as conn:
        conn.execute("INSERT INTO observer_control.source_mappings VALUES(%s,%s,'account-two','facility-a',true)",(SOURCE,PHONES['a']))
    assert client.get('/api/conversations/'+ref('a'),headers=auth()).status_code==404
    with psycopg.connect(TEST_DSN) as conn:
        conn.execute("UPDATE observer_control.staff SET status='suspended' WHERE email='operator@example.test'")
    assert client.get('/api/me',headers=auth()).status_code==403


def test_summaries_minimal_projection_and_search(client):
    data=client.get('/api/conversations',headers=auth()).json
    row=next(x for x in data['items'] if x['phone']==PHONES['a'])
    assert row['last_message_id']=='9007199254740995'
    assert 'messages' not in row and 'state' not in row and 'message_en' not in row
    assert row['delivery_status']=='unknown'
    assert len(client.get('/api/conversations?q=SYN-a',headers=auth()).json['items'])==1
    assert len(client.get('/api/conversations?filter=without_messages',headers=auth()).json['items'])==1
    assert len(client.get('/api/conversations?filter=with_messages',headers=auth()).json['items'])==2
    # Missing user row is not invented: identity/language/times remain NULL.
    orphan=next(x for x in data['items'] if x['phone']==PHONES['history_only'])
    assert orphan['user_id'] is None and orphan['language'] is None and orphan['user_created_at'] is None


def test_history_keyset_bigint_ids_and_concurrent_inserts(client):
    path='/api/conversations/'+ref('a')
    first=client.get(path+'?limit=2',headers=auth()).json
    assert [m['id'] for m in first['messages']]==['9007199254740994','9007199254740995']
    with psycopg.connect(TEST_DSN) as conn:
        new=conn.execute("INSERT INTO public.messages(phone,role,message) VALUES(%s,'bot','New synthetic source write') RETURNING id",(PHONES['a'],)).fetchone()[0]
    second=client.get(path,query_string={'limit':2,'cursor':first['nextCursor']},headers=auth()).json
    assert [m['id'] for m in second['messages']]==['9007199254740993']
    assert second['nextCursor'] is None
    fresh=client.get(path+'?limit=2',headers=auth()).json
    assert fresh['messages'][-1]['id']==str(new)
    assert all(m['delivery_status']=='unknown' and m['provider_id'] is None for m in fresh['messages'])
    assert all('message_en' not in m for m in fresh['messages'])
    assert datetime.fromisoformat(first['messages'][0]['timestamp']).astimezone(timezone.utc)==datetime(2026,1,1,12,tzinfo=timezone.utc)


def test_cursor_binding_tampering_filters_and_principals(client):
    first=client.get('/api/conversations?limit=1',headers=auth()).json
    assert first['nextCursor']
    for params,user in [({'cursor':first['nextCursor'],'q':'changed'},'operator'),({'cursor':first['nextCursor']},'other'),({'cursor':'broken'},'operator')]:
        assert client.get('/api/conversations',query_string=params,headers=auth(user)).status_code==400
    assert client.get('/api/orders',query_string={'cursor':first['nextCursor']},headers=auth()).status_code==400
    assert client.get('/api/conversations?limit=101',headers=auth()).status_code==400
    assert client.get('/api/conversations?offset=1',headers=auth()).status_code==400


def test_conversation_pages_no_duplicates_under_source_updates(client):
    first=client.get('/api/conversations?limit=1',headers=auth()).json
    SyntheticBot().receive(PHONES['a'],'interleaved question')
    ids=[x['id'] for x in first['items']];cursor=first['nextCursor']
    while cursor:
        data=client.get('/api/conversations',query_string={'limit':1,'cursor':cursor},headers=auth()).json
        ids.extend(x['id'] for x in data['items']);cursor=data['nextCursor']
    assert len(ids)==len(set(ids))==3


def test_orders_referrals_source_fields_and_nullable_unknowns(client):
    order=client.get('/api/orders',headers=auth()).json['items'][0]
    assert isinstance(order['id'],str) and order['price'] is None and order['status']=='pending'
    assert 'address' not in order and 'user_id' not in order and order['quantity']==2
    referral=client.get('/api/referrals',headers=auth()).json['items'][0]
    assert referral['source']=='Synthetic a Poster 2' and isinstance(referral['id'],str)
    assert client.get('/api/orders?status=not-a-source-status',headers=auth()).json['items']==[]


def test_empty_is_success_unavailable_is_error(client,observer,monkeypatch):
    assert client.get('/api/conversations',headers=auth('empty')).json['items']==[]
    assert client.get('/api/conversations/'+ref('empty'),headers=auth()).json['messages']==[]
    def down(*args,**kwargs):raise psycopg.OperationalError('PRIVATE_SOURCE_SENTINEL')
    import rudo.observer as observer_module
    with monkeypatch.context() as patch:
        patch.setattr(observer_module,'_pools',{})  # Source unreachable: no pooled connections, new ones fail.
        patch.setattr(psycopg,'connect',down)
        response=client.get('/api/conversations',headers=auth())
    assert response.status_code==503 and 'items' not in response.json and 'PRIVATE' not in response.text


def test_audit_separate_append_only_and_failure_closed(observer,client,monkeypatch):
    before=snapshot()
    assert client.get('/api/conversations',headers=auth()).status_code==200
    with psycopg.connect(TEST_DSN) as conn:
        rows=conn.execute('SELECT action,rows_returned,resource_digest FROM observer_control.access_audit').fetchall()
    assert rows==[('conversations',3,None)] and snapshot()==before
    def failed(*args,**kwargs):raise RuntimeError('PRIVATE_AUDIT_SENTINEL')
    monkeypatch.setattr(observer.audit,'append',failed)
    result=client.get('/api/conversations',headers=auth())
    assert result.status_code==503 and result.json['error']=='audit_unavailable' and 'PRIVATE' not in result.text
    # A failed observer/audit does not prevent independent source processing.
    assert SyntheticBot().receive(PHONES['a'],'observer outage')['send_count']==1


@pytest.mark.parametrize('method,path',[
 ('POST','/api/conversations'),('PATCH','/api/conversations/fake'),('POST','/api/conversations/fake/messages'),
 ('PATCH','/api/orders/1'),('DELETE','/api/referrals/1'),('PUT','/api/anything'),('POST','/sendWhatsApp'),
 ('POST','/webhook'),('GET','/webhook'),('POST','/api/profile'),('POST','/api/agent-timeout')])
def test_all_mutations_and_webhooks_disabled(client,method,path):
    before=snapshot()
    response=client.open(path,method=method,headers=auth(),json={'to':'anything','message':'must never send'})
    assert response.status_code==405 and response.json['error']=='observer_read_only'
    assert snapshot()==before


def test_analyst_aggregate_only_and_supported_metrics(client):
    assert client.get('/api/conversations',headers=auth('analyst')).status_code==403
    for route in ('orders','referrals'):assert client.get('/api/'+route,headers=auth('analyst')).status_code==403
    data=client.get('/api/analytics',headers=auth('analyst')).json
    assert data['counts']=={'source_users':2,'conversations':3,'captured_messages':4,'orders':1,'referrals':1}
    assert 'response_time' in data['unavailableMetrics'] and 'delivery_rate' in data['unavailableMetrics']
    assert not any(key in json.dumps(data) for key in ('Other facility sentinel','INTERNAL_MODEL_CONTEXT','ADDRESS_SENTINEL'))


def test_direct_role_privileges_and_state_isolation(observer):
    for sql in ["INSERT INTO public.messages(phone,role,message) VALUES('x','user','x')",
                "UPDATE public.users SET language='x'","DELETE FROM public.orders","TRUNCATE public.referrals",
                "ALTER TABLE public.messages ADD COLUMN unsafe text","SELECT state FROM public.users",
                "SELECT message_en FROM public.messages","SELECT address FROM public.orders","SELECT * FROM public.user_state",
                "SELECT * FROM public.kv","UPDATE observer_control.staff SET role='admin'",
                "SET ROLE rudo_test_owner","CREATE TABLE public.unsafe(id int)",
                "SELECT * FROM observer_control.source_mappings","SELECT * FROM observer_control.scopes(false)"]:
        with psycopg.connect(observer.dsn) as conn:
            conn.execute('SET TRANSACTION READ WRITE') # Privileges must protect even if read-only default is overridden.
            conn.execute("SELECT set_config('observer.issuer',%s,true),set_config('observer.subject','operator',true),set_config('observer.source',%s,true)",(ISSUER,SOURCE))
            with pytest.raises(psycopg.Error):conn.execute(sql)
    with psycopg.connect(observer.audit.dsn) as conn:
        for sql in ['SELECT * FROM public.messages','SELECT * FROM observer_control.access_audit','UPDATE observer_control.access_audit SET action=\'history\'','TRUNCATE observer_control.access_audit']:
            with conn.transaction():
                with pytest.raises(psycopg.Error):conn.execute(sql)
    with psycopg.connect(observer.dsn) as conn:
        conn.execute("SELECT set_config('observer.issuer',%s,true),set_config('observer.subject','analyst',true),set_config('observer.source',%s,true)",(ISSUER,SOURCE))
        assert conn.execute('SELECT id FROM public.messages').fetchall()==[]


def test_source_state_model_context_and_observer_disabled_baseline(observer):
    # Comparison is synthetic local only, not a production/deployed model validation.
    initial=snapshot();observer.conversations(identity());observer.analytics(identity());observer.history(identity(),ref('a'))
    assert snapshot()==initial
    baseline=SyntheticBot().receive(PHONES['a'],'same synthetic question')
    bootstrap(TEST_DSN)
    enabled=SyntheticBot().receive(PHONES['a'],'same synthetic question',between=lambda:observer.conversations(identity()))
    assert baseline==enabled
    observed=observer.history(identity(),ref('a'))
    assert observed['messages'][-1]['message']==enabled['answer']


def test_concurrent_source_write_visibility_without_duplicates(observer):
    before=snapshot()
    with ThreadPoolExecutor(max_workers=3) as pool:
        jobs=[pool.submit(SyntheticBot().receive,PHONES['a'],'question '+str(i)) for i in range(3)]
        reads=[observer.conversations(identity()) for _ in range(2)]
        for job in jobs:job.result()
    messages=observer.history(identity(),ref('a'))['messages']
    assert len(messages)==len({m['id'] for m in messages})==9
    assert before!=snapshot()  # Only the synthetic writer changed source rows.


def test_no_private_business_schema_required_and_default_fail_closed(observer):
    with psycopg.connect(TEST_DSN) as conn:assert conn.execute("SELECT to_regnamespace('rudo')").fetchone()[0] is None
    assert observer.conversations(identity())['items']
    app=create_app({'TESTING':True},verifier=SyntheticVerifier())
    assert app.config['MODE']=='observer'
    with app.test_client() as client:
        assert client.post('/sendWhatsApp',headers=auth(),json={}).status_code==405
        assert client.get('/api/conversations',headers=auth()).status_code==503


def test_source_mapping_state_mismatch_not_merged(observer):
    initial=snapshot();assert PHONES['inconsistent'] not in {r['phone'] for r in observer.conversations(identity())['items']}
    assert snapshot()==initial


def test_effective_connection_roles_cannot_be_owner(observer):
    unsafe=Observer(TEST_DSN,observer.audit,SOURCE)
    with pytest.raises(Exception) as exc:unsafe.membership(identity())
    assert getattr(exc.value,'code',None)=='observer_role_required'
    audit=AccessAudit(TEST_DSN)
    with pytest.raises(Exception) as exc:audit.append(identity(),SOURCE,'membership',0)
    assert getattr(exc.value,'code',None)=='audit_role_required'


def test_summary_query_count_constant_as_scope_size_grows(observer,monkeypatch):
    original=psycopg.Connection.execute;count=[]
    def tracked(conn,*args,**kwargs):count.append(1);return original(conn,*args,**kwargs)
    monkeypatch.setattr(psycopg.Connection,'execute',tracked)
    observer.conversations(identity(),limit=100);small=len(count)
    with psycopg.connect(TEST_DSN) as conn:
        for i in range(40):
            phone='260000008'+str(i).zfill(3)
            conn.execute('INSERT INTO public.users(phone) VALUES(%s)',(phone,))
            conn.execute("INSERT INTO observer_control.source_mappings VALUES(%s,%s,'account-one','facility-a',true)",(SOURCE,phone))
    count.clear();result=observer.conversations(identity(),limit=100)
    assert len(result['items'])==43 and len(count)==small


def test_fixture_schema_matches_inspected_public_columns(observer):
    metadata=json.loads(Path('docs/integration-readiness/evidence/remote-metadata.json').read_text())
    expected={(c['table'],c['column']):(c['type'],c['not_null'],c['identity']) for c in metadata['columns']}
    with psycopg.connect(TEST_DSN) as conn:
        rows=conn.execute('''SELECT c.relname,a.attname,format_type(a.atttypid,a.atttypmod),a.attnotnull,a.attidentity
                            FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
                            WHERE n.nspname='public' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped''').fetchall()
    assert {(t,col):(typ,nn,mode) for t,col,typ,nn,mode in rows}==expected


def test_remote_flags_cannot_enable_observer_production_connection(observer,monkeypatch):
    remote=Observer('postgresql://example.invalid/postgres?sslmode=verify-full',observer.audit,SOURCE)
    app=create_app({'MODE':'observer','TESTING':True,'ENABLE_REMOTE_WRITES':True},observer=remote,verifier=SyntheticVerifier())
    result=app.test_client().get('/api/conversations',headers=auth())
    assert result.status_code==503 and result.json['error']=='remote_database_disabled'


def test_observer_does_not_use_private_pending_or_failed_history(observer):
    # There is no rudo store in this mode, and no private queue is read or fabricated.
    data=observer.history(identity(),ref('a'))
    assert len(data['messages'])==3
    assert all(m['delivery_status']=='unknown' for m in data['messages'])


def test_demo_provider_is_not_exposed_in_normal_mode(client,observer):
    assert client.get('/js/observer-demo-auth.js').status_code==404
    assert client.get('/js/./observer-demo-auth.js').status_code==404
    for page in ('cake_orders','profile','settings'):
        assert client.get('/'+page+'.html').status_code==404
    demo=create_app({'MODE':'observer','OBSERVER_SYNTHETIC_DEMO':True},observer=observer,verifier=SyntheticVerifier())
    assert b'www.gstatic.com' not in demo.test_client().get('/login.html').data


def test_signed_source_bigint_history_pagination(observer):
    # Identity columns can contain manually assigned signed bigint source IDs.
    with psycopg.connect(TEST_DSN) as conn:
        for mid in (-3,-2,-1):
            conn.execute("INSERT INTO public.messages(id,phone,role,message) VALUES(%s,%s,'user','Synthetic signed ID')",(mid,PHONES['empty']))
    identity={'issuer':ISSUER,'subject':'operator'}
    ref=reference(SOURCE,PHONES['empty'])
    page=observer.history(identity,ref,limit=2)
    assert [m['id'] for m in page['messages']]==['-2','-1']
    older=observer.history(identity,ref,limit=2,cursor=page['nextCursor'])
    assert [m['id'] for m in older['messages']]==['-3']
