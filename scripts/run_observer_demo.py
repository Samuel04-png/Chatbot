"""Explicit local-only authenticated synthetic demo. No real Firebase/Supabase/Meta/model credentials.
Everything runs against the marked disposable loopback database; WhatsApp sending is a no-network stand-in."""
from pathlib import Path
import sys,logging
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from rudo.synthetic import (adapter,admin_dsn,assert_disposable,sender_dsn,LOCAL_DSN,SOURCE,SyntheticSender,SyntheticVerifier,
                            open_reply_window)
from rudo.replies import StaffReplies
from app import create_app

PORT=5051


def demo_app():
    assert_disposable(LOCAL_DSN)
    replies=StaffReplies(sender_dsn(),SOURCE,SyntheticSender(),enabled=True)  # Never reaches WhatsApp.
    return create_app({'MODE':'observer','OBSERVER_SYNTHETIC_DEMO':True,'FIREBASE_PROJECT_ID':'synthetic-test',
                       'ALLOWED_ORIGIN':f'http://127.0.0.1:{PORT}','STAFF_ADMIN_DATABASE_URL':admin_dsn(),'STAFF_REPLIES':replies},
                      observer=adapter(),verifier=SyntheticVerifier())

if __name__=='__main__':
    logging.getLogger('werkzeug').disabled=True  # Do not log identifier-bearing request URLs.
    if '--open-reply-window' in sys.argv:
        open_reply_window()
    app=demo_app()
    print(f'\nRudo SYNTHETIC DEMO running: open http://127.0.0.1:{PORT}/observer.html  (Ctrl+C to stop)\n'
          'No real patients, no Supabase/Firebase login, no WhatsApp sending.\n',flush=True)
    app.run(host='127.0.0.1',port=PORT,debug=False)
