"""Private Postgres adapter; verified staff context is transaction-local, never pooled globally."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .errors import ApiError


class Database:
    def __init__(self, dsn='', worker_dsn='', allow_remote=False):
        self.dsn = dsn
        self.worker_dsn = worker_dsn
        self.allow_remote = allow_remote

    def check_target(self, dsn):
        if not dsn:
            raise ApiError(503, 'database_unavailable')
        from psycopg.conninfo import conninfo_to_dict
        try:
            info = conninfo_to_dict(dsn)
        except Exception:
            raise ApiError(503, 'database_configuration') from None
        host = info.get('host', '')
        local = host in ('127.0.0.1', 'localhost', '::1')
        indirect = info.get('hostaddr') or os.getenv('PGHOSTADDR','')
        service = info.get('service') or os.getenv('PGSERVICE','')
        if not self.allow_remote and (service or indirect not in ('','127.0.0.1','::1')):
            raise ApiError(503, 'remote_database_disabled')
        if self.allow_remote and not local and info.get('sslmode') != 'verify-full':
            raise ApiError(503, 'verified_database_tls_required')
        if not self.allow_remote and not local:
            # Only explicit loopback is accepted: absent hosts and arbitrary sockets fail closed.
            raise ApiError(503, 'remote_database_disabled')

    @contextmanager
    def transaction(self, identity=None, worker=False):
        dsn = self.worker_dsn if worker else self.dsn
        self.check_target(dsn)
        with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row) as conn:
            role = 'rudo_worker' if worker else 'rudo_api'
            conn.execute('SET LOCAL ROLE ' + role)
            conn.execute("SET LOCAL statement_timeout = '10s'")
            conn.execute("SELECT set_config('rudo.subject', %s, true), set_config('rudo.issuer', %s, true)",
                         ((identity or {}).get('subject', ''), (identity or {}).get('issuer', '')))
            yield conn

    def membership(self, identity):
        with self.transaction(identity) as c:
            row = c.execute('SELECT * FROM rudo.staff()').fetchone()
        if not row or not row['active']:
            raise ApiError(403, 'staff_required')
        return row

    def conversations(self, identity, limit, offset):
        with self.transaction(identity) as c:
            rows = c.execute('SELECT * FROM rudo.conversations ORDER BY id LIMIT %s OFFSET %s',
                             (limit, offset)).fetchall()
            for row in rows:
                row['messages'] = self._messages(c, row['id'])
            self.audit(c, identity, 'conversation.list', None)
        return rows

    @staticmethod
    def _messages(c, conversation_id):
        # Hard cap is explicit, rather than silently claiming complete history.
        rows = c.execute('''SELECT id,role,message,message_en,occurred_at AS timestamp,delivery_status
                            FROM rudo.messages WHERE conversation_id=%s
                            ORDER BY occurred_at NULLS LAST,source_ordinal LIMIT 10001''',
                         (conversation_id,)).fetchall()
        if len(rows) > 10000:
            raise ApiError(422, 'thread_requires_history_pagination')
        pending = c.execute('''SELECT id,'bot' AS role,message,created_at AS timestamp,status AS delivery_status
                               FROM rudo.outbox WHERE conversation_id=%s AND status<>'sent'
                               ORDER BY created_at''', (conversation_id,)).fetchall()
        return rows + pending

    def conversation(self, identity, conversation_id):
        with self.transaction(identity) as c:
            row = c.execute('SELECT * FROM rudo.conversations WHERE id=%s', (conversation_id,)).fetchone()
            if not row:
                raise ApiError(404, 'not_found')
            row['messages'] = self._messages(c, conversation_id)
            self.audit(c, identity, 'conversation.read', conversation_id)
        return row

    def create_conversation(self, identity, phone, account, facility):
        with self.transaction(identity) as c:
            row = c.execute('''INSERT INTO rudo.conversations(id,phone,account_id,facility_id)
                               VALUES(%s,%s,%s,%s) ON CONFLICT(account_id,phone)
                               DO NOTHING RETURNING *''', (uuid4(), phone, account, facility)).fetchone()
            if not row:
                row = c.execute('SELECT * FROM rudo.conversations WHERE account_id=%s AND phone=%s',
                                (account, phone)).fetchone()
                if not row:
                    raise ApiError(409, 'conversation_conflict')
            self.audit(c, identity, 'conversation.open', row['id'])
        return row

    @staticmethod
    def audit(c, identity, action, resource_id):
        c.execute('''INSERT INTO rudo.audit_events(actor_issuer,actor_subject,action,resource_id)
                     VALUES(%s,%s,%s,%s)''', (identity['issuer'], identity['subject'], action, resource_id))

    def change_status(self, identity, table, record_id, status, version):
        if table not in ('orders', 'conversations'):
            raise ValueError('unsupported table')
        with self.transaction(identity) as c:
            # Fixed allowlist above, no user-supplied SQL identifier.
            row = c.execute(f'''UPDATE rudo.{table} SET status=%s,version=version+1,updated_at=now()
                                WHERE id=%s AND version=%s RETURNING *''',
                            (status, record_id, version)).fetchone()
            if not row:
                visible = c.execute(f'SELECT id FROM rudo.{table} WHERE id=%s', (record_id,)).fetchone()
                raise ApiError(409 if visible else 404, 'version_conflict' if visible else 'not_found')
            self.audit(c, identity, table + '.status', record_id)
        return row

    def enqueue(self, identity, conversation_id, text, operation_id):
        with self.transaction(identity) as c:
            thread = c.execute('SELECT id FROM rudo.conversations WHERE id=%s', (conversation_id,)).fetchone()
            if not thread:
                raise ApiError(404, 'not_found')
            row = c.execute('''INSERT INTO rudo.outbox(id,conversation_id,actor_issuer,actor_subject,message)
                               VALUES(%s,%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING RETURNING *''',
                            (operation_id, conversation_id, identity['issuer'], identity['subject'], text)).fetchone()
            if not row:
                row = c.execute('SELECT * FROM rudo.outbox WHERE id=%s', (operation_id,)).fetchone()
                if (not row or str(row['conversation_id']) != str(conversation_id)
                        or row['message'] != text or row['actor_subject'] != identity['subject']
                        or row['actor_issuer'] != identity['issuer']):
                    raise ApiError(409, 'idempotency_conflict')
            else:
                self.audit(c, identity, 'message.enqueue', conversation_id)
        return row

    def orders(self, identity, limit, offset):
        with self.transaction(identity) as c:
            rows=c.execute('SELECT * FROM rudo.orders ORDER BY id LIMIT %s OFFSET %s',
                           (limit, offset)).fetchall()
            self.audit(c,identity,'order.list',None)
            return rows

    def referrals(self, identity, limit, offset):
        with self.transaction(identity) as c:
            rows=c.execute('SELECT * FROM rudo.referrals ORDER BY id LIMIT %s OFFSET %s',
                           (limit, offset)).fetchall()
            self.audit(c,identity,'referral.list',None)
            return rows

    def analytics(self, identity):
        with self.transaction(identity) as c:
            row=c.execute('SELECT * FROM rudo.analytics()').fetchone()
            self.audit(c,identity,'analytics.read',None)
            return row

    def accept_webhook(self, payload, account, facility):
        accepted = 0
        with self.transaction(worker=True) as c:
            for entry in payload.get('entry', []):
                for change in entry.get('changes', []):
                    if change.get('field') != 'messages':
                        continue
                    value = change.get('value', {})
                    if value.get('metadata', {}).get('phone_number_id') != account:
                        raise ApiError(403, 'wrong_messaging_account')
                    events = [('message', event) for event in value.get('messages', [])]
                    events += [('status', event) for event in value.get('statuses', [])]
                    for kind, event in events:
                        if not isinstance(event, dict) or not isinstance(event.get('id'), str):
                            raise ApiError(400, 'invalid_event')
                        digest = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
                        event_id = ('message:' + event['id'] if kind == 'message' else
                                    'status:' + event['id'] + ':' + str(event.get('status')) + ':' + str(event.get('timestamp')))
                        inserted = c.execute('''INSERT INTO rudo.webhook_inbox(account_id,event_id,payload_digest,provider_id,delivery_status)
                                                VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING event_id''',
                                             (account, event_id, digest, event['id'], event.get('status') if kind=='status' else None)).fetchone()
                        if not inserted:
                            previous = c.execute('''SELECT payload_digest FROM rudo.webhook_inbox
                                                    WHERE account_id=%s AND event_id=%s''', (account, event_id)).fetchone()
                            if previous['payload_digest'] != digest:
                                raise ApiError(409, 'event_identity_conflict')
                            continue
                        if kind == 'status':
                            status = event.get('status')
                            # Never regress read/delivered to sent on delayed delivery.
                            if status in ('sent','delivered','read','failed'):
                                c.execute('''UPDATE rudo.messages SET delivery_status=%s WHERE account_id=%s AND provider_id=%s
                                  AND delivery_status NOT IN ('read') AND NOT(delivery_status='delivered' AND %s='sent')''',
                                          (status, account, event['id'], status))
                        else:
                            phone = event.get('from', '')
                            import re
                            if not isinstance(phone, str) or not re.fullmatch(r'[1-9][0-9]{9,14}', phone):
                                raise ApiError(400, 'invalid_event')
                            try:
                                stamp = datetime.fromtimestamp(int(event['timestamp']), timezone.utc)
                            except (KeyError, ValueError, TypeError, OverflowError, OSError):
                                raise ApiError(400, 'invalid_event_time') from None
                            msg_type = event.get('type')
                            if msg_type == 'text':
                                text = event.get('text', {}).get('body')
                            elif msg_type == 'interactive':
                                interactive = event.get('interactive', {})
                                text = interactive.get(interactive.get('type'), {}).get('title')
                            else:
                                text = '[' + str(msg_type)[:40] + ' message]'
                            if not isinstance(text, str) or not 1 <= len(text) <= 65536:
                                raise ApiError(400, 'invalid_event')
                            thread = c.execute('''INSERT INTO rudo.conversations(id,account_id,phone,facility_id)
                                                 VALUES(%s,%s,%s,%s) ON CONFLICT(account_id,phone)
                                                 DO UPDATE SET updated_at=now(),version=rudo.conversations.version+1 RETURNING id''',
                                              (uuid4(), account, phone, facility)).fetchone()
                            c.execute('''INSERT INTO rudo.messages(id,conversation_id,role,message,occurred_at,provider_id,account_id)
                                         VALUES(%s,%s,'user',%s,%s,%s,%s)''',
                                      (uuid4(), thread['id'], text, stamp, event['id'], account))
                        accepted += 1
        return accepted

    def state_get(self, key):
        with self.transaction(worker=True) as c:
            row=c.execute('''SELECT value FROM rudo.expiring_state WHERE key=%s
                             AND (expires_at IS NULL OR expires_at>now())''',(key,)).fetchone()
        return row['value'] if row else None

    def state_acquire(self, key, value, seconds):
        if seconds<=0:raise ValueError('positive lifetime required')
        with self.transaction(worker=True) as c:
            row=c.execute('''INSERT INTO rudo.expiring_state(key,value,expires_at)
                             VALUES(%s,%s,now()+(%s * interval '1 second'))
                             ON CONFLICT(key) DO UPDATE SET value=excluded.value,expires_at=excluded.expires_at
                             WHERE rudo.expiring_state.expires_at<=now() RETURNING key''',
                          (key,Jsonb(value),seconds)).fetchone()
        return bool(row)
