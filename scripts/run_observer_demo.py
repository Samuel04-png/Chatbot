"""Explicit local-only authenticated synthetic demo. No real Firebase/Meta/model credentials."""
from pathlib import Path
import sys,logging
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rudo.synthetic import adapter,admin_dsn,assert_disposable,LOCAL_DSN,SyntheticVerifier
from app import create_app

def demo_app():
    assert_disposable(LOCAL_DSN)
    return create_app({'MODE':'observer','OBSERVER_SYNTHETIC_DEMO':True,'FIREBASE_PROJECT_ID':'synthetic-test',
                       'ALLOWED_ORIGIN':'http://127.0.0.1:5051','STAFF_ADMIN_DATABASE_URL':admin_dsn()},observer=adapter(),verifier=SyntheticVerifier())

if __name__=='__main__':
    logging.getLogger('werkzeug').disabled=True  # Do not log identifier-bearing request URLs.
    demo_app().run(host='127.0.0.1',port=5051,debug=False)
