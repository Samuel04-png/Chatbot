"""Explicitly enabled worker. Unknown outcomes are never automatically resent."""
import os
import re
from uuid import uuid4
import requests
from .errors import ApiError


class MetaSender:
    def __init__(self, token, account, version, enabled=False):
        self.token,self.account,self.version,self.enabled = token,account,version,enabled

    def send(self, phone, message):
        if not self.enabled or not self.token or not self.account or not re.fullmatch(r'v\d+\.\d+',self.version):
            raise ApiError(503,'delivery_disabled')
        response=requests.post(f'https://graph.facebook.com/{self.version}/{self.account}/messages',
                               headers={'Authorization':'Bearer '+self.token},
                               json={'messaging_product':'whatsapp','to':phone,'type':'text','text':{'body':message}},
                               timeout=(5,20))
        if response.status_code>=500:
            # A provider/proxy error can follow acceptance: do not assume safe to retry.
            return 'unknown',None
        if response.status_code>=400:
            return 'failed',None
        try:
            provider_id=response.json()['messages'][0]['id']
            if not isinstance(provider_id,str) or not provider_id:
                raise ValueError()
            return 'sent',provider_id
        except (KeyError,IndexError,ValueError,TypeError):
            return 'unknown',None


def deliver_one(db, sender):
    with db.transaction(worker=True) as c:
        row=c.execute('''SELECT o.*,c.phone,c.account_id FROM rudo.outbox o JOIN rudo.conversations c ON c.id=o.conversation_id
                         WHERE o.status='pending' ORDER BY o.created_at FOR UPDATE OF o SKIP LOCKED LIMIT 1''').fetchone()
        if not row:return False
        if row['account_id'] != sender.account:
            raise ApiError(503,'wrong_messaging_account')
        c.execute("UPDATE rudo.outbox SET status='sending',attempts=attempts+1,updated_at=now() WHERE id=%s",(row['id'],))
    # Claim committed before external side effect. A crash leaves sending, never pending.
    try:
        status,provider_id=sender.send(row['phone'],row['message'])
    except ApiError:
        # Configuration disabled: no external call occurred, safely return to pending.
        with db.transaction(worker=True) as c:
            c.execute("UPDATE rudo.outbox SET status='pending',updated_at=now() WHERE id=%s",(row['id'],))
        raise
    except Exception:
        status,provider_id='unknown',None
    with db.transaction(worker=True) as c:
        c.execute('UPDATE rudo.outbox SET status=%s,provider_id=%s,updated_at=now() WHERE id=%s',
                  (status,provider_id,row['id']))
        if status=='sent':
            prior=c.execute('''SELECT delivery_status FROM rudo.webhook_inbox WHERE account_id=%s AND provider_id=%s
                               AND delivery_status IN ('read','delivered','sent','failed')
                               ORDER BY CASE delivery_status WHEN 'read' THEN 4 WHEN 'delivered' THEN 3 WHEN 'sent' THEN 2 ELSE 1 END DESC LIMIT 1''',
                            (row['account_id'],provider_id)).fetchone()
            delivery=prior['delivery_status'] if prior else 'sent'
            c.execute('''INSERT INTO rudo.messages(id,conversation_id,role,message,occurred_at,provider_id,account_id,delivery_status)
                         VALUES(%s,%s,'bot',%s,now(),%s,%s,%s)''',
                      (uuid4(),row['conversation_id'],row['message'],provider_id,row['account_id'],delivery))
    return True


def mark_stale_unknown(db, seconds=120):
    if seconds<30:raise ValueError('lease window too short')
    with db.transaction(worker=True) as c:
        return c.execute("UPDATE rudo.outbox SET status='unknown',updated_at=now() WHERE status='sending' AND updated_at<now()-(%s * interval '1 second') RETURNING id",(seconds,)).rowcount


def main():
    from .db import Database
    # Even if delivery is enabled, remote databases remain independently blocked by default.
    sender=MetaSender(os.getenv('WHATSAPP_TOKEN',''),os.getenv('WHATSAPP_PHONE_NUMBER_ID',''),
                      os.getenv('WHATSAPP_API_VERSION',''),os.getenv('RUDO_ENABLE_MESSAGE_DELIVERY')=='true')
    if not sender.enabled:
        raise SystemExit('Delivery is disabled. No message was sent.')
    db=Database(worker_dsn=os.getenv('RUDO_WORKER_DATABASE_URL',''),
                allow_remote=os.getenv('RUDO_ENABLE_REMOTE_WRITES')=='true')
    print('Processed one operation.' if deliver_one(db,sender) else 'No pending operations.')


if __name__=='__main__':main()
