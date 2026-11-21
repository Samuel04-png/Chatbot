"""Candidate-only comparison: exact pinned helper definitions, stubbed answer/Meta; no deployed AI claim."""
from pathlib import Path
from types import SimpleNamespace
import hashlib,json
import psycopg
from conftest import TEST_DSN
from rudo.synthetic import bootstrap,clear_source,snapshot,PHONES,ISSUER,SOURCE
from rudo.observer import reference


def test_pinned_candidate_helper_contract_observer_on_off():
    root=Path(__file__).parent/'fixtures'
    metadata=json.loads((root/'candidate_provenance.json').read_text())
    excerpt=(root/'candidate_contract.py').read_text()
    assert hashlib.sha256(excerpt.encode()).hexdigest()==metadata['excerpt_sha256']
    outcomes=[]
    try:
        for enabled in (False,True):
            observer=bootstrap(TEST_DSN);sent=[]
            def add_message(phone,role,message,message_en=None):
                with psycopg.connect(TEST_DSN) as c:c.execute('INSERT INTO public.messages(phone,role,message,message_en) VALUES(%s,%s,%s,%s)',(phone,role,message,message_en))
            def get_history(phone):
                with psycopg.connect(TEST_DSN) as c:rows=c.execute('SELECT role,message,message_en FROM public.messages WHERE phone=%s ORDER BY id',(phone,)).fetchall()
                return [dict(zip(('role','message','message_en'),row)) for row in rows]
            def fake_post(url,headers,json,timeout):
                sent.append({'url':url,'payload':json,'timeout':timeout})
                return SimpleNamespace(status_code=200,text='synthetic')
            ns={'requests':SimpleNamespace(post=fake_post),'logging':SimpleNamespace(info=lambda *a:None,error=lambda *a:None),
                'json':json,'WHATSAPP_MAX_CHARS':3800,'HISTORY_ENTRIES_FOR_MODEL':12,'wa_token':'synthetic-not-a-provider-secret',
                'AGENT_PHONES_NORM':set(),'normalize_phone':lambda p:p.lstrip('+'),'get_user_conversation':get_history,
                'db':SimpleNamespace(add_message=add_message)}
            exec(compile(excerpt,'candidate_contract.py','exec'),ns)
            ns['send']('Synthetic candidate-only fixed answer with enough context',PHONES['a'],'synthetic-account',message_en='Synthetic English answer')
            before=snapshot()
            if enabled:
                who={'issuer':ISSUER,'subject':'operator'}
                observer.conversations(who);observer.history(who,reference(SOURCE,PHONES['a']));observer.analytics(who)
            assert snapshot()==before
            history=ns['_history_for_model'](PHONES['a'],'english')
            outcomes.append({'requests':sent,'model_context':ns['pairs_from_history'](history),'history':get_history(PHONES['a'])})
        assert outcomes[0]==outcomes[1]
    finally:clear_source(TEST_DSN)
