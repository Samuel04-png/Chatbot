"""Rudo staff application. No provider secrets in source; no implicit remote writes."""
from collections import defaultdict, deque
from datetime import datetime
from functools import wraps
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import threading
import time
from uuid import UUID, uuid4

from flask import Flask, abort, g, jsonify, redirect, request, send_from_directory
from werkzeug.exceptions import HTTPException

from rudo.auth import browser_auth_config, build_verifier
from rudo.db import Database
from rudo.errors import ApiError

ROOT = Path(__file__).resolve().parent
PAGES = {'index.html','index2.html','chats.html','orders.html','analytics.html','login.html',
         'register.html','profile.html','settings.html','forgot-password.html',
         'change-password.html','reset-password.html'}
STATUSES = {'pending','confirmed','completed','cancelled','paid','unpaid','collected','delivered'}
CLINICS = [{'name': name, 'color': color} for name,color in [
    ('Mandebvu Clinic','#09f128'),('Avondale Clinic','#0000FF'),('Mandebvu Pharmacy','#FFFF00'),
    ("N'gombe Clinic",'#FF5F15'),('Chelstone Clinic','#D3D3D3')]]


def create_app(config=None, database=None, verifier=None, observer=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(
        MAX_CONTENT_LENGTH=1024*1024,
        MODE=os.getenv('RUDO_MODE','observer'),
        OBSERVER_DATABASE_URL=os.getenv('RUDO_OBSERVER_DATABASE_URL',''),
        OBSERVER_AUDIT_DATABASE_URL=os.getenv('RUDO_OBSERVER_AUDIT_DATABASE_URL',''),
        OBSERVER_SOURCE_ID=os.getenv('RUDO_OBSERVER_SOURCE_ID',''),
        OBSERVER_SYNTHETIC_DEMO=False,
        FIREBASE_PROJECT_ID=os.getenv('FIREBASE_PROJECT_ID',''),
        # Staff identity: Firebase stays the default until Supabase Auth passes staging verification.
        IDENTITY_PROVIDERS=os.getenv('RUDO_IDENTITY_PROVIDERS','firebase'),
        BROWSER_AUTH=os.getenv('RUDO_BROWSER_AUTH','firebase'),
        SUPABASE_URL=os.getenv('SUPABASE_URL',''),
        SUPABASE_ANON_KEY=os.getenv('SUPABASE_ANON_KEY',''),
        SUPABASE_GOOGLE_ENABLED=os.getenv('SUPABASE_GOOGLE_ENABLED','false') == 'true',
        SUPABASE_SESSION_CHECK=os.getenv('RUDO_SUPABASE_SESSION_CHECK','true') != 'false',
        FIREBASE_CHECK_REVOKED=os.getenv('RUDO_FIREBASE_CHECK_REVOKED','true') != 'false',
        # Production observer: remote Supabase Postgres only with sslmode=verify-full.
        OBSERVER_ALLOW_REMOTE=os.getenv('RUDO_OBSERVER_ALLOW_REMOTE','false') == 'true',
        STAFF_ADMIN_DATABASE_URL=os.getenv('RUDO_STAFF_ADMIN_DATABASE_URL',''),
        CURSOR_SECRET=os.getenv('RUDO_CURSOR_SECRET',''),
        TRUST_PROXY=os.getenv('RUDO_TRUST_PROXY','false') == 'true',
        DATABASE_URL=os.getenv('RUDO_DATABASE_URL',''),
        WORKER_DATABASE_URL=os.getenv('RUDO_WORKER_DATABASE_URL',''),
        ENABLE_REMOTE_WRITES=os.getenv('RUDO_ENABLE_REMOTE_WRITES','false') == 'true',
        ALLOWED_ORIGIN=os.getenv('RUDO_ALLOWED_ORIGIN','http://127.0.0.1:5000'),
        META_APP_SECRET=os.getenv('META_APP_SECRET',''),
        META_VERIFY_TOKEN=os.getenv('META_VERIFY_TOKEN',''),
        WHATSAPP_PHONE_NUMBER_ID=os.getenv('WHATSAPP_PHONE_NUMBER_ID',''),
        FACILITY_ID=os.getenv('RUDO_FACILITY_ID',''),
    )
    if config:
        app.config.update(config)
    if app.config.get('TRUST_PROXY'):
        # Behind exactly one TLS-terminating proxy (the hosting platform's load balancer).
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    db = database or Database(app.config['DATABASE_URL'],app.config['WORKER_DATABASE_URL'],
                              app.config['ENABLE_REMOTE_WRITES'])
    identity_provider = verifier or build_verifier(app.config)
    auth_config = browser_auth_config(app.config)  # Fails startup if a privileged key would reach browsers.
    app.extensions['browser_auth'] = auth_config
    supabase_origin = ' ' + auth_config['supabase']['url'] if 'supabase' in auth_config else ''
    app.extensions['rudo_db'] = db
    rate_lock = threading.Lock()
    rates = defaultdict(deque)

    def authenticated(raw=True):
        def decorate(fn):
            @wraps(fn)
            def wrapped(*args, **kwargs):
                header = request.headers.get('Authorization','')
                if not header.startswith('Bearer ') or len(header) > 16384:
                    raise ApiError(401,'authentication_required')
                g.identity = identity_provider.verify(header[7:])
                g.staff = db.membership(g.identity)
                if raw and g.staff['role'] not in ('admin','operator'):
                    raise ApiError(403,'role_required')
                return fn(*args,**kwargs)
            return wrapped
        return decorate

    def rate_limit():
        key = (g.identity['issuer'],g.identity['subject'])
        now = time.monotonic()
        with rate_lock:
            # Bound memory; retain only recent senders.
            for old in list(rates):
                if not rates[old] or rates[old][-1] < now-60:
                    del rates[old]
            if key not in rates and len(rates) >= 10000:
                raise ApiError(429,'rate_limited')
            bucket = rates[key]
            while bucket and bucket[0] < now-60:
                bucket.popleft()
            if len(bucket) >= 20:
                raise ApiError(429,'rate_limited')
            bucket.append(now)

    @app.before_request
    def request_context():
        g.request_id = str(uuid4())
        g.started = time.monotonic()
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin = request.headers.get('Origin')
            if origin and origin != app.config['ALLOWED_ORIGIN']:
                raise ApiError(403,'origin_denied')

    @app.after_request
    def privacy_headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Request-ID'] = g.get('request_id','')
        if request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        # Monitoring line: route TEMPLATE only (never the URL, query, conversation reference, token or body).
        rule = request.url_rule.rule if request.url_rule else 'unmatched'
        elapsed = (time.monotonic() - g.get('started', time.monotonic())) * 1000
        app.logger.info('request method=%s route=%s status=%s ms=%.0f request_id=%s',
                        request.method, rule, response.status_code, elapsed, g.get('request_id', ''))
        # Inline scripts are retained for compatibility; no unsafe-eval or arbitrary connections.
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://www.gstatic.com https://apis.google.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; font-src 'self' https://cdnjs.cloudflare.com data:; "
            "img-src 'self' data: https://*.googleusercontent.com; connect-src 'self' https://*.googleapis.com https://*.firebaseapp.com https://securetoken.googleapis.com" + supabase_origin + "; "
            "frame-src https://*.firebaseapp.com https://accounts.google.com; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        return response

    @app.errorhandler(ApiError)
    def api_error(exc):
        return jsonify(error=exc.code,requestId=g.get('request_id')),exc.status

    @app.errorhandler(Exception)
    def unexpected(exc):
        if isinstance(exc,HTTPException):
            return jsonify(error=exc.name.lower().replace(' ','_'),requestId=g.get('request_id')),exc.code
        # Do not log exception strings, provider bodies, DSNs, tokens or tracebacks.
        app.logger.error('request_failed request_id=%s exception_type=%s',g.get('request_id'),type(exc).__name__)
        return jsonify(error='service_unavailable',requestId=g.get('request_id')),503

    if app.config['MODE'] == 'observer':
        from rudo.observer_api import register_observer
        register_observer(app,identity_provider,observer)
        return app
    if app.config['MODE'] != 'private':
        raise ValueError('Unsupported application mode')

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value,dict):
            raise ApiError(400,'invalid_json')
        return value

    def identifier(value):
        try:
            return UUID(str(value))
        except (ValueError,TypeError):
            raise ApiError(400,'invalid_identifier') from None

    def page():
        try:
            limit = int(request.args.get('limit',100))
            offset = int(request.args.get('offset',0))
            if not 1 <= limit <= 100 or not 0 <= offset <= 1000000:
                raise ValueError()
            return limit,offset
        except ValueError:
            raise ApiError(400,'invalid_pagination') from None

    def encode(value):
        if isinstance(value,dict):return {k:encode(v) for k,v in value.items()}
        if isinstance(value,list):return [encode(v) for v in value]
        if isinstance(value,UUID):return str(value)
        if isinstance(value,datetime):return value.isoformat()
        return value

    def version(value):
        if type(value) is not int or value < 1:
            raise ApiError(400,'version_required')
        return value

    @app.get('/api/me')
    @authenticated(raw=False)
    def me():
        return jsonify(subject=g.identity['subject'],role=g.staff['role'],facilities=g.staff['facilities'])

    @app.get('/api/conversations')
    @authenticated()
    def conversations():
        limit,offset = page()
        return jsonify(items=encode(db.conversations(g.identity,limit,offset)),limit=limit,offset=offset)

    @app.post('/api/conversations')
    @authenticated()
    def open_conversation():
        value=body()
        phone=value.get('phone','')
        if not isinstance(phone,str) or not re.fullmatch(r'\+?[1-9][0-9]{9,14}',phone):
            raise ApiError(400,'international_phone_required')
        facility=value.get('facilityId')
        if facility not in g.staff['facilities']:
            raise ApiError(403,'scope_required')
        account=app.config['WHATSAPP_PHONE_NUMBER_ID']
        if not account:
            raise ApiError(503,'messaging_account_unconfigured')
        row=db.create_conversation(g.identity,phone.lstrip('+'),account,facility)
        return jsonify(encode(row)),201

    @app.get('/api/conversations/<conversation_id>')
    @authenticated()
    def thread(conversation_id):
        return jsonify(encode(db.conversation(g.identity,identifier(conversation_id))))

    @app.patch('/api/conversations/<conversation_id>')
    @authenticated()
    def resolve(conversation_id):
        value=body()
        if value.get('status') not in ('active','closed'):
            raise ApiError(400,'invalid_status')
        return jsonify(encode(db.change_status(g.identity,'conversations',identifier(conversation_id),
                                               value['status'],version(value.get('version')))))

    @app.post('/api/conversations/<conversation_id>/messages')
    @authenticated()
    def send(conversation_id):
        rate_limit()
        value=body()
        text=value.get('message')
        if not isinstance(text,str) or not 1 <= len(text.strip()) <= 4096:
            raise ApiError(400,'invalid_message')
        operation=identifier(request.headers.get('Idempotency-Key'))
        row=db.enqueue(g.identity,identifier(conversation_id),text.strip(),operation)
        return jsonify(id=str(row['id']),status=row['status']),202

    @app.post('/sendWhatsApp')
    @authenticated()
    def old_send():
        # Legacy arbitrary-recipient sending cannot bypass scoped conversation operations.
        raise ApiError(410,'use_conversation_message_api')

    @app.get('/api/orders')
    @authenticated()
    def orders():
        limit,offset=page()
        return jsonify(items=encode(db.orders(g.identity,limit,offset)),limit=limit,offset=offset)

    @app.patch('/api/orders/<order_id>')
    @authenticated()
    def update_order(order_id):
        value=body()
        if value.get('status') not in STATUSES:
            raise ApiError(400,'invalid_status')
        return jsonify(encode(db.change_status(g.identity,'orders',identifier(order_id),value['status'],
                                               version(value.get('version')))))

    @app.get('/api/referrals')
    @authenticated()
    def referrals():
        limit,offset=page()
        return jsonify(items=encode(db.referrals(g.identity,limit,offset)),limit=limit,offset=offset)

    @app.get('/api/analytics')
    @authenticated(raw=False)
    def analytics():
        return jsonify(db.analytics(g.identity))

    @app.get('/api/qr-analytics')
    @authenticated()
    def qr_analytics():
        # Explicit completeness guard; UI never displays a partial tally as complete.
        rows=db.referrals(g.identity,10001,0)
        if len(rows)>10000:
            raise ApiError(422,'analytics_requires_aggregation')
        sources=['Poster 1','Poster 2','Flyer']
        counts={clinic['name']:{s:0 for s in sources} for clinic in CLINICS}
        matched=0
        for row in rows:
            source=row['source']
            for clinic in CLINICS:
                if clinic['name'].lower() in source.lower():
                    for name,pattern in [('Poster 1',r'poster\s*1'),('Poster 2',r'poster\s*2'),('Flyer',r'flyer')]:
                        if re.search(pattern,source,re.I):
                            counts[clinic['name']][name]+=1
                            matched+=1
                            break
                    break
        return jsonify(ok=True,clinics=CLINICS,sources=sources,counts=counts,totalRecords=len(rows),
                       validRecords=len(rows),malformedRecords=0,matchedRecords=matched,cached=False)

    @app.route('/webhook',methods=['GET','POST'])
    def webhook():
        if request.method=='GET':
            configured=app.config['META_VERIFY_TOKEN']
            if (not configured or request.args.get('hub.mode')!='subscribe'
                    or not hmac.compare_digest(request.args.get('hub.verify_token',''),configured)
                    or not request.args.get('hub.challenge')):
                raise ApiError(403,'verification_denied')
            return request.args['hub.challenge'],200,{'Content-Type':'text/plain'}
        secret=app.config['META_APP_SECRET']
        if not secret:
            raise ApiError(503,'webhook_unconfigured')
        raw=request.get_data()
        expected='sha256='+hmac.new(secret.encode(),raw,hashlib.sha256).hexdigest()
        supplied=request.headers.get('X-Hub-Signature-256','')
        if not re.fullmatch(r'sha256=[0-9a-f]{64}',supplied) or not hmac.compare_digest(supplied,expected):
            raise ApiError(403,'invalid_signature')
        value=body()
        if value.get('object')!='whatsapp_business_account' or not isinstance(value.get('entry'),list):
            raise ApiError(400,'invalid_webhook')
        for entry in value['entry']:
            if not isinstance(entry,dict) or not isinstance(entry.get('changes'),list):
                raise ApiError(400,'invalid_webhook')
            for change in entry['changes']:
                if not isinstance(change,dict) or not isinstance(change.get('value'),dict):
                    raise ApiError(400,'invalid_webhook')
                for field in ('messages','statuses'):
                    if field in change['value'] and not isinstance(change['value'][field],list):
                        raise ApiError(400,'invalid_webhook')
        account=app.config['WHATSAPP_PHONE_NUMBER_ID']
        facility=app.config['FACILITY_ID']
        if not account or not facility:
            raise ApiError(503,'webhook_unconfigured')
        accepted=db.accept_webhook(value,account,facility)
        return jsonify(status='accepted',events=accepted)

    @app.get('/')
    def index():return redirect('index2.html')

    @app.get('/<page_name>.html')
    def html(page_name):
        filename=page_name+'.html'
        if filename not in PAGES:abort(404)
        return send_from_directory(ROOT,filename)

    @app.get('/<asset>/<path:filename>')
    def asset(asset,filename):
        if asset not in ('css','js','img'):abort(404)
        return send_from_directory(ROOT/asset,filename)

    return app


app=create_app()

if __name__=='__main__':
    app.run(host='127.0.0.1',port=5000,debug=False)
