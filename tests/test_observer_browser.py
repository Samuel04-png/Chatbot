"""Real frontend/backend/database integration, using IPC instead of any HTTP/provider network."""
import base64,json,subprocess
from pathlib import Path
import psycopg
from app import create_app
from conftest import TEST_DSN
from rudo.synthetic import bootstrap,clear_source,SyntheticVerifier,SyntheticBot,PHONES


def test_observer_browser_integrates_with_restricted_database():
    observer=bootstrap(TEST_DSN)
    app=create_app({'MODE':'observer','TESTING':True,'OBSERVER_SYNTHETIC_DEMO':True,
                    'ALLOWED_ORIGIN':'http://127.0.0.1:5051'},observer=observer,verifier=SyntheticVerifier())
    proc=subprocess.Popen(['node','scripts/test_observer_browser.mjs'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
    original=observer.dsn;result=None;failure=None
    try:
        with app.test_client() as client:
            for line in proc.stdout:
                message=json.loads(line)
                if 'request' in message:
                    req=message['request'];headers={k:v for k,v in req['headers'].items() if k.lower() not in ('host','content-length')}
                    response=client.open(req['url'],method=req['method'],headers=headers,data=req['body'],base_url='http://127.0.0.1:5051')
                    reply={'id':message['id'],'status':response.status_code,'headers':dict(response.headers),'body':base64.b64encode(response.data).decode()}
                elif 'control' in message:
                    action=message['control']
                    if action=='source_write':SyntheticBot().receive(PHONES['a'],'browser source update')
                    elif action=='bulk_history':
                        with psycopg.connect(TEST_DSN) as c:
                            for i in range(60):c.execute("INSERT INTO public.messages(phone,role,message) VALUES(%s,'user',%s)",(PHONES['a'],'Synthetic bulk '+str(i)))
                    elif action=='source_down':observer.dsn=''
                    elif action=='source_up':observer.dsn=original
                    elif action=='writer_during_outage':assert SyntheticBot().receive(PHONES['a'],'while observer is down')['send_count']==1
                    else:raise AssertionError('Unexpected fixture control')
                    reply={'id':message['id'],'ok':True}
                elif 'result' in message:result=message['result'];break
                elif 'failure' in message:failure=message;break
                else:raise AssertionError('Unexpected browser IPC')
                proc.stdin.write(json.dumps(reply)+'\n');proc.stdin.flush()
        proc.wait(timeout=65)
        assert proc.returncode==0 and result is not None, str(failure)+proc.stderr.read()
        Path('.local/observer-browser-results.json').write_text(json.dumps(result,indent=2)+'\n')
        assert result['passed']>=15 and result['pageErrors']==[]
    finally:
        if proc.poll() is None:proc.kill();proc.wait()
        clear_source(TEST_DSN)
