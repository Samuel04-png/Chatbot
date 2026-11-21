"""Approved-export normalizer. Pure dry-run default; apply is local-loopback only."""
from datetime import datetime,timezone,timedelta
import hashlib
import json
import re
from uuid import NAMESPACE_URL,uuid5
from psycopg.types.json import Jsonb
import psycopg
from .db import Database

STATUSES={'pending','confirmed','completed','cancelled','paid','unpaid','collected','delivered'}


def decode(raw):
    for _ in range(3):
        if not isinstance(raw,str):return raw
        raw=json.loads(raw)
    if isinstance(raw,str):raise ValueError('encoding_depth')
    return raw


def timestamp(value):
    if value is None:return None
    if not isinstance(value,str):raise ValueError('ambiguous_time')
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None:raise ValueError('ambiguous_time')
    return stamp


def plan(document,now=None):
    now=now or datetime.now(timezone.utc)
    snapshot=timestamp(document['captured_at'])
    alias=document['source_alias']
    if not isinstance(alias,str) or not alias or snapshot is None:raise ValueError('invalid_manifest')
    results=[];counts={'discovered':0,'accepted':0,'quarantined':0,'expired':0,'excluded':0}
    seen={}
    for record in document['records']:
        if record['key'] in seen:
            if record != seen[record['key']]:raise ValueError('inconsistent_snapshot')
            continue
        seen[record['key']]=record;counts['discovered']+=1
        result={'key':record['key'],'alias':alias}
        try:
            ttl=record['pttl_ms']
            if type(ttl) is not int or ttl < -2:raise ValueError('invalid_expiry')
            expiry=snapshot+timedelta(milliseconds=ttl) if ttl>=0 else None
            if ttl==-2 or (expiry and expiry<=now):
                counts['expired']+=1;continue
            if record.get('type')!='string':raise ValueError('unsupported_type')
            key=record['key'];kind=('conversation' if key.startswith('conversation:') else 'order' if key.startswith('orders:') else 'referral' if key.startswith('referrals') else None)
            if kind is None:counts['excluded']+=1;continue
            value=decode(record['value'])
            if kind=='conversation':
                if not isinstance(value,list):raise ValueError('invalid_thread')
                if not re.fullmatch('[1-9][0-9]{9,14}',key.split(':',1)[1]):raise ValueError('invalid_phone')
                for message in value:
                    if not isinstance(message,dict):raise ValueError('invalid_message')
                    text=message.get('message',message.get('text',message.get('content')))
                    if not isinstance(text,str):raise ValueError('invalid_message')
                    timestamp(message.get('timestamp'))
            else:
                if not isinstance(value,dict):raise ValueError('invalid_object')
                timestamp(value.get('timestamp',value.get('createdAt')))
                if kind=='order' and value.get('status','pending') not in STATUSES:raise ValueError('unknown_status')
                if kind=='referral' and not isinstance(value.get('source'),str):raise ValueError('missing_source')
            digest=hashlib.sha256(json.dumps(record,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            result.update(kind=kind,value=value,expiry=expiry,digest=digest,raw=record,
                          id=uuid5(NAMESPACE_URL,json.dumps([alias,key],separators=(',',':'),ensure_ascii=False)))
            results.append(result);counts['accepted']+=1
        except (ValueError,TypeError,KeyError,OverflowError):
            counts['quarantined']+=1
    return results,counts


def apply_local(dsn,records,facility,account):
    Database().check_target(dsn)
    outcome={'inserted':0,'skipped':0}
    with psycopg.connect(dsn) as c:
        for r in records:
            previous=c.execute('SELECT source_digest FROM rudo.migration_records WHERE source_alias=%s AND source_key=%s FOR UPDATE',
                               (r['alias'],r['key'])).fetchone()
            if previous:
                if previous[0]!=r['digest']:raise ValueError('source_conflict')
                outcome['skipped']+=1;continue
            if r['expiry'] is not None:
                # Do not place expiring history into permanent tables without read-time expiry semantics.
                c.execute('INSERT INTO rudo.expiring_state(key,value,expires_at) VALUES(%s,%s,%s)',
                          (str(r['id']),Jsonb({'kind':r['kind'],'source':r['value']}),r['expiry']))
            elif r['kind']=='conversation':
                c.execute('''INSERT INTO rudo.conversations(id,phone,account_id,facility_id,created_at)
                             VALUES(%s,%s,%s,%s,NULL)''',(r['id'],r['key'].split(':',1)[1],account,facility))
                for i,m in enumerate(r['value']):
                    c.execute('''INSERT INTO rudo.messages(id,conversation_id,role,message,message_en,occurred_at,account_id)
                                 VALUES(%s,%s,%s,%s,%s,%s,%s)''',
                              (uuid5(r['id'],str(i)),r['id'],m.get('role','unknown'),m.get('message',m.get('text',m.get('content'))),
                               m.get('message_en'),timestamp(m.get('timestamp')),account))
            elif r['kind']=='order':
                value=r['value']
                c.execute('''INSERT INTO rudo.orders(id,source_key,facility_id,payload,status,created_at)
                             VALUES(%s,%s,%s,%s,%s,%s)''',(r['id'],json.dumps([r['alias'],r['key']],separators=(',',':'),ensure_ascii=False),facility,Jsonb(value),
                             value.get('status','pending'),timestamp(value.get('timestamp',value.get('createdAt')))))
            else:
                value=r['value']
                c.execute('''INSERT INTO rudo.referrals(id,source_key,facility_id,source,payload,occurred_at)
                             VALUES(%s,%s,%s,%s,%s,%s)''',(r['id'],json.dumps([r['alias'],r['key']],separators=(',',':'),ensure_ascii=False),facility,value['source'],Jsonb(value),
                             timestamp(value.get('timestamp',value.get('createdAt')))))
            c.execute('''INSERT INTO rudo.migration_records(source_alias,source_key,source_digest,target_id,expires_at,source_payload)
                         VALUES(%s,%s,%s,%s,%s,%s)''',(r['alias'],r['key'],r['digest'],r['id'],r['expiry'],Jsonb(r['raw'])))
            outcome['inserted']+=1
    return outcome


def reconcile_local(dsn, records):
    """Verify restricted source mappings and canonical target facts; emit only totals."""
    Database().check_target(dsn)
    counts={'expected':len(records),'matched':0,'mismatched':0}
    with psycopg.connect(dsn) as c:
        for r in records:
            mapping=c.execute('''SELECT source_digest,target_id,expires_at FROM rudo.migration_records
                                 WHERE source_alias=%s AND source_key=%s''',(r['alias'],r['key'])).fetchone()
            ok=bool(mapping and mapping==(r['digest'],r['id'],r['expiry']))
            if ok and r['expiry'] is not None:
                row=c.execute('SELECT value,expires_at FROM rudo.expiring_state WHERE key=%s',(str(r['id']),)).fetchone()
                ok=bool(row and row[0]=={'kind':r['kind'],'source':r['value']} and row[1]==r['expiry'])
            elif ok and r['kind']=='conversation':
                row=c.execute('SELECT id FROM rudo.conversations WHERE id=%s',(r['id'],)).fetchone()
                actual=c.execute('''SELECT id,role,message,occurred_at FROM rudo.messages
                                    WHERE conversation_id=%s ORDER BY source_ordinal''',(r['id'],)).fetchall()
                expected=[(uuid5(r['id'],str(i)),m.get('role','unknown'),m.get('message',m.get('text',m.get('content'))),timestamp(m.get('timestamp')))
                          for i,m in enumerate(r['value'])]
                ok=bool(row and actual==expected)
            elif ok:
                table='orders' if r['kind']=='order' else 'referrals'
                row=c.execute(f'SELECT payload FROM rudo.{table} WHERE id=%s',(r['id'],)).fetchone()
                ok=bool(row and row[0]==r['value'])
            counts['matched' if ok else 'mismatched']+=1
    return counts
