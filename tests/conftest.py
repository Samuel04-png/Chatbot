"""Synthetic-only suite: all Python sockets denied, libpq confined to test cluster."""
import os
from pathlib import Path
import socket
import sys
from uuid import uuid4

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app import create_app
from rudo.db import Database
from rudo.errors import ApiError
from scripts.apply_local_migrations import apply

TEST_PORT=55439
TEST_DSN=f'postgresql://rudo_test_owner@127.0.0.1:{TEST_PORT}/rudo_test'
ISSUER='https://securetoken.google.com/synthetic-test'


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def denied(*args,**kwargs):raise RuntimeError('Network denied in automated tests')
    monkeypatch.setattr(socket.socket,'connect',denied)
    monkeypatch.setattr(socket.socket,'connect_ex',denied)
    monkeypatch.setattr(socket,'create_connection',denied)
    real_connect=psycopg.connect
    def confined(conninfo='',*args,**kwargs):
        info=conninfo_to_dict(conninfo,**{k:v for k,v in kwargs.items() if k in ('host','port','dbname')})
        if info.get('host')!='127.0.0.1' or info.get('port')!=str(TEST_PORT) or info.get('dbname')!='rudo_test':
            raise RuntimeError('Non-test libpq connection denied')
        return real_connect(conninfo,*args,**kwargs)
    monkeypatch.setattr(psycopg,'connect',confined)
    for name in list(os.environ):
        if name != 'RUDO_TEST_CHROME' and name.startswith(('PGHOSTADDR','PGSERVICE','RUDO_','WHATSAPP_','META_','FIREBASE_','SUPABASE_','GOOGLE_APPLICATION_CREDENTIALS')):
            monkeypatch.delenv(name,raising=False)


@pytest.fixture
def database():
    # Only this disposable loopback database can be reset. Never reads linked config.
    with psycopg.connect(TEST_DSN,autocommit=True) as c:
        if c.execute("SELECT current_setting('rudo.synthetic_test_cluster',true)").fetchone()[0] != 'synthetic-only':
            raise RuntimeError('Refusing to reset a cluster without the synthetic-only marker')
        c.execute('DROP SCHEMA IF EXISTS rudo CASCADE')
        c.execute('DROP SCHEMA IF EXISTS rudo_local_migrations CASCADE')
    from rudo.synthetic import clear_source
    clear_source(TEST_DSN)
    apply(TEST_DSN)
    with psycopg.connect(TEST_DSN) as c:
        for subject,role,facilities,active in [
            ('operator','operator',['clinic-a'],True),('admin','admin',['clinic-a','clinic-b'],True),
            ('analyst','analyst',['clinic-a'],True),('disabled','operator',['clinic-a'],False)]:
            c.execute('INSERT INTO rudo.staff_memberships VALUES(%s,%s,%s,%s,%s)',
                      (ISSUER,subject,role,facilities,active))
        a,b=uuid4(),uuid4()
        for cid,facility,phone in [(a,'clinic-a','260000000001'),(b,'clinic-b','260000000002')]:
            c.execute('INSERT INTO rudo.conversations(id,account_id,phone,facility_id) VALUES(%s,%s,%s,%s)',
                      (cid,'synthetic-account',phone,facility))
        order=uuid4()
        c.execute('''INSERT INTO rudo.orders(id,facility_id,payload,status,created_at)
                     VALUES(%s,'clinic-a','{"product":"Synthetic product","price":"12.50","quantity":2}','pending','2026-01-01T00:00:00Z')''',(order,))
        for source in ['Mandebvu Clinic Poster 1','Mandebvu Clinic Poster 2',"N'gombe Clinic Flyer",'Unknown source']:
            c.execute('INSERT INTO rudo.referrals(id,facility_id,source) VALUES(%s,%s,%s)',(uuid4(),'clinic-a',source))
    db=Database(TEST_DSN,TEST_DSN)
    db.test_ids={'a':str(a),'b':str(b),'order':str(order)}
    return db


class SyntheticVerifier:
    calls=0
    def verify(self,token):
        self.calls+=1
        if token in ('expired','revoked','wrong-project','invalid'):
            raise ApiError(401,'invalid_identity')
        return {'subject':token,'issuer':ISSUER}


@pytest.fixture
def app(database):
    return create_app({'TESTING':True,'MODE':'private','FIREBASE_PROJECT_ID':'synthetic-test',
                       'META_APP_SECRET':'synthetic-secret','META_VERIFY_TOKEN':'synthetic-verify',
                       'WHATSAPP_PHONE_NUMBER_ID':'synthetic-account','FACILITY_ID':'clinic-a'},
                      database=database,verifier=SyntheticVerifier())


@pytest.fixture
def client(app):return app.test_client()


def headers(user='operator',**extra):return {'Authorization':'Bearer '+user,**extra}
