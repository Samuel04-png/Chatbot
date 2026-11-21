-- PROPOSED, LOCAL-TESTED ONLY. Never modifies existing public bot tables.
-- Apply once through the migration ledger. An unexpected existing rudo schema fails.
CREATE SCHEMA rudo;
REVOKE ALL ON SCHEMA rudo FROM PUBLIC;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='rudo_api') THEN
    CREATE ROLE rudo_api NOLOGIN NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='rudo_worker') THEN
    CREATE ROLE rudo_worker NOLOGIN NOBYPASSRLS;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('rudo_api','rudo_worker')
             AND (rolsuper OR rolbypassrls OR rolcanlogin)) THEN
    RAISE EXCEPTION 'unexpected runtime role attributes';
  END IF;
END $$;
GRANT USAGE ON SCHEMA rudo TO rudo_api, rudo_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA rudo REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

CREATE TABLE rudo.staff_memberships (
  issuer text NOT NULL,
  subject text NOT NULL,
  role text NOT NULL CHECK (role IN ('admin','operator','analyst')),
  facilities text[] NOT NULL DEFAULT '{}',
  active boolean NOT NULL DEFAULT true,
  PRIMARY KEY (issuer,subject)
);
CREATE FUNCTION rudo.staff() RETURNS SETOF rudo.staff_memberships
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,rudo AS $$
 SELECT * FROM rudo.staff_memberships WHERE active
 AND subject=current_setting('rudo.subject',true)
 AND issuer=current_setting('rudo.issuer',true)
$$;
CREATE FUNCTION rudo.allowed(facility text, writing boolean DEFAULT false)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path=pg_catalog,rudo AS $$
 SELECT EXISTS(SELECT 1 FROM rudo.staff() s
 WHERE s.role IN ('admin','operator') AND facility=ANY(s.facilities))
$$;

CREATE TABLE rudo.conversations (
 id uuid PRIMARY KEY,
 account_id text NOT NULL,
 phone text NOT NULL CHECK (phone ~ '^[1-9][0-9]{9,14}$'),
 facility_id text NOT NULL,
 status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','closed')),
 version bigint NOT NULL DEFAULT 1,
 created_at timestamptz DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now(),
 UNIQUE(account_id,phone)
);
CREATE TABLE rudo.messages (
 id uuid PRIMARY KEY,
 conversation_id uuid NOT NULL REFERENCES rudo.conversations(id) ON DELETE RESTRICT,
 role text NOT NULL,
 message text NOT NULL,
 message_en text,
 occurred_at timestamptz,
 recorded_at timestamptz NOT NULL DEFAULT now(),
 source_ordinal bigint GENERATED ALWAYS AS IDENTITY,
 provider_id text,
 account_id text NOT NULL,
 delivery_status text NOT NULL DEFAULT 'received'
 CHECK(delivery_status IN ('received','pending','sent','delivered','read','failed','unknown')),
 UNIQUE(account_id,provider_id)
);
CREATE INDEX messages_thread_time ON rudo.messages(conversation_id,occurred_at,source_ordinal);
CREATE INDEX conversations_scope ON rudo.conversations(facility_id,status,updated_at DESC);
CREATE TABLE rudo.orders (
 id uuid PRIMARY KEY,
 source_key text UNIQUE,
 conversation_id uuid REFERENCES rudo.conversations(id),
 facility_id text NOT NULL,
 payload jsonb NOT NULL,
 status text NOT NULL CHECK(status IN ('pending','confirmed','completed','cancelled','paid','unpaid','collected','delivered')),
 version bigint NOT NULL DEFAULT 1,
 created_at timestamptz,
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX orders_scope ON rudo.orders(facility_id,status,created_at DESC);
CREATE TABLE rudo.referrals (
 id uuid PRIMARY KEY,
 source_key text UNIQUE,
 facility_id text NOT NULL,
 source text NOT NULL,
 payload jsonb NOT NULL DEFAULT '{}',
 occurred_at timestamptz
);
CREATE INDEX referrals_scope_time ON rudo.referrals(facility_id,occurred_at);
CREATE TABLE rudo.expiring_state (
 key text PRIMARY KEY, value jsonb NOT NULL, expires_at timestamptz
);
CREATE INDEX state_expiry ON rudo.expiring_state(expires_at);
CREATE TABLE rudo.webhook_inbox (
 account_id text NOT NULL,
 event_id text NOT NULL,
 payload_digest text NOT NULL,
 provider_id text,
 delivery_status text,
 accepted_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(account_id,event_id)
);
CREATE INDEX inbox_provider_status ON rudo.webhook_inbox(account_id,provider_id,delivery_status);
CREATE TABLE rudo.outbox (
 id uuid PRIMARY KEY,
 conversation_id uuid NOT NULL REFERENCES rudo.conversations(id),
 actor_issuer text NOT NULL,
 actor_subject text NOT NULL,
 message text NOT NULL CHECK(length(message) BETWEEN 1 AND 4096),
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','sending','sent','failed','unknown')),
 provider_id text,
 attempts integer NOT NULL DEFAULT 0,
 created_at timestamptz NOT NULL DEFAULT now(),
 updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX outbox_ready ON rudo.outbox(status,created_at);
CREATE TABLE rudo.audit_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 actor_issuer text NOT NULL, actor_subject text NOT NULL,
 action text NOT NULL, resource_id uuid, occurred_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE rudo.migration_records (
 source_alias text NOT NULL, source_key text NOT NULL, source_digest text NOT NULL,
 target_id uuid, expires_at timestamptz, source_payload jsonb NOT NULL, imported_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(source_alias,source_key)
);

DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['staff_memberships','conversations','messages','orders','referrals',
 'expiring_state','webhook_inbox','outbox','audit_events','migration_records'] LOOP
 EXECUTE format('ALTER TABLE rudo.%I ENABLE ROW LEVEL SECURITY',t);
 END LOOP;
END $$;
CREATE POLICY membership_self ON rudo.staff_memberships FOR SELECT TO rudo_api
 USING(subject=current_setting('rudo.subject',true) AND issuer=current_setting('rudo.issuer',true));
CREATE POLICY conversation_read ON rudo.conversations FOR SELECT TO rudo_api
 USING(rudo.allowed(facility_id));
CREATE POLICY conversation_insert ON rudo.conversations FOR INSERT TO rudo_api
 WITH CHECK(rudo.allowed(facility_id,true));
CREATE POLICY conversation_update ON rudo.conversations FOR UPDATE TO rudo_api
 USING(rudo.allowed(facility_id,true)) WITH CHECK(rudo.allowed(facility_id,true));
CREATE POLICY message_read ON rudo.messages FOR SELECT TO rudo_api USING(EXISTS(
 SELECT 1 FROM rudo.conversations c WHERE c.id=conversation_id AND rudo.allowed(c.facility_id)));
CREATE POLICY order_read ON rudo.orders FOR SELECT TO rudo_api USING(rudo.allowed(facility_id));
CREATE POLICY order_update ON rudo.orders FOR UPDATE TO rudo_api
 USING(rudo.allowed(facility_id,true)) WITH CHECK(rudo.allowed(facility_id,true));
CREATE POLICY referral_read ON rudo.referrals FOR SELECT TO rudo_api USING(rudo.allowed(facility_id));
CREATE POLICY outbox_read ON rudo.outbox FOR SELECT TO rudo_api USING(EXISTS(
 SELECT 1 FROM rudo.conversations c WHERE c.id=conversation_id AND rudo.allowed(c.facility_id)));
CREATE POLICY outbox_insert ON rudo.outbox FOR INSERT TO rudo_api WITH CHECK(
 actor_subject=current_setting('rudo.subject',true) AND actor_issuer=current_setting('rudo.issuer',true)
 AND EXISTS(SELECT 1 FROM rudo.conversations c WHERE c.id=conversation_id AND rudo.allowed(c.facility_id,true)));
CREATE POLICY audit_append ON rudo.audit_events FOR INSERT TO rudo_api WITH CHECK(
 actor_subject=current_setting('rudo.subject',true) AND actor_issuer=current_setting('rudo.issuer',true));
DO $$ DECLARE t text; BEGIN
 FOREACH t IN ARRAY ARRAY['conversations','messages','referrals','webhook_inbox','outbox','expiring_state'] LOOP
 EXECUTE format('CREATE POLICY worker_access ON rudo.%I TO rudo_worker USING(true) WITH CHECK(true)',t);
 END LOOP;
END $$;
GRANT SELECT ON rudo.staff_memberships,rudo.conversations,rudo.messages,rudo.orders,rudo.referrals,rudo.outbox TO rudo_api;
GRANT INSERT ON rudo.conversations,rudo.outbox,rudo.audit_events TO rudo_api;
GRANT UPDATE(status,version,updated_at) ON rudo.conversations,rudo.orders TO rudo_api;
GRANT USAGE ON SEQUENCE rudo.audit_events_id_seq TO rudo_api;
GRANT SELECT,INSERT,UPDATE ON rudo.conversations,rudo.messages,rudo.referrals,rudo.webhook_inbox,rudo.outbox,rudo.expiring_state TO rudo_worker;
GRANT USAGE ON SEQUENCE rudo.messages_source_ordinal_seq TO rudo_worker;
GRANT EXECUTE ON FUNCTION rudo.staff(),rudo.allowed(text,boolean) TO rudo_api;
REVOKE ALL ON ALL TABLES IN SCHEMA rudo FROM PUBLIC;
REVOKE EXECUTE ON ALL FUNCTIONS IN SCHEMA rudo FROM PUBLIC;
-- Login provisioning / role membership is deliberately NOT included. Owner review required.
-- No anon, authenticated, service_role or PostgREST grants/exposure are added.

-- Approved aggregate surface for analysts: counts only, never phone/message/address.
CREATE FUNCTION rudo.analytics() RETURNS TABLE(conversations bigint, orders bigint, referrals bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,rudo AS $$
 SELECT
 (SELECT count(*) FROM rudo.conversations c WHERE EXISTS(SELECT 1 FROM rudo.staff() s WHERE c.facility_id=ANY(s.facilities))),
 (SELECT count(*) FROM rudo.orders o WHERE EXISTS(SELECT 1 FROM rudo.staff() s WHERE o.facility_id=ANY(s.facilities))),
 (SELECT count(*) FROM rudo.referrals r WHERE EXISTS(SELECT 1 FROM rudo.staff() s WHERE r.facility_id=ANY(s.facilities)))
$$;
REVOKE ALL ON FUNCTION rudo.analytics() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION rudo.analytics() TO rudo_api;
