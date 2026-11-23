"""Read-only source projections. No CLI credentials, source writes, state reads or business replicas."""
from contextlib import contextmanager
import base64
import hashlib
import hmac
import json
import secrets
import threading

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool,PoolTimeout

from .db import Database
from .errors import ApiError

HISTORY_NOTICE = 'Captured bot history may omit WhatsApp interactions. Delivery and provider identifiers are unknown.'


def reference(source, phone):
    return base64.urlsafe_b64encode(json.dumps([source,phone],separators=(',',':')).encode()).decode().rstrip('=')


def parse_reference(value, source):
    try:
        if not isinstance(value,str) or len(value)>1024:raise ValueError()
        result=json.loads(base64.b64decode(value+'='*((-len(value))%4),altchars=b'-_',validate=True))
        if not isinstance(result,list) or len(result)!=2 or result[0]!=source or not isinstance(result[1],str) or len(result[1])>128:
            raise ValueError()
        return result[1]
    except (ValueError,TypeError,UnicodeError):
        raise ApiError(400,'invalid_conversation_reference') from None


def set_context(conn,identity,source,*prefix):
    """Transaction-local verified identity (database functions resolve it to the internal staff id), sent in ONE
    round trip together with any fixed prefix statements. Values are quoted client-side by psycopg.sql."""
    values=[sql.Literal(v) for v in (identity['issuer'],identity['subject'],source)]
    statement=sql.SQL("SELECT set_config('observer.issuer',{},true),set_config('observer.subject',{},true),"
                      "set_config('observer.source',{},true)").format(*values)
    conn.execute(sql.SQL('; ').join([sql.SQL(p) for p in prefix]+[statement]))


ROLE_ERRORS={'rudo_observer':'observer_role_required','rudo_observer_audit':'audit_role_required'}
_pools={}
_pools_lock=threading.Lock()


def _pool(dsn,expected_role,dict_rows,autocommit=False):
    """One small pool per (login, row format) and process. Created only after a direct check that the DSN
    logs in as exactly the expected restricted role, so a wrong (e.g. privileged) login is never pooled."""
    key=(dsn,expected_role,dict_rows,autocommit)
    with _pools_lock:
        pool=_pools.get(key)
        if pool is None:
            with psycopg.connect(dsn,connect_timeout=10,prepare_threshold=None) as probe:
                if probe.execute('SELECT current_user').fetchone()[0]!=expected_role:
                    raise ApiError(503,ROLE_ERRORS.get(expected_role,'staff_admin_role_required'))
            kwargs={'connect_timeout':10,'prepare_threshold':None,'autocommit':autocommit,
                    **({'row_factory':dict_row} if dict_rows else {})}
            # No per-checkout probe (one round trip each); broken connections are discarded by the pool and
            # idle ones recycled after max_idle.
            pool=ConnectionPool(dsn,min_size=2,max_size=6,kwargs=kwargs,timeout=20,max_idle=240,max_lifetime=1800,
                                name=expected_role,open=True)
            _pools[key]=pool
        return pool


@contextmanager
def connect(dsn,allow_remote,expected_role,row_factory=None,autocommit=False):
    """Pooled connection: loopback, or remote only with sslmode=verify-full; refuses any login other than the
    expected role. Each use is its own transaction (committed or rolled back before the connection is reused);
    request identity is set with transaction-local settings, so nothing carries over between requests."""
    Database(allow_remote=allow_remote).check_target(dsn)
    try:
        pool=_pool(dsn,expected_role,row_factory is dict_row,autocommit)
    except psycopg.OperationalError:
        raise ApiError(503,'database_unavailable') from None
    try:
        with pool.connection() as conn:
            yield conn
    except PoolTimeout:
        raise ApiError(503,'database_unavailable') from None
    except psycopg.OperationalError:
        # Connections can die while idle (e.g. the host slept or the pooler recycled them). Sweep the idle
        # ones now so the next request gets a live connection instead of another dead one.
        try:
            pool.check()
        except Exception:
            pass
        raise ApiError(503,'database_unavailable') from None


class AccessAudit:
    def __init__(self,dsn,allow_remote=False):self.dsn,self.allow_remote=dsn,allow_remote

    def append(self,identity,source,action,count,resource=None):
        with connect(self.dsn,self.allow_remote,'rudo_observer_audit',autocommit=True) as conn:
            conn.execute('''INSERT INTO observer_control.access_audit
              (issuer,subject,source_id,action,resource_digest,rows_returned) VALUES(%s,%s,%s,%s,%s,%s)''',
                         (identity['issuer'],identity['subject'],source,action,
                          hashlib.sha256(resource.encode()).hexdigest() if resource else None,count))

    def record_request(self,identity):
        """A verified sign-in without a staff link becomes visible to admins as pending. Grants nothing."""
        with connect(self.dsn,self.allow_remote,'rudo_observer_audit',autocommit=True) as conn:
            conn.execute('SELECT observer_control.record_identity_request(%s,%s,%s,%s,%s)',
                         (identity['issuer'],identity['subject'],identity.get('provider','firebase'),
                          identity.get('email'),bool(identity.get('email_verified'))))


class Observer:
    def __init__(self,dsn,audit,source_id,cursor_secret=None,allow_remote=False,replies=False):
        self.dsn,self.audit,self.source_id,self.allow_remote=dsn,audit,source_id,allow_remote
        self.replies=replies  # True once the staff-replies migration is installed and replies are enabled.
        self.cursor_secret=cursor_secret or secrets.token_bytes(32)

    @contextmanager
    def read(self,identity,raw=True,account=None,facility=None):
        if not self.source_id:raise ApiError(503,'observer_unconfigured')
        with connect(self.dsn,self.allow_remote,'rudo_observer',row_factory=dict_row) as conn:
            set_context(conn,identity,self.source_id,'SET TRANSACTION READ ONLY',"SET LOCAL statement_timeout='5s'")
            staff=conn.execute('SELECT id,role,display_name,email FROM observer_control.staff').fetchone()
            if not staff:
                try:self.audit.record_request(identity)
                except Exception:pass  # Recording a pending sign-in must never grant or block anything.
                raise ApiError(403,'staff_required')
            if raw and staff['role'] not in ('operator','admin'):raise ApiError(403,'role_required')
            scopes=conn.execute('''SELECT s.source_id,s.account_id,s.facility_id,f.display_name AS facility_name
                                   FROM observer_control.staff_scopes s JOIN observer_control.facilities f USING(source_id,account_id,facility_id)
                                   WHERE s.source_id=%s AND f.active ORDER BY s.account_id,s.facility_id''',(self.source_id,)).fetchall()
            if (account or facility) and not any((not account or s['account_id']==account) and (not facility or s['facility_id']==facility) for s in scopes):
                raise ApiError(403,'scope_required')
            yield conn,{'role':staff['role'],'staffId':str(staff['id']),'displayName':staff['display_name'],
                        'email':staff['email'],'scopes':scopes}

    def _context(self,identity,action,filters):
        return hashlib.sha256(json.dumps([identity,self.source_id,action,filters],sort_keys=True).encode()).hexdigest()

    def _cursor(self,context,last,anchor=None):
        raw=json.dumps({'v':1,'context':context,'last':last,'anchor':anchor},separators=(',',':')).encode()
        signature=hmac.new(self.cursor_secret,raw,hashlib.sha256).digest()
        return base64.urlsafe_b64encode(signature+raw).decode().rstrip('=')

    def _decode(self,value,context):
        if not value:return None,None
        try:
            if len(value)>4096:raise ValueError()
            data=base64.b64decode(value+'='*((-len(value))%4),altchars=b'-_',validate=True)
            signature,raw=data[:32],data[32:]
            if not hmac.compare_digest(signature,hmac.new(self.cursor_secret,raw,hashlib.sha256).digest()):raise ValueError()
            parsed=json.loads(raw)
            if parsed.get('v')!=1 or parsed.get('context')!=context:raise ValueError()
            return parsed['last'],parsed['anchor']
        except (ValueError,TypeError,KeyError,UnicodeError):raise ApiError(400,'invalid_cursor') from None

    def _record(self,identity,action,count,resource=None):
        try:self.audit.append(identity,self.source_id,action,count,resource)
        except Exception:raise ApiError(503,'audit_unavailable') from None

    def membership(self,identity):
        with self.read(identity,raw=False) as (_,member):pass
        self._record(identity,'membership',0)
        return {'subject':identity['subject'],'provider':identity.get('provider'),**member,
                'mode':'observer','readOnly':True,'sourceId':self.source_id}

    def conversations(self,identity,limit=25,cursor=None,query='',kind='all',account=None,facility=None):
        context=self._context(identity,'conversations',[query,kind,account,facility])
        last,_=self._decode(cursor,context)
        if last is not None and not isinstance(last,str):raise ApiError(400,'invalid_cursor')
        # Escape search wildcards; search covers identifiers, not a full sensitive history scan.
        pattern='%'+query.replace('!','!!').replace('%','!%').replace('_','!_')+'%'
        with self.read(identity,account=account,facility=facility) as (conn,_):
            rows=conn.execute('''SELECT s.phone,s.account_id,s.facility_id,u.user_id,u.language,
                u.created_at AS user_created_at,u.updated_at AS user_updated_at,
                latest.id AS last_message_id,latest.role AS last_role,latest.created_at AS last_message_at,
                substring(latest.message FROM 1 FOR 160) AS preview
              FROM observer_control.visible_scopes() s
              LEFT JOIN public.users u ON u.phone=s.phone
              LEFT JOIN LATERAL (SELECT id,role,message,created_at FROM public.messages WHERE phone=s.phone ORDER BY id DESC LIMIT 1) latest ON true
              WHERE (u.phone IS NOT NULL OR latest.id IS NOT NULL)
               AND (%s::text IS NULL OR s.phone>%s)
               AND (%s::text IS NULL OR s.account_id=%s) AND (%s::text IS NULL OR s.facility_id=%s)
               AND (s.phone ILIKE %s ESCAPE '!' OR u.user_id ILIKE %s ESCAPE '!')
               AND (%s='all' OR (%s='with_messages' AND latest.id IS NOT NULL) OR (%s='without_messages' AND latest.id IS NULL))
              ORDER BY s.phone LIMIT %s''',
              (last,last,account,account,facility,facility,pattern,pattern,kind,kind,kind,limit+1)).fetchall()
        more=len(rows)>limit;rows=rows[:limit]
        for row in rows:
            row['id']=reference(self.source_id,row['phone'])
            row['last_message_id']=str(row['last_message_id']) if row['last_message_id'] is not None else None
            row['delivery_status']='unknown';row['coverage']='captured_history'
        self._record(identity,'conversations',len(rows))
        return {'items':rows,'nextCursor':self._cursor(context,rows[-1]['phone']) if more else None,'coverageNotice':HISTORY_NOTICE}

    def history(self,identity,conversation_id,limit=50,cursor=None):
        phone=parse_reference(conversation_id,self.source_id)
        context=self._context(identity,'history',[phone])
        before,anchor=self._decode(cursor,context)
        try:
            if before is not None:
                before,anchor=int(before),int(anchor)
                if not -9223372036854775808<=before<=anchor<=9223372036854775807:raise ValueError()
        except (ValueError,TypeError):raise ApiError(400,'invalid_cursor') from None
        with self.read(identity) as (conn,_):
            scope=conn.execute('SELECT account_id,facility_id FROM observer_control.visible_scopes() WHERE phone=%s',(phone,)).fetchone()
            if not scope:raise ApiError(404,'not_found')
            exists=conn.execute('''SELECT EXISTS(SELECT 1 FROM public.users WHERE phone=%s)
                                   OR EXISTS(SELECT 1 FROM public.messages WHERE phone=%s) AS present''',(phone,phone)).fetchone()['present']
            if not exists:raise ApiError(404,'not_found')
            rows=conn.execute('''SELECT id,role,message,created_at AS timestamp FROM public.messages
                                 WHERE phone=%s AND (%s::bigint IS NULL OR id<%s) AND (%s::bigint IS NULL OR id<=%s)
                                 ORDER BY id DESC LIMIT %s''',(phone,before,before,anchor,anchor,limit+1)).fetchall()
            notes,attempts,window={},[],None
            if self.replies:
                for note in conn.execute('SELECT * FROM observer_control.reply_annotations(%s)',(phone,)).fetchall():
                    if note['message_id'] is not None:notes[note['message_id']]=note['staff_name']
                    else:attempts.append({'staff_name':note['staff_name'],'status':note['status'],'message':note['body'],
                                          'timestamp':note['created_at']})
                window=conn.execute('SELECT observer_control.reply_window(%s) AS w',(phone,)).fetchone()['w']
        more=len(rows)>limit;rows=rows[:limit]
        if anchor is None and rows:anchor=rows[0]['id']
        next_cursor=self._cursor(context,str(rows[-1]['id']),str(anchor)) if more else None
        for row in rows:
            row['sent_by_staff']=notes.get(row['id'])
            row.update(id=str(row['id']),delivery_status='unknown',provider_id=None)
        self._record(identity,'history',len(rows),conversation_id)
        return {'id':conversation_id,'phone':phone,**scope,'messages':list(reversed(rows)),
                'nextCursor':next_cursor,'snapshotMaxId':str(anchor) if anchor is not None else None,'coverageNotice':HISTORY_NOTICE,
                'replyAttempts':attempts,'replyWindow':window}

    def records(self,identity,table,limit=25,cursor=None,account=None,facility=None,status=None):
        if table not in ('orders','referrals'):raise ValueError('unsupported projection')
        context=self._context(identity,table,[account,facility,status]);before,anchor=self._decode(cursor,context)
        try:
            if before is not None:
                before,anchor=int(before),int(anchor)
                if not -9223372036854775808<=before<=anchor<=9223372036854775807:raise ValueError()
        except (ValueError,TypeError):raise ApiError(400,'invalid_cursor') from None
        fields='t.id,t.phone,t.product,t.price,t.quantity,t.status,t.created_at' if table=='orders' else 't.id,t.phone,t.source,t.created_at'
        status_clause='AND (%s::text IS NULL OR t.status=%s)' if table=='orders' else ''
        args=[before,before,anchor,anchor,account,account,facility,facility]
        if table=='orders':args.extend([status,status])
        args.append(limit+1)
        with self.read(identity,account=account,facility=facility) as (conn,_):
            rows=conn.execute(f'''SELECT {fields},s.account_id,s.facility_id FROM public.{table} t
               JOIN observer_control.visible_scopes() s ON s.phone=t.phone
               WHERE (%s::bigint IS NULL OR t.id<%s) AND (%s::bigint IS NULL OR t.id<=%s)
               AND (%s::text IS NULL OR s.account_id=%s) AND (%s::text IS NULL OR s.facility_id=%s)
               {status_clause} ORDER BY t.id DESC LIMIT %s''',args).fetchall()
        more=len(rows)>limit;rows=rows[:limit]
        if anchor is None and rows:anchor=rows[0]['id']
        next_cursor=self._cursor(context,str(rows[-1]['id']),str(anchor)) if more else None
        for row in rows:row['id']=str(row['id'])
        self._record(identity,table,len(rows))
        return {'items':rows,'nextCursor':next_cursor}

    def analytics(self,identity,account=None,facility=None):
        with self.read(identity,raw=False,account=account,facility=facility) as (conn,_):
            row=conn.execute('SELECT * FROM observer_control.counts(%s,%s)',(account,facility)).fetchone()
        self._record(identity,'analytics',1)
        return {'counts':row,'coverageNotice':HISTORY_NOTICE,
                'unavailableMetrics':['delivery_rate','conversion_rate','response_time','clinical_resolution'],
                'scope':'explicit approved source/account/facility mappings'}


ADMIN_ERRORS={'42501':403,'22023':400,'23505':409}


class StaffAdmin:
    """Staff management through database functions that themselves require an active admin,
    via a separate login (rudo_staff_admin) that can do nothing except call those functions."""
    FUNCTIONS={'overview':'SELECT observer_control.admin_overview() AS result',
               'invite':'SELECT observer_control.admin_invite(%s,%s,%s::jsonb,%s::uuid) AS result',
               'approve':'SELECT observer_control.admin_approve(%s::uuid,%s,%s) AS result',
               'update':'SELECT observer_control.admin_update_staff(%s::uuid,%s,%s,%s::jsonb) AS result',
               'revoke_invitation':'SELECT observer_control.admin_revoke_invitation(%s::uuid) AS result',
               'unlink':'SELECT observer_control.admin_unlink_identity(%s,%s) AS result',
               'dismiss':'SELECT observer_control.admin_dismiss_request(%s,%s) AS result'}

    def __init__(self,dsn,audit,source_id,allow_remote=False):
        self.dsn,self.audit,self.source_id,self.allow_remote=dsn,audit,source_id,allow_remote

    def call(self,identity,name,*args):
        if not self.dsn or not self.source_id:raise ApiError(503,'staff_admin_unavailable')
        try:
            with connect(self.dsn,self.allow_remote,'rudo_staff_admin',row_factory=dict_row) as conn:
                set_context(conn,identity,self.source_id)
                result=conn.execute(self.FUNCTIONS[name],args).fetchone()['result']
        except psycopg.errors.InvalidTextRepresentation:
            raise ApiError(400,'invalid_identifier') from None
        except psycopg.Error as exc:
            status=ADMIN_ERRORS.get(exc.sqlstate)
            if status is None:raise
            code=exc.diag.message_primary or 'rejected'
            raise ApiError(status,code if code.replace('_','').isalpha() else 'rejected') from None
        if name!='overview':
            try:self.audit.append(identity,self.source_id,'staff_admin',1,name)
            except Exception:pass  # The privileged action itself is recorded in staff_admin_events.
        return result
