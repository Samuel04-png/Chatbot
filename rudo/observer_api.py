"""Observer-only HTTP surface. No mutation, webhook ingestion, state merge or transport."""
import json
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Blueprint,Response,abort,g,jsonify,redirect,request,send_from_directory
from .errors import ApiError
from .observer import AccessAudit,Observer,StaffAdmin


FIREBASE_APP='<script src="https://www.gstatic.com/firebasejs/9.6.0/firebase-app-compat.js"></script>'
FIREBASE_AUTH='<script src="https://www.gstatic.com/firebasejs/9.6.0/firebase-auth-compat.js"></script>'
# Pinned exact version. Add a Subresource Integrity hash before production (see auth-migration README).
SUPABASE_SDK='<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.js"></script>'


def register_observer(app, verifier, adapter=None):
    api=Blueprint('observer',__name__)
    root=Path(__file__).resolve().parents[1]
    remote=app.config.get('OBSERVER_ALLOW_REMOTE',False)
    secret=app.config.get('CURSOR_SECRET') or ''
    if remote and len(secret)<32:
        # Pagination cursors must verify across every worker/instance in production.
        raise ValueError('RUDO_CURSOR_SECRET (32+ characters) is required with RUDO_OBSERVER_ALLOW_REMOTE')
    audit=AccessAudit(app.config['OBSERVER_AUDIT_DATABASE_URL'],allow_remote=remote)
    observer=adapter or Observer(app.config['OBSERVER_DATABASE_URL'],audit,app.config['OBSERVER_SOURCE_ID'],
                                 cursor_secret=secret.encode() or None,allow_remote=remote)
    staff_admin=app.config.get('STAFF_ADMIN') or StaffAdmin(app.config.get('STAFF_ADMIN_DATABASE_URL',''),
                                                           getattr(observer,'audit',audit),getattr(observer,'source_id',''),allow_remote=remote)
    app.extensions['observer']=observer

    @app.before_request
    def readonly_boundary():
        if request.path.rstrip('/') in ('/webhook','/sendWhatsApp'):
            raise ApiError(405,'observer_read_only')
        if request.path.startswith('/api/') and request.method not in ('GET','HEAD','OPTIONS'):
            # Only staff administration may write, and only to observer_control through admin-checked
            # database functions. Patient/bot data has no write path at all.
            if not (request.path.startswith('/api/admin/') and request.method=='POST'):
                raise ApiError(405,'observer_read_only')
            if not request.is_json:raise ApiError(415,'json_required')

    def authenticated(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            header=request.headers.get('Authorization','')
            if not header.startswith('Bearer ') or not header[7:] or len(header)>16384:
                raise ApiError(401,'authentication_required')
            g.identity=verifier.verify(header[7:])
            return fn(*args,**kwargs)
        return wrapped

    def encode(value):
        if isinstance(value,datetime):return value.isoformat()
        if isinstance(value,list):return [encode(v) for v in value]
        if isinstance(value,dict):return {k:encode(v) for k,v in value.items()}
        return value

    def options(default=25):
        if 'offset' in request.args:raise ApiError(400,'keyset_cursor_required')
        try:
            limit=int(request.args.get('limit',default))
            if not 1<=limit<=100:raise ValueError()
        except (ValueError,TypeError):raise ApiError(400,'invalid_pagination') from None
        cursor=request.args.get('cursor')
        if cursor and len(cursor)>4096:raise ApiError(400,'invalid_cursor')
        return {'limit':limit,'cursor':cursor}

    def scopes():
        account=request.args.get('account') or None;facility=request.args.get('facility') or None
        if any(v is not None and len(v)>128 for v in (account,facility)):raise ApiError(400,'invalid_scope')
        return {'account':account,'facility':facility}

    @api.get('/api/auth-config')
    def auth_config():
        # Public, browser-safe values only (validated at startup): provider, project URL, anon key.
        return jsonify(app.extensions['browser_auth'])

    @api.get('/api/me')
    @authenticated
    def me():return jsonify(observer.membership(g.identity))

    @api.get('/api/conversations')
    @authenticated
    def conversations():
        query=request.args.get('q','').strip();kind=request.args.get('filter','all')
        if len(query)>100 or kind not in ('all','with_messages','without_messages'):raise ApiError(400,'invalid_filter')
        return jsonify(encode(observer.conversations(g.identity,**options(),**scopes(),query=query,kind=kind)))

    @api.get('/api/conversations/<conversation_id>')
    @authenticated
    def history(conversation_id):return jsonify(encode(observer.history(g.identity,conversation_id,**options(50))))

    @api.get('/api/orders')
    @authenticated
    def orders():
        status=request.args.get('status') or None
        if status and len(status)>100:raise ApiError(400,'invalid_filter')
        return jsonify(encode(observer.records(g.identity,'orders',**options(),**scopes(),status=status)))

    @api.get('/api/referrals')
    @authenticated
    def referrals():return jsonify(encode(observer.records(g.identity,'referrals',**options(),**scopes())))

    @api.get('/api/analytics')
    @authenticated
    def analytics():return jsonify(observer.analytics(g.identity,**scopes()))

    def body():
        value=request.get_json(silent=True)
        if not isinstance(value,dict):raise ApiError(400,'invalid_json')
        return value

    def text_field(value,name,limit=254,required=True):
        if value is None and not required:return None
        if not isinstance(value,str) or not value.strip() or len(value)>limit:raise ApiError(400,'invalid_'+name)
        return value.strip()

    def scope_list(value):
        if value is None:return None
        if not isinstance(value,list) or len(value)>100 or not all(
                isinstance(v,dict) and set(v)=={'account','facility'} and all(isinstance(x,str) and 0<len(x)<=64 for x in v.values()) for v in value):
            raise ApiError(400,'invalid_scopes')
        return json.dumps(value)

    @api.get('/api/admin/overview')
    @authenticated
    def admin_overview():return jsonify(staff_admin.call(g.identity,'overview'))

    @api.post('/api/admin/invitations')
    @authenticated
    def admin_invite():
        data=body()
        staff=data.get('staffId')
        role=None if staff else text_field(data.get('role'),'role',20)
        return jsonify(id=staff_admin.call(g.identity,'invite',text_field(data.get('email'),'email').lower(),role,
                                           scope_list(data.get('scopes') or []),staff and text_field(staff,'staff',64))),201

    @api.post('/api/admin/invitations/<invitation>/approve')
    @authenticated
    def admin_approve(invitation):
        data=body()
        return jsonify(staffId=staff_admin.call(g.identity,'approve',invitation,text_field(data.get('issuer'),'issuer',300),
                                                text_field(data.get('subject'),'subject',200)))

    @api.post('/api/admin/invitations/<invitation>/revoke')
    @authenticated
    def admin_revoke(invitation):
        staff_admin.call(g.identity,'revoke_invitation',invitation);return jsonify(ok=True)

    @api.post('/api/admin/staff/<staff>')
    @authenticated
    def admin_update(staff):
        data=body()
        if not {'role','status','scopes'}&set(data):raise ApiError(400,'nothing_to_change')
        staff_admin.call(g.identity,'update',staff,text_field(data.get('role'),'role',20,False),
                         text_field(data.get('status'),'status',20,False),scope_list(data.get('scopes')))
        return jsonify(ok=True)

    @api.post('/api/admin/identities/unlink')
    @authenticated
    def admin_unlink():
        data=body()
        staff_admin.call(g.identity,'unlink',text_field(data.get('issuer'),'issuer',300),text_field(data.get('subject'),'subject',200))
        return jsonify(ok=True)

    @api.post('/api/admin/requests/dismiss')
    @authenticated
    def admin_dismiss():
        data=body()
        staff_admin.call(g.identity,'dismiss',text_field(data.get('issuer'),'issuer',300),text_field(data.get('subject'),'subject',200))
        return jsonify(ok=True)

    @api.get('/healthz')
    def health():return jsonify(status='ok')

    @api.get('/readyz')
    def ready():
        # Database reachability under the restricted roles, without any staff identity or patient row.
        try:
            from .observer import connect
            with connect(observer.dsn,remote,'rudo_observer') as conn:conn.execute('SELECT 1')
            with connect(getattr(observer,'audit',audit).dsn,remote,'rudo_observer_audit') as conn:conn.execute('SELECT 1')
        except Exception:
            return jsonify(status='unavailable'),503
        return jsonify(status='ready')

    @api.get('/')
    def index():return redirect('observer.html')

    def render(name):
        content=(root/name).read_text()
        if app.extensions['browser_auth']['provider']=='supabase' and not app.config.get('OBSERVER_SYNTHETIC_DEMO'):
            content=content.replace(FIREBASE_APP,SUPABASE_SDK).replace(FIREBASE_AUTH,'')
            content=content.replace('<script defer src="js/rudo-auth.js"></script>','<script defer src="js/rudo-supabase-auth.js"></script>')
        if app.config.get('OBSERVER_SYNTHETIC_DEMO'):
            # Only the explicit loopback demo entrypoint injects this offline identity provider.
            content=content.replace(FIREBASE_APP,'<script src="js/observer-demo-auth.js"></script>').replace(FIREBASE_AUTH,'')
            content=content.replace('data-environment="configured-source"','data-environment="synthetic-local"')
        return Response(content,mimetype='text/html')

    @api.get('/<page>.html')
    def page(page):
        if page in ('observer','index','index2','chats','orders','referrals','analytics'):return render('observer.html')
        if page=='staff':return render('staff.html')
        if page in ('staff-login','staff-reset'):
            return send_from_directory(root,page+'.html')
        if page in ('login','forgot-password','reset-password','register'):
            if app.config.get('OBSERVER_SYNTHETIC_DEMO'):
                return Response('<!doctype html><title>Synthetic Rudo demo</title><h1>Signed out of the synthetic demo</h1><p>No external identity provider is connected.</p><a href="observer.html">Return to synthetic observer</a>',mimetype='text/html')
            return send_from_directory(root,page+'.html')
        abort(404)

    @api.get('/<asset>/<path:filename>')
    def asset(asset,filename):
        if asset not in ('css','js','img'):abort(404)
        if Path(filename).name=='observer-demo-auth.js' and not app.config.get('OBSERVER_SYNTHETIC_DEMO'):abort(404)
        return send_from_directory(root/asset,filename)

    app.register_blueprint(api)
