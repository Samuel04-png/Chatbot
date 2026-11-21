from concurrent.futures import ThreadPoolExecutor
import hashlib,hmac,json,socket
from uuid import uuid4
import psycopg
import pytest
from conftest import TEST_DSN,ISSUER,headers


def signature(payload,secret='synthetic-secret'):
    raw=json.dumps(payload,ensure_ascii=False).encode()
    return raw,{'X-Hub-Signature-256':'sha256='+hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest(),
                'Content-Type':'application/json'}


def webhook(messages=None,statuses=None,account='synthetic-account'):
    value={'metadata':{'phone_number_id':account}}
    if messages is not None:value['messages']=messages
    if statuses is not None:value['statuses']=statuses
    return {'object':'whatsapp_business_account','entry':[{'changes':[{'field':'messages','value':value}]}]}


def event(mid='synthetic-1',text='Synthetic text ñ'):
    return {'id':mid,'from':'260000000003','timestamp':'1780000000','type':'text','text':{'body':text}}


@pytest.mark.parametrize('route',['/api/me','/api/conversations','/api/orders','/api/referrals','/api/analytics','/api/qr-analytics'])
def test_anonymous_denied(client,route):assert client.get(route).status_code==401


@pytest.mark.parametrize('identity,code',[('unknown',403),('disabled',403),('expired',401),('revoked',401),('wrong-project',401)])
def test_identity_gate(client,identity,code):assert client.get('/api/conversations',headers=headers(identity)).status_code==code


def test_scopes_and_roles(client,database):
    result=client.get('/api/conversations',headers=headers()).json
    assert [r['id'] for r in result['items']]==[database.test_ids['a']]
    assert client.get('/api/conversations/'+database.test_ids['b'],headers=headers()).status_code==404
    assert len(client.get('/api/conversations',headers=headers('admin')).json['items'])==2
    assert client.get('/api/conversations',headers=headers('analyst')).status_code==403
    assert client.get('/api/analytics',headers=headers('analyst')).json=={'conversations':1,'orders':1,'referrals':4}


def test_open_conversation_and_resolution(client,database):
    assert client.post('/api/conversations',headers=headers(),json={'phone':'0978000000','facilityId':'clinic-a'}).status_code==400
    assert client.post('/api/conversations',headers=headers(),json={'phone':'+260000000009','facilityId':'clinic-b'}).status_code==403
    response=client.post('/api/conversations',headers=headers(),json={'phone':'+260000000009','facilityId':'clinic-a'})
    assert response.status_code==201
    cid=response.json['id']
    result=client.patch('/api/conversations/'+cid,headers=headers(),json={'status':'closed','version':1})
    assert result.status_code==200 and result.json['version']==2
    assert client.get('/api/conversations/'+cid,headers=headers()).json['status']=='closed'
    assert client.patch('/api/conversations/'+cid,headers=headers(),json={'status':'active','version':1}).status_code==409


def test_send_idempotency_scope_and_validation(client,database):
    path='/api/conversations/'+database.test_ids['a']+'/messages'
    op=str(uuid4());h=headers(**{'Idempotency-Key':op})
    for _ in range(2):assert client.post(path,headers=h,json={'message':'Synthetic outbound'}).status_code==202
    assert client.post(path,headers=h,json={'message':'Changed body'}).status_code==409
    assert client.post(path,headers=headers(),json={'message':'test'}).status_code==400
    assert client.post(path,headers=headers(**{'Idempotency-Key':str(uuid4())}),json={'message':'x'*4097}).status_code==400
    assert client.post('/api/conversations/'+database.test_ids['b']+'/messages',headers=h,json={'message':'test'}).status_code==404
    assert client.post('/sendWhatsApp',json={'to':'untrusted','message':'x'}).status_code==401
    assert client.post('/sendWhatsApp',headers=headers(),json={}).status_code==410
    with psycopg.connect(TEST_DSN) as c:assert c.execute('SELECT count(*) FROM rudo.outbox').fetchone()[0]==1


def test_send_rate_and_origin(client,database):
    path='/api/conversations/'+database.test_ids['a']+'/messages'
    assert client.post(path,headers=headers(Origin='https://untrusted.test'),json={}).status_code==403
    for i in range(20):
        assert client.post(path,headers=headers(**{'Idempotency-Key':str(uuid4())}),json={'message':'synthetic'}).status_code==202
    assert client.post(path,headers=headers(**{'Idempotency-Key':str(uuid4())}),json={'message':'synthetic'}).status_code==429


def test_order_status_conflict(client,database):
    path='/api/orders/'+database.test_ids['order']
    assert client.patch(path,headers=headers(),json={'status':'paid','version':1}).status_code==200
    assert client.patch(path,headers=headers(),json={'status':'cancelled','version':1}).status_code==409
    assert client.patch(path,headers=headers(),json={'status':'bogus','version':2}).status_code==400
    assert client.get('/api/orders',headers=headers()).json['items'][0]['status']=='paid'


def test_qr_sources(client):
    data=client.get('/api/qr-analytics',headers=headers()).json
    assert data['totalRecords']==4 and data['matchedRecords']==3
    assert data['counts']['Mandebvu Clinic']=={'Poster 1':1,'Poster 2':1,'Flyer':0}


def test_signature_verification_and_challenge(client):
    assert client.get('/webhook?hub.mode=subscribe&hub.verify_token=synthetic-verify&hub.challenge=123').data==b'123'
    assert client.get('/webhook?hub.mode=subscribe&hub.verify_token=bad&hub.challenge=123').status_code==403
    payload=webhook([event()]);raw,h=signature(payload)
    assert client.post('/webhook',data=raw,content_type='application/json').status_code==403
    assert client.post('/webhook',data=raw+b' ',headers=h).status_code==403
    assert client.post('/webhook',data=raw,headers={**h,'X-Hub-Signature-256':'sha256=bad'}).status_code==403
    assert client.post('/webhook',data=raw,headers=h).status_code==200


def test_webhook_batch_duplicate_and_privacy(client,caplog):
    payload=webhook([event('a','PRIVATE_SYNTHETIC_SENTINEL'),event('b')]);raw,h=signature(payload)
    assert client.post('/webhook',data=raw,headers=h).json['events']==2
    assert client.post('/webhook',data=raw,headers=h).json['events']==0
    with psycopg.connect(TEST_DSN) as c:
        assert c.execute('SELECT count(*) FROM rudo.messages').fetchone()[0]==2
        assert c.execute('SELECT count(*) FROM rudo.webhook_inbox').fetchone()[0]==2
    assert 'PRIVATE_SYNTHETIC_SENTINEL' not in caplog.text
    conflict,hh=signature(webhook([event('a','different')]))
    assert client.post('/webhook',data=conflict,headers=hh).status_code==409


def test_webhook_wrong_account_and_transaction_rollback(client):
    raw,h=signature(webhook([event()],account='other'))
    assert client.post('/webhook',data=raw,headers=h).status_code==403
    broken=event('broken');broken['timestamp']='invalid'
    raw,h=signature(webhook([event('valid'),broken]))
    assert client.post('/webhook',data=raw,headers=h).status_code==400
    with psycopg.connect(TEST_DSN) as c:assert c.execute('SELECT count(*) FROM rudo.messages').fetchone()[0]==0


def test_webhook_concurrent_duplicate(app):
    raw,h=signature(webhook([event()]))
    def call(_):
        with app.test_client() as client:return client.post('/webhook',data=raw,headers=h).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:assert list(pool.map(call,range(4)))==[200]*4
    with psycopg.connect(TEST_DSN) as c:assert c.execute('SELECT count(*) FROM rudo.messages').fetchone()[0]==1


def test_error_redaction_and_non_ack(client,app,monkeypatch,caplog):
    def fail(*args):raise RuntimeError('PRIVATE_SYNTHETIC_TOKEN_AND_TEXT')
    monkeypatch.setattr(app.extensions['rudo_db'],'accept_webhook',fail)
    raw,h=signature(webhook([event()]))
    response=client.post('/webhook',data=raw,headers=h)
    assert response.status_code==503
    assert 'PRIVATE_SYNTHETIC' not in response.text+caplog.text


def test_private_headers_and_assets(client):
    response=client.get('/chats.html')
    assert response.status_code==200 and response.headers['Cache-Control']=='no-store'
    assert response.headers['X-Frame-Options']=='DENY'
    assert client.get('/app.py').status_code==404
    assert client.get('/cake_orders.html').status_code==404
    assert client.get('/chats%20copy.html').status_code==404
    assert client.get('/js/../../app.py').status_code==404


def test_network_denial():
    with pytest.raises(RuntimeError):socket.create_connection(('example.com',443))
    with pytest.raises(RuntimeError):psycopg.connect('postgresql://example.com/production')


def test_staff_revocation_effective_on_next_request(client):
    assert client.get('/api/me',headers=headers()).status_code==200
    with psycopg.connect(TEST_DSN) as c:
        c.execute('UPDATE rudo.staff_memberships SET active=false WHERE issuer=%s AND subject=%s',(ISSUER,'operator'))
    assert client.get('/api/me',headers=headers()).status_code==403


def test_signed_malformed_and_oversized_webhook(client):
    raw,h=signature({'object':'whatsapp_business_account','entry':[None]})
    assert client.post('/webhook',data=raw,headers=h).status_code==400
    assert client.post('/webhook',data=b'x'*(1024*1024+1),content_type='application/json').status_code==413


def test_status_events_out_of_order(client,database):
    with psycopg.connect(TEST_DSN) as c:
        c.execute('''INSERT INTO rudo.messages(id,conversation_id,role,message,account_id,provider_id,delivery_status)
                     VALUES(%s,%s,'bot','Synthetic outbound','synthetic-account','provider-status','sent')''',
                  (uuid4(),database.test_ids['a']))
    for status,stamp in [('read','1780000002'),('delivered','1780000001'),('sent','1780000000')]:
        raw,h=signature(webhook(statuses=[{'id':'provider-status','status':status,'timestamp':stamp}]))
        assert client.post('/webhook',data=raw,headers=h).status_code==200
    with psycopg.connect(TEST_DSN) as c:
        assert c.execute("SELECT delivery_status FROM rudo.messages WHERE provider_id='provider-status'").fetchone()[0]=='read'
