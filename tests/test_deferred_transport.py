"""Known legacy transport gaps: explicit expected failures, never production transport activation."""
import json,hmac,hashlib
from uuid import uuid4
from unittest.mock import Mock
import psycopg
import pytest
from conftest import TEST_DSN,ISSUER
from rudo.delivery import deliver_one,mark_stale_unknown


@pytest.mark.xfail(strict=True,reason='Deferred owner-contract fix: late failed must not regress delivered. Observer cannot ingest/send.')
def test_legacy_delivered_then_late_failed_keeps_delivery_evidence(app,database):
    with psycopg.connect(TEST_DSN) as c:
        c.execute("INSERT INTO rudo.messages(id,conversation_id,role,message,account_id,provider_id,delivery_status) VALUES(%s,%s,'bot','Synthetic','synthetic-account','late-status','delivered')",(uuid4(),database.test_ids['a']))
    value={'object':'whatsapp_business_account','entry':[{'changes':[{'field':'messages','value':{'metadata':{'phone_number_id':'synthetic-account'},'statuses':[{'id':'late-status','status':'failed','timestamp':'1780000000'}]}}]}]}
    raw=json.dumps(value).encode();signature='sha256='+hmac.new(b'synthetic-secret',raw,hashlib.sha256).hexdigest()
    app.test_client().post('/webhook',data=raw,headers={'Content-Type':'application/json','X-Hub-Signature-256':signature})
    with psycopg.connect(TEST_DSN) as c:assert c.execute("SELECT delivery_status FROM rudo.messages WHERE provider_id='late-status'").fetchone()[0]=='delivered'


@pytest.mark.xfail(strict=True,reason='Deferred owner-contract fix: legacy completion lacks claim fencing. Observer never runs delivery worker.')
def test_legacy_stale_completion_cannot_overwrite_reconciled_unknown(database):
    operation=uuid4();database.enqueue({'issuer':ISSUER,'subject':'operator'},database.test_ids['a'],'Synthetic',operation)
    def provider_side_effect(phone,message):
        with psycopg.connect(TEST_DSN) as c:c.execute("UPDATE rudo.outbox SET updated_at=now()-interval '5 minutes' WHERE id=%s",(operation,))
        assert mark_stale_unknown(database)==1
        return 'sent','provider-synthetic-stale'
    sender=Mock(account='synthetic-account');sender.send.side_effect=provider_side_effect
    deliver_one(database,sender)
    with psycopg.connect(TEST_DSN) as c:assert c.execute('SELECT status FROM rudo.outbox WHERE id=%s',(operation,)).fetchone()[0]=='unknown'
