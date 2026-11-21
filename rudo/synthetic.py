"""Explicit disposable local fixture/demo harness. Never discovers Supabase or production settings."""
from pathlib import Path
import hashlib
import json
from datetime import datetime,timezone
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
from .db import Database
from .errors import ApiError
from .observer import Observer,AccessAudit,reference

ROOT=Path(__file__).resolve().parents[1]
LOCAL_DSN='postgresql://rudo_test_owner@127.0.0.1:55439/rudo_test'
SOURCE='synthetic-public'
ISSUER='https://securetoken.google.com/synthetic-test'
PHONES={'a':'260000000101','b':'260000000102','c':'260000000103','unmapped':'260000000104',
        'ambiguous':'260000000105','empty':'260000000106','history_only':'260000000107','inconsistent':'260000000108'}


def assert_disposable(dsn):
    Database().check_target(dsn)
    info=conninfo_to_dict(dsn)
    if info.get('host')!='127.0.0.1' or info.get('port')!='55439' or info.get('dbname')!='rudo_test' or info.get('user')!='rudo_test_owner':
        raise RuntimeError('Only the isolated marked test database is permitted')
    with psycopg.connect(dsn) as conn:
        if conn.execute("SELECT current_setting('rudo.synthetic_test_cluster',true)").fetchone()[0]!='synthetic-only':
            raise RuntimeError('Disposable synthetic cluster marker required')


def clear_source(dsn):
    assert_disposable(dsn)
    with psycopg.connect(dsn) as conn:
        conn.execute('DROP SCHEMA IF EXISTS observer_control CASCADE')
        for table in ('messages','orders','referrals','users','kv','user_state'):
            conn.execute('DROP TABLE IF EXISTS public.'+table+' CASCADE')


MIGRATION=ROOT/'supabase/migrations/20261121120000_rudo_staff_control.sql'
FACILITIES=[('account-one','facility-a','Facility A'),('account-one','facility-b','Facility B'),
            ('account-two','facility-a','Account two Facility A'),('account-two','facility-b','Account two Facility B'),
            ('account-empty','facility-empty','Empty facility')]
IDENTITIES=[('operator','operator','active',[('account-one','facility-a')]),
            ('other','operator','active',[('account-one','facility-b')]),
            ('second-account','operator','active',[('account-two','facility-a')]),
            ('admin','admin','active',[('account-one','facility-a'),('account-one','facility-b'),('account-two','facility-a')]),
            ('analyst','analyst','active',[('account-one','facility-a')]),
            ('disabled','operator','suspended',[('account-one','facility-a')]),
            ('empty','operator','active',[('account-empty','facility-empty')])]


def staff_id(conn,subject,issuer=ISSUER):
    return conn.execute('SELECT staff_id FROM observer_control.staff_identities WHERE issuer=%s AND subject=%s',(issuer,subject)).fetchone()[0]


def bootstrap(dsn=LOCAL_DSN):
    clear_source(dsn)
    with psycopg.connect(dsn) as conn:
        conn.execute((ROOT/'staging/observer/source_fixture.sql').read_text())
        conn.execute(MIGRATION.read_text())  # The exact production migration file.
        for account,facility,name in FACILITIES:
            conn.execute('INSERT INTO observer_control.facilities(source_id,account_id,facility_id,display_name) VALUES(%s,%s,%s,%s)',
                         (SOURCE,account,facility,name))
        for subject,role,status,scopes in IDENTITIES:
            sid=conn.execute("INSERT INTO observer_control.staff(email,display_name,role,status,created_by) VALUES(%s,%s,%s,%s,'synthetic') RETURNING id",
                             (subject+'@example.test','Synthetic '+subject,role,status)).fetchone()[0]
            conn.execute("INSERT INTO observer_control.staff_identities(issuer,subject,provider,staff_id,email,link_method,linked_by) VALUES(%s,%s,'firebase',%s,%s,'bootstrap','synthetic')",
                         (ISSUER,subject,sid,subject+'@example.test'))
            for account,facility in scopes:
                conn.execute("INSERT INTO observer_control.staff_scopes(staff_id,source_id,account_id,facility_id,granted_by) VALUES(%s,%s,%s,%s,'synthetic')",
                             (sid,SOURCE,account,facility))
        for name,phone in PHONES.items():
            if name=='history_only':continue
            conn.execute('''INSERT INTO public.users(phone,user_id,language,state,created_at,updated_at)
                            VALUES(%s,%s,%s,%s,'2026-01-01T00:00:00Z','2026-01-01T00:00:00Z')''',
                         (phone,None if name=='empty' else 'SYN-'+name,None if name=='empty' else 'english',
                          json.dumps({'step':'source-owned','state_sentinel':name})))
        mappings=[('a','account-one','facility-a'),('b','account-one','facility-b'),('c','account-two','facility-a'),
                  ('ambiguous','account-one','facility-a'),('ambiguous','account-two','facility-b'),
                  ('empty','account-one','facility-a'),('history_only','account-one','facility-a')]
        for name,account,facility in mappings:
            conn.execute("INSERT INTO observer_control.source_mappings(source_id,phone,account_id,facility_id,approved,approved_by) VALUES(%s,%s,%s,%s,true,'synthetic')",
                         (SOURCE,PHONES[name],account,facility))
        messages=[(9007199254740993,'a','user','Synthetic inbound one'),
                  (9007199254740994,'a','bot','Synthetic source answer; delivery unverified'),
                  (9007199254740995,'a','user','Synthetic latest question'),
                  (20,'b','user','Other facility sentinel'),(21,'c','user','Other account sentinel'),
                  (22,'unmapped','user','Unmapped source sentinel'),(23,'ambiguous','user','Ambiguous source sentinel'),
                  (24,'history_only','bot','History without a users row')]
        for mid,name,role,text in messages:
            conn.execute('''INSERT INTO public.messages(id,phone,role,message,message_en,created_at)
                            VALUES(%s,%s,%s,%s,%s,'2026-01-01T12:00:00Z')''',
                         (mid,PHONES[name],role,text,'INTERNAL_MODEL_CONTEXT_'+name))
        conn.execute("SELECT setval(pg_get_serial_sequence('public.messages','id'),9007199254740995)")
        for name,status,price in [('a','pending',None),('b','paid','ZMW 20.00'),('c','confirmed','12.50'),('unmapped','pending','9')]:
            conn.execute('''INSERT INTO public.orders(phone,product,price,quantity,address,status,created_at)
                            VALUES(%s,'Synthetic source product',%s,2,'ADDRESS_SENTINEL_NO_READ',%s,'2026-01-01T00:00:00Z')''',(PHONES[name],price,status))
            conn.execute("INSERT INTO public.referrals(phone,source,created_at) VALUES(%s,%s,'2026-01-01T00:00:00Z')",(PHONES[name], 'Synthetic '+name+' Poster 2'))
        conn.execute("INSERT INTO public.kv VALUES('source-session','DO_NOT_READ_SESSION',now()+interval '1 hour')")
        conn.execute('''INSERT INTO public.user_state(user_id,phone_digits,step,language,registered)
                        VALUES('unrelated-state','260000009999','"independent"','{"code":"unknown"}',NULL)''')
    return adapter(dsn)


def adapter(dsn=LOCAL_DSN):
    reader=make_conninfo(dsn,user='rudo_observer');audit=make_conninfo(dsn,user='rudo_observer_audit')
    return Observer(reader,AccessAudit(audit),SOURCE,cursor_secret=b'synthetic-test-cursor-secret')


def snapshot(dsn=LOCAL_DSN):
    """Synthetic owner-only equality proof, never used against real data."""
    assert_disposable(dsn)
    with psycopg.connect(dsn) as conn:
        data={t:conn.execute('SELECT row_to_json(t) FROM public.'+t+' t ORDER BY row_to_json(t)::text').fetchall()
              for t in ('users','messages','orders','referrals','kv','user_state')}
    return hashlib.sha256(json.dumps(data,sort_keys=True,default=str).encode()).hexdigest()


class SyntheticVerifier:
    def verify(self,token):
        if not token.startswith('synthetic:') or token.split(':',1)[1] in ('expired','revoked','invalid'):
            raise ApiError(401,'invalid_identity')
        subject=token.split(':',1)[1]
        # 'synthetic:unverified-<uid>' models a sign-in whose email is not verified.
        return {'issuer':ISSUER,'subject':subject,'provider':'firebase',
                'email':subject.removeprefix('unverified-')+'@example.test','email_verified':not subject.startswith('unverified-')}


class SyntheticBot:
    """Local source writer simulates fixed inference, context use and existing bot writes."""
    def __init__(self,dsn=LOCAL_DSN):self.dsn=dsn;self.sent=[]
    def receive(self,phone,prompt,between=None):
        assert_disposable(self.dsn)
        with psycopg.connect(self.dsn) as conn:
            context=conn.execute('SELECT role,message_en FROM public.messages WHERE phone=%s ORDER BY id DESC LIMIT 4',(phone,)).fetchall()
            conn.execute('INSERT INTO public.messages(phone,role,message,message_en) VALUES(%s,\'user\',%s,%s)',(phone,prompt,'EN:'+prompt))
        if between:between()
        answer='Synthetic fixed answer for '+prompt
        self.sent.append(answer)
        with psycopg.connect(self.dsn) as conn:
            conn.execute("INSERT INTO public.messages(phone,role,message,message_en) VALUES(%s,'bot',%s,%s)",(phone,answer,'EN:'+answer))
        return {'context':context,'answer':answer,'send_count':len(self.sent)}


def admin_dsn(dsn=LOCAL_DSN):
    return make_conninfo(dsn,user='rudo_staff_admin')
