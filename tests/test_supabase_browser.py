"""Real browser -> Flask -> restricted PostgreSQL for Supabase staff sign-in, with an offline fake SDK."""
import base64,json,os,subprocess
from pathlib import Path
from uuid import uuid4
from app import create_app
from conftest import TEST_DSN
from rudo.synthetic import bootstrap,clear_source
from rudo.staff_migration import LinkStore
from test_identity_links import TwoProviders,SB_ISSUER,sid
from rudo.synthetic import ISSUER


def test_supabase_staff_sign_in_browser_flow():
    observer=bootstrap(TEST_DSN)
    linked,pending=str(uuid4()),str(uuid4())
    LinkStore(TEST_DSN).link(SB_ISSUER,linked,sid('operator'),'operator@example.test','synthetic-admin')
    app=create_app({'MODE':'observer','TESTING':True,'BROWSER_AUTH':'supabase','SUPABASE_URL':'https://synthetic-ref.supabase.co',
                    'SUPABASE_ANON_KEY':'sb_publishable_synthetic','SUPABASE_GOOGLE_ENABLED':True},
                   observer=observer,verifier=TwoProviders())
    env={**os.environ,'RUDO_LINKED_UUID':linked,'RUDO_PENDING_UUID':pending}
    proc=subprocess.Popen(['node','scripts/test_supabase_browser.mjs'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1,env=env)
    result=failure=None
    try:
        with app.test_client() as client:
            for line in proc.stdout:
                message=json.loads(line)
                if 'request' in message:
                    req=message['request'];headers={k:v for k,v in req['headers'].items() if k.lower() not in ('host','content-length')}
                    response=client.open(req['url'],method=req['method'],headers=headers,data=req['body'],base_url='http://127.0.0.1:5051')
                    reply={'id':message['id'],'status':response.status_code,'headers':dict(response.headers),'body':base64.b64encode(response.data).decode()}
                    proc.stdin.write(json.dumps(reply)+'\n');proc.stdin.flush()
                elif 'result' in message:result=message['result'];break
                elif 'failure' in message:failure=message;break
                else:raise AssertionError('Unexpected browser IPC')
        proc.wait(timeout=95)
        assert proc.returncode==0 and result is not None, str(failure)+proc.stderr.read()
        Path('.local/supabase-browser-results.json').write_text(json.dumps(result,indent=2)+'\n')
        assert result['passed']==14 and result['pageErrors']==[]
    finally:
        if proc.poll() is None:proc.kill();proc.wait()
        clear_source(TEST_DSN)
