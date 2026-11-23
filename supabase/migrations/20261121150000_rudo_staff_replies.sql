-- Rudo staff replies from the dashboard (sent from the bot's WhatsApp number by the dashboard server).
-- Target: cktfbpnxpfbyroqzuibc, applied as "postgres" in ONE transaction, after 20261121120000.
--
-- Effect on bot tables: a confirmed staff reply is inserted into public.messages as role 'bot' (exactly how
-- the bot stores its own replies), so the bot's future answers include it as context. Inserts happen only
-- inside finish_staff_reply() (SECURITY DEFINER, owner postgres); no new grant on any bot table.
-- public.kv is read only inside begin_staff_reply() to refuse replies during an active WhatsApp agent session.
-- Rollback: supabase/rollback/20261121150000_rudo_staff_replies.down.sql (keeps already-sent history rows).

DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='observer_control') THEN
  RAISE EXCEPTION 'apply 20261121120000_rudo_staff_control first';
 END IF;
 IF to_regclass('observer_control.staff_replies') IS NOT NULL THEN
  RAISE EXCEPTION 'staff replies already installed';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='rudo_sender') THEN
  CREATE ROLE rudo_sender LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;
 END IF;
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='rudo_sender' AND (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole))
    OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname='rudo_sender') THEN
  RAISE EXCEPTION 'unsafe rudo_sender role';
 END IF;
END $$;
ALTER ROLE rudo_sender SET statement_timeout='5s';
GRANT USAGE ON SCHEMA observer_control TO rudo_sender;

CREATE TABLE observer_control.staff_replies (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 request_id uuid NOT NULL,
 staff_id uuid NOT NULL REFERENCES observer_control.staff(id),
 source_id text NOT NULL,phone text NOT NULL,
 body text NOT NULL CHECK(length(btrim(body)) BETWEEN 1 AND 3800),
 status text NOT NULL DEFAULT 'sending' CHECK(status IN ('sending','sent','failed','unknown')),
 provider_message_id text,message_id bigint,error_code text CHECK(length(error_code)<=80),
 created_at timestamptz NOT NULL DEFAULT now(),finished_at timestamptz,
 UNIQUE(staff_id,request_id),
 CHECK((status='sent')=(message_id IS NOT NULL))
);
CREATE INDEX staff_replies_phone_idx ON observer_control.staff_replies(source_id,phone,created_at);
CREATE INDEX staff_replies_rate_idx ON observer_control.staff_replies(staff_id,created_at);
ALTER TABLE observer_control.staff_replies ENABLE ROW LEVEL SECURITY;  -- No policies: functions only.

-- Step 1: authorise and claim. Committed BEFORE the WhatsApp call, so a crash leaves 'sending', never a resend.
CREATE FUNCTION observer_control.begin_staff_reply(p_request uuid,p_phone text,p_body text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
DECLARE sid uuid:=observer_control.current_staff(); src text:=current_setting('observer.source',true);
        existing observer_control.staff_replies; last_user timestamptz; rid uuid;
BEGIN
 IF sid IS NULL THEN RAISE EXCEPTION 'staff_required' USING ERRCODE='42501'; END IF;
 IF NOT EXISTS(SELECT 1 FROM observer_control.staff WHERE id=sid AND role IN ('admin','operator')) THEN
  RAISE EXCEPTION 'role_required' USING ERRCODE='42501';
 END IF;
 SELECT * INTO existing FROM observer_control.staff_replies WHERE staff_id=sid AND request_id=p_request;
 IF existing.id IS NOT NULL THEN  -- Idempotent: the same request never sends twice.
  RETURN jsonb_build_object('id',existing.id,'status',existing.status,'duplicate',true);
 END IF;
 IF NOT observer_control.visible(p_phone) THEN RAISE EXCEPTION 'not_found' USING ERRCODE='42501'; END IF;
 IF p_body IS NULL OR length(btrim(p_body)) NOT BETWEEN 1 AND 3800 THEN RAISE EXCEPTION 'invalid_message' USING ERRCODE='22023'; END IF;
 SELECT max(created_at) INTO last_user FROM public.messages WHERE phone=p_phone AND role='user';
 IF last_user IS NULL OR last_user < now()-interval '24 hours' THEN
  RAISE EXCEPTION 'outside_24h_window' USING ERRCODE='22023';  -- WhatsApp allows free-form replies only within 24 h.
 END IF;
 IF EXISTS(SELECT 1 FROM public.kv WHERE key='agent_session:'||p_phone AND (expires_at IS NULL OR expires_at>now())) THEN
  RAISE EXCEPTION 'agent_session_active' USING ERRCODE='22023';  -- A WhatsApp agent is handling this patient.
 END IF;
 IF (SELECT count(*) FROM observer_control.staff_replies WHERE staff_id=sid AND created_at>now()-interval '1 minute')>=10 THEN
  RAISE EXCEPTION 'rate_limited' USING ERRCODE='22023';
 END IF;
 IF EXISTS(SELECT 1 FROM observer_control.staff_replies WHERE source_id=src AND phone=p_phone AND status='sending'
           AND created_at>now()-interval '2 minutes') THEN
  RAISE EXCEPTION 'reply_in_progress' USING ERRCODE='22023';
 END IF;
 INSERT INTO observer_control.staff_replies(request_id,staff_id,source_id,phone,body)
 VALUES(p_request,sid,src,p_phone,p_body) RETURNING id INTO rid;
 RETURN jsonb_build_object('id',rid,'status','sending','duplicate',false);
END $$;

-- Step 2: record the WhatsApp outcome. Only 'sent' (provider accepted, message id returned) enters history.
CREATE FUNCTION observer_control.finish_staff_reply(p_id uuid,p_status text,p_provider_id text,p_error text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
DECLARE sid uuid:=observer_control.current_staff(); r observer_control.staff_replies; mid bigint;
BEGIN
 SELECT * INTO r FROM observer_control.staff_replies WHERE id=p_id FOR UPDATE;
 IF r.id IS NULL OR r.staff_id IS DISTINCT FROM sid THEN RAISE EXCEPTION 'not_found' USING ERRCODE='42501'; END IF;
 IF r.status<>'sending' THEN RETURN jsonb_build_object('id',r.id,'status',r.status,'message_id',r.message_id); END IF;
 IF p_status NOT IN ('sent','failed','unknown') OR (p_status='sent' AND coalesce(p_provider_id,'')='') THEN
  RAISE EXCEPTION 'invalid_outcome' USING ERRCODE='22023';
 END IF;
 IF p_status='sent' THEN
  INSERT INTO public.messages(phone,role,message,message_en) VALUES(r.phone,'bot',r.body,r.body) RETURNING id INTO mid;
 END IF;
 UPDATE observer_control.staff_replies SET status=p_status,provider_message_id=nullif(p_provider_id,''),message_id=mid,
   error_code=left(p_error,80),finished_at=now() WHERE id=r.id;
 RETURN jsonb_build_object('id',r.id,'status',p_status,'message_id',mid);
END $$;

-- Dashboard display: who sent which history row, plus failed/unknown attempts that never entered history.
CREATE FUNCTION observer_control.reply_annotations(p_phone text)
RETURNS TABLE(message_id bigint,staff_name text,status text,body text,created_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
 SELECT r.message_id,coalesce(s.display_name,s.email),r.status,CASE WHEN r.status='sent' THEN NULL ELSE r.body END,r.created_at
 FROM observer_control.staff_replies r JOIN observer_control.staff s ON s.id=r.staff_id
 WHERE r.source_id=current_setting('observer.source',true) AND r.phone=p_phone AND observer_control.visible(p_phone)
 ORDER BY r.created_at DESC LIMIT 200
$$;
-- Whether a conversation can be replied to now (for the dashboard to explain a disabled reply box).
CREATE FUNCTION observer_control.reply_window(p_phone text) RETURNS jsonb
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
 SELECT CASE WHEN NOT observer_control.visible(p_phone) THEN NULL ELSE jsonb_build_object(
  'last_user_message_at',(SELECT max(created_at) FROM public.messages WHERE phone=p_phone AND role='user'),
  'agent_session_active',EXISTS(SELECT 1 FROM public.kv WHERE key='agent_session:'||p_phone AND (expires_at IS NULL OR expires_at>now()))) END
$$;

REVOKE ALL ON FUNCTION observer_control.begin_staff_reply(uuid,text,text),observer_control.finish_staff_reply(uuid,text,text,text),
 observer_control.reply_annotations(text),observer_control.reply_window(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION observer_control.begin_staff_reply(uuid,text,text),observer_control.finish_staff_reply(uuid,text,text,text),
 observer_control.current_staff() TO rudo_sender;
GRANT EXECUTE ON FUNCTION observer_control.reply_annotations(text),observer_control.reply_window(text) TO rudo_observer;
DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
   EXECUTE format('REVOKE ALL ON observer_control.staff_replies FROM %I',r);
   EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA observer_control FROM %I',r);
  END IF;
 END LOOP;
END $$;
