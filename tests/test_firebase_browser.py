"""Release 1 path in a real browser: Firebase pages (offline fake SDK) -> Flask -> restricted PostgreSQL,
including staff invitation and approval through the real staff page and rudo_staff_admin login."""
import base64,json,subprocess
from pathlib import Path
from app import create_app
from conftest import TEST_DSN
from rudo.synthetic import SyntheticVerifier,admin_dsn,bootstrap,clear_source


def drive(app,script,env=None):
    proc=subprocess.Popen(['node',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1,env=env)
    result=failure=None
    try:
        with app.test_client() as client:
            for line in proc.stdout:
                message=json.loads(line)
                if 'request' in message:
                    req=message['request'];headers={k:v for k,v in req['headers'].items() if k.lower() not in ('host','content-length')}
                    response=client.open(req['url'],method=req['method'],headers=headers,data=req['body'],base_url='http://127.0.0.1:5051')
                    try:
                        proc.stdin.write(json.dumps({'id':message['id'],'status':response.status_code,'headers':dict(response.headers),
                                                     'body':base64.b64encode(response.data).decode()})+'\n');proc.stdin.flush()
                    except BrokenPipeError:
                        continue  # The script already finished; keep reading for its result/failure line.
                elif 'result' in message:result=message['result'];break
                elif 'failure' in message:failure=message;break
                else:raise AssertionError('Unexpected browser IPC')
        proc.wait(timeout=125)
        assert proc.returncode==0 and result is not None,str(failure)+proc.stderr.read()
        return result
    finally:
        if proc.poll() is None:proc.kill();proc.wait()


def test_firebase_sign_in_staff_invitation_and_approval_in_browser():
    observer=bootstrap(TEST_DSN)
    try:
        app=create_app({'MODE':'observer','TESTING':True,'FIREBASE_PROJECT_ID':'dawa-ca263','STAFF_ADMIN_DATABASE_URL':admin_dsn(TEST_DSN),'ALLOWED_ORIGIN':'http://127.0.0.1:5051'},
                       observer=observer,verifier=SyntheticVerifier())
        result=drive(app,'scripts/test_firebase_browser.mjs')
        Path('.local/firebase-browser-results.json').write_text(json.dumps(result,indent=2)+'\n')
        assert result['passed']==11 and result['pageErrors']==[]
    finally:
        clear_source(TEST_DSN)
