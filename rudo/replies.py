"""Staff replies from the dashboard, sent from the bot's WhatsApp number. Two database steps around one
WhatsApp call: begin (authorise + claim, committed first) -> send once -> finish (record outcome; only a
provider-confirmed send enters the bot's history). An uncertain outcome is 'unknown' and is never resent."""
from .delivery import MetaSender
from .errors import ApiError
from .observer import ADMIN_ERRORS, connect, parse_reference, set_context

import re

import psycopg
from psycopg.rows import dict_row


class StaffReplies:
    def __init__(self, dsn, source_id, sender, allow_remote=False, enabled=False):
        self.dsn, self.source_id, self.sender = dsn, source_id, sender
        self.allow_remote, self.enabled = allow_remote, enabled

    @classmethod
    def from_config(cls, config, source_id):
        sender = MetaSender(config.get('WHATSAPP_TOKEN', ''), config.get('WHATSAPP_PHONE_NUMBER_ID', ''),
                            config.get('WHATSAPP_API_VERSION', 'v19.0'), enabled=config.get('ENABLE_STAFF_REPLIES', False))
        return cls(config.get('SENDER_DATABASE_URL', ''), source_id, sender,
                   allow_remote=config.get('OBSERVER_ALLOW_REMOTE', False), enabled=config.get('ENABLE_STAFF_REPLIES', False))

    @property
    def available(self):
        s = self.sender
        return bool(self.enabled and self.dsn and self.source_id and s.enabled and s.token and s.account)

    def _call(self, identity, statement, args):
        try:
            with connect(self.dsn, self.allow_remote, 'rudo_sender', row_factory=dict_row, autocommit=False) as conn:
                set_context(conn, identity, self.source_id)
                return conn.execute(statement, args).fetchone()['result']
        except psycopg.errors.InvalidTextRepresentation:
            raise ApiError(400, 'invalid_identifier') from None
        except psycopg.Error as exc:
            status = ADMIN_ERRORS.get(exc.sqlstate)
            if status is None:
                raise
            code = exc.diag.message_primary or 'rejected'
            raise ApiError(404 if code == 'not_found' else status, code if re.fullmatch(r'[a-z0-9_]{1,60}', code) else 'rejected') from None

    def send(self, identity, conversation_id, body, request_id):
        if not self.available:
            raise ApiError(503, 'replies_disabled')
        phone = parse_reference(conversation_id, self.source_id)
        claim = self._call(identity, 'SELECT observer_control.begin_staff_reply(%s::uuid,%s,%s) AS result',
                           (request_id, phone, body))
        if claim.get('duplicate'):
            return {'id': claim['id'], 'status': claim['status'], 'duplicate': True}
        try:
            status, provider_id = self.sender.send(phone, body)
            error = None if status == 'sent' else ('provider_rejected' if status == 'failed' else 'provider_uncertain')
        except ApiError:
            status, provider_id, error = 'failed', None, 'sending_disabled'
        except Exception:
            status, provider_id, error = 'unknown', None, 'network_uncertain'  # May have been delivered: never auto-resend.
        result = self._call(identity, 'SELECT observer_control.finish_staff_reply(%s::uuid,%s,%s,%s) AS result',
                            (claim['id'], status, provider_id, error))
        return {'id': result['id'], 'status': result['status'],
                'messageId': str(result['message_id']) if result.get('message_id') is not None else None}
