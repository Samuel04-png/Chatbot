-- Rollback for 20261121150000_rudo_staff_replies.sql. Run as "postgres" in ONE transaction.
-- Disables staff replies. Replies already SENT stay in public.messages (they were delivered to patients and
-- are part of the conversation history); the reply ledger is dropped, so export it first if needed.
BEGIN;
DROP FUNCTION IF EXISTS observer_control.begin_staff_reply(uuid,text,text);
DROP FUNCTION IF EXISTS observer_control.finish_staff_reply(uuid,text,text,text);
DROP FUNCTION IF EXISTS observer_control.reply_annotations(text);
DROP FUNCTION IF EXISTS observer_control.reply_window(text);
DROP TABLE IF EXISTS observer_control.staff_replies;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='rudo_sender') THEN
  REVOKE ALL ON SCHEMA observer_control FROM rudo_sender;
  REVOKE ALL ON FUNCTION observer_control.current_staff() FROM rudo_sender;
 END IF;
END $$;
DROP ROLE IF EXISTS rudo_sender;
DO $$ BEGIN
 IF to_regclass('observer_control.staff_replies') IS NOT NULL OR EXISTS(SELECT 1 FROM pg_roles WHERE rolname='rudo_sender') THEN
  RAISE EXCEPTION 'staff replies rollback incomplete';
 END IF;
END $$;
COMMIT;
