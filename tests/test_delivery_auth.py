from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import Mock
import psycopg
import pytest
import requests
from conftest import ISSUER,TEST_DSN
from rudo.auth import FirebaseVerifier
from rudo.delivery import MetaSender,deliver_one
from rudo.errors import ApiError


def test_firebase_adapter_checks_revocation_and_project(monkeypatch):
    import firebase_admin.auth as auth
    claims={'sub':'synthetic-uid','uid':'synthetic-uid','aud':'synthetic-test','iss':ISSUER}
    verify=Mock(return_value=claims)
    monkeypatch.setattr(auth,'verify_id_token',verify)
    verifier=FirebaseVerifier('synthetic-test');verifier.app=object()
    assert verifier.verify('synthetic-id-token')=={'subject':'synthetic-uid','issuer':ISSUER,'provider':'firebase','email':None,'email_verified':False}
    assert verify.call_args.kwargs['check_revoked'] is True
    verify.return_value={**claims,'email':'staff@example.test','email_verified':True}
    verify.return_value={**claims,'email':'staff@example.test','email_verified':'true'}  # Only boolean true counts.
    assert verifier.verify('t')['email_verified'] is False
    verify.return_value=claims
    for field,value in [('aud','other-project'),('iss','wrong-issuer'),('sub','wrong-subject')]:
        mutated={**claims,field:value};verify.return_value=mutated
        with pytest.raises(ApiError) as exc:verifier.verify('synthetic-id-token')
        assert exc.value.status==401
    verify.side_effect=auth.RevokedIdTokenError('synthetic-revoked')
    with pytest.raises(ApiError) as exc:verifier.verify('synthetic-id-token')
    assert exc.value.status==401


def test_firebase_unconfigured():
    with pytest.raises(ApiError) as exc:FirebaseVerifier('').verify('synthetic')
    assert exc.value.status==503


@pytest.mark.parametrize('status,body,result',[
    (200,{'messages':[{'id':'provider-synthetic'}]},('sent','provider-synthetic')),
    (400,{},('failed',None)),(429,{},('failed',None)),(500,{},('unknown',None)),(200,{},('unknown',None))])
def test_meta_response_contract(monkeypatch,status,body,result):
    response=SimpleNamespace(status_code=status,json=lambda:body)
    post=Mock(return_value=response);monkeypatch.setattr(requests,'post',post)
    sender=MetaSender('synthetic-token','synthetic-account','v99.0',True)
    assert sender.send('260000000001','Synthetic outbound')==result
    assert post.call_args.kwargs['timeout']==(5,20)


def test_meta_disabled_no_call(monkeypatch):
    post=Mock();monkeypatch.setattr(requests,'post',post)
    with pytest.raises(ApiError):MetaSender('','','',False).send('synthetic','test')
    post.assert_not_called()


@pytest.mark.parametrize('mode,expected',[('success','sent'),('timeout','unknown'),('declined','failed')])
def test_delivery_worker_no_automatic_resend(database,mode,expected):
    identity={'issuer':ISSUER,'subject':'operator'}
    operation=uuid4()
    database.enqueue(identity,database.test_ids['a'],'Synthetic outbound',operation)
    sender=Mock(account='synthetic-account')
    if mode=='timeout':sender.send.side_effect=requests.Timeout('synthetic-private-provider-body')
    else:sender.send.return_value=('sent','synthetic-provider-id') if mode=='success' else ('failed',None)
    assert deliver_one(database,sender)
    assert not deliver_one(database,sender)
    assert sender.send.call_count==1
    with psycopg.connect(TEST_DSN) as c:
        assert c.execute('SELECT status FROM rudo.outbox WHERE id=%s',(operation,)).fetchone()[0]==expected
        assert c.execute('SELECT count(*) FROM rudo.messages').fetchone()[0]==(1 if expected=='sent' else 0)


def test_crashed_claim_becomes_unknown_without_resend(database):
    from rudo.delivery import mark_stale_unknown
    database.enqueue({'issuer':ISSUER,'subject':'operator'},database.test_ids['a'],'Synthetic outbound',uuid4())
    with psycopg.connect(TEST_DSN) as c:
        c.execute("UPDATE rudo.outbox SET status='sending',updated_at=now()-interval '5 minutes'")
    assert mark_stale_unknown(database)==1
    sender=Mock(account='synthetic-account')
    assert not deliver_one(database,sender)
    sender.send.assert_not_called()


def test_real_firebase_sdk_verifies_synthetic_signatures_offline(monkeypatch):
    """Use the real SDK crypto path with ephemeral RSA/certificate and stubbed identity lookup."""
    from datetime import datetime,timedelta,timezone
    import json,time
    import jwt
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from firebase_admin import initialize_app,delete_app,credentials,_token_gen,_auth_client
    from google.auth.credentials import AnonymousCredentials
    class SyntheticCredential(credentials.Base):
        def get_credential(self):return AnonymousCredentials()
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'synthetic.test')])
    now=datetime.now(timezone.utc)
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
          .not_valid_after(now+timedelta(days=1)).sign(key,hashes.SHA256()))
    response=SimpleNamespace(status=200,data=json.dumps({'synthetic-key':cert.public_bytes(serialization.Encoding.PEM).decode()}).encode())
    monkeypatch.setattr(_token_gen.CertificateFetchRequest,'__call__',lambda *args,**kwargs:response)
    user=SimpleNamespace(disabled=False,tokens_valid_after_timestamp=0)
    monkeypatch.setattr(_auth_client.Client,'get_user',lambda *args,**kwargs:user)
    app=initialize_app(SyntheticCredential(),{'projectId':'synthetic-test'},name='synthetic-'+str(uuid4()))
    verifier=FirebaseVerifier('synthetic-test');verifier.app=app
    base={'aud':'synthetic-test','iss':ISSUER,'sub':'synthetic-uid','iat':int(time.time()),'exp':int(time.time())+3600,'auth_time':int(time.time())}
    def token(claims=base,signing_key=key):return jwt.encode(claims,signing_key,algorithm='RS256',headers={'kid':'synthetic-key'})
    try:
        assert verifier.verify(token())['subject']=='synthetic-uid'
        for claims in [{**base,'aud':'wrong'},{**base,'iss':'wrong'},{**base,'exp':int(time.time())-10}]:
            with pytest.raises(ApiError) as exc:verifier.verify(token(claims))
            assert exc.value.status==401
        other=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        with pytest.raises(ApiError) as exc:verifier.verify(token(signing_key=other))
        assert exc.value.status==401
        user.disabled=True
        with pytest.raises(ApiError) as exc:verifier.verify(token())
        assert exc.value.status==401
        user.disabled=False;user.tokens_valid_after_timestamp=(int(time.time())+60)*1000
        with pytest.raises(ApiError) as exc:verifier.verify(token())
        assert exc.value.status==401
    finally:delete_app(app)
