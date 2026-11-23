-- Firebase -> Supabase account migration ledger (every Firebase account, staff or not).
-- Target: cktfbpnxpfbyroqzuibc, applied as "postgres" in ONE transaction, after 20261121120000.
-- NOT applied. Production apply needs the owner's explicit approval.
--
-- Effect: a private schema (not exposed to the Data API) recording one row per Firebase account and its
-- outcome. No change to public.* (patients, messages, orders, referrals) and no new dashboard access:
-- access still exists only through observer_control.staff_identities, which this migration can extend
-- solely by copying an EXISTING Firebase staff link to the same internal staff id.
-- Login role rudo_migrator (password set separately, SCRAM) may only use this schema and the functions below.
-- Rollback: supabase/rollback/20261123063840_firebase_account_migration.down.sql

DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='observer_control') THEN
  RAISE EXCEPTION 'apply 20261121120000_rudo_staff_control first';
 END IF;
 IF EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='firebase_migration') THEN
  RAISE EXCEPTION 'firebase_migration already installed';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='rudo_migrator') THEN
  CREATE ROLE rudo_migrator LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;
 END IF;
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='rudo_migrator' AND (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole))
    OR EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member WHERE r.rolname='rudo_migrator') THEN
  RAISE EXCEPTION 'unsafe rudo_migrator role';
 END IF;
END $$;
ALTER ROLE rudo_migrator SET statement_timeout='30s';

CREATE SCHEMA firebase_migration;
REVOKE ALL ON SCHEMA firebase_migration FROM PUBLIC;
GRANT USAGE ON SCHEMA firebase_migration TO rudo_migrator;

CREATE TABLE firebase_migration.runs (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 firebase_project text NOT NULL,
 export_sha256 text NOT NULL CHECK(export_sha256 ~ '^[0-9a-f]{64}$'),
 mode text NOT NULL CHECK(mode IN ('dry_run','execute')),
 actor text NOT NULL CHECK(length(actor) BETWEEN 1 AND 120),
 started_at timestamptz NOT NULL DEFAULT now(),
 finished_at timestamptz,
 counts jsonb
);

CREATE TABLE firebase_migration.accounts (
 firebase_project text NOT NULL,
 firebase_uid text NOT NULL CHECK(length(firebase_uid) BETWEEN 1 AND 128),
 supabase_user_id uuid UNIQUE,                       -- no FK into auth: history survives user deletion
 planned_user_id uuid NOT NULL UNIQUE,              -- uuid5(project, uid): same id on every rerun
 email text, email_verified boolean NOT NULL, phone text, display_name text, photo_url text,
 disabled boolean NOT NULL, tenant_id text,
 providers text[] NOT NULL DEFAULT '{}',
 provider_identities jsonb NOT NULL DEFAULT '[]',   -- provider + provider uid + email; no tokens
 custom_claims jsonb NOT NULL DEFAULT '{}',         -- kept here, never copied into Supabase JWTs
 mfa_factor_types text[] NOT NULL DEFAULT '{}',
 firebase_created_at timestamptz, firebase_last_sign_in_at timestamptz,
 password_status text NOT NULL CHECK(password_status IN ('preserved','needs_setup','none')),
 status text NOT NULL CHECK(status IN ('staged','imported','manual','excluded_by_owner','failed')),
 remediation text[] NOT NULL DEFAULT '{}',
 staff_id uuid REFERENCES observer_control.staff(id),  -- only from an existing Firebase staff link
 source_sha256 text NOT NULL CHECK(source_sha256 ~ '^[0-9a-f]{64}$'),
 last_run uuid REFERENCES firebase_migration.runs(id),
 error_code text CHECK(length(error_code)<=80),
 updated_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(firebase_project,firebase_uid),
 CHECK(status<>'imported' OR supabase_user_id IS NOT NULL)
);
CREATE INDEX accounts_status_idx ON firebase_migration.accounts(firebase_project,status);
CREATE INDEX accounts_staff_idx ON firebase_migration.accounts(staff_id) WHERE staff_id IS NOT NULL;
CREATE INDEX accounts_run_idx ON firebase_migration.accounts(last_run);

CREATE TABLE firebase_migration.events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 run_id uuid NOT NULL REFERENCES firebase_migration.runs(id),
 firebase_uid text,
 event text NOT NULL CHECK(event ~ '^[a-z_]{1,60}$'),
 detail jsonb NOT NULL DEFAULT '{}',
 at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX events_run_idx ON firebase_migration.events(run_id);

CREATE FUNCTION firebase_migration.append_only() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'firebase_migration.events is append-only'; END $$;
CREATE TRIGGER events_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON firebase_migration.events
 FOR EACH STATEMENT EXECUTE FUNCTION firebase_migration.append_only();

ALTER TABLE firebase_migration.runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE firebase_migration.accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE firebase_migration.events ENABLE ROW LEVEL SECURITY;
-- The migrator is the only non-owner role with table access; it gets explicit policies.
CREATE POLICY migrator_all ON firebase_migration.runs TO rudo_migrator USING (true) WITH CHECK (true);
CREATE POLICY migrator_all ON firebase_migration.accounts TO rudo_migrator USING (true) WITH CHECK (true);
CREATE POLICY migrator_read ON firebase_migration.events FOR SELECT TO rudo_migrator USING (true);
CREATE POLICY migrator_append ON firebase_migration.events FOR INSERT TO rudo_migrator WITH CHECK (true);
GRANT SELECT,INSERT,UPDATE ON firebase_migration.runs,firebase_migration.accounts TO rudo_migrator;
GRANT SELECT,INSERT ON firebase_migration.events TO rudo_migrator;

-- Existing Firebase staff links (the only source of preserved dashboard access).
CREATE FUNCTION firebase_migration.firebase_staff_links(p_project text)
RETURNS TABLE(firebase_uid text,staff_id uuid,staff_status text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog AS $$
 SELECT i.subject,i.staff_id,s.status FROM observer_control.staff_identities i JOIN observer_control.staff s ON s.id=i.staff_id
 WHERE i.provider='firebase' AND i.issuer='https://securetoken.google.com/'||p_project
$$;

-- Copy an existing Firebase staff link to the imported Supabase identity: same internal staff id, so the
-- role, status and facility scopes are preserved exactly. Never creates staff or grants anything new.
CREATE FUNCTION firebase_migration.copy_staff_link(p_project text,p_uid text,p_supabase_issuer text,p_actor text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE a firebase_migration.accounts; sid uuid; done uuid;
BEGIN
 SELECT * INTO a FROM firebase_migration.accounts WHERE firebase_project=p_project AND firebase_uid=p_uid FOR UPDATE;
 IF a.supabase_user_id IS NULL OR a.status<>'imported' THEN RAISE EXCEPTION 'not_imported' USING ERRCODE='22023'; END IF;
 IF p_supabase_issuer !~ '^https://[a-z0-9]{20}\.supabase\.co/auth/v1$' AND p_supabase_issuer !~ '^http://127\.0\.0\.1:[0-9]+/auth/v1$' THEN
  RAISE EXCEPTION 'invalid_issuer' USING ERRCODE='22023';
 END IF;
 SELECT i.staff_id INTO sid FROM observer_control.staff_identities i
  WHERE i.provider='firebase' AND i.issuer='https://securetoken.google.com/'||p_project AND i.subject=p_uid;
 IF sid IS NULL THEN RETURN 'no_staff_link'; END IF;
 SELECT staff_id INTO done FROM observer_control.staff_identities WHERE issuer=p_supabase_issuer AND subject=a.supabase_user_id::text;
 IF done IS NOT NULL THEN RETURN CASE WHEN done=sid THEN 'already_linked' ELSE 'conflict_other_staff' END; END IF;
 INSERT INTO observer_control.staff_identities(issuer,subject,provider,staff_id,email,link_method,linked_by)
 VALUES(p_supabase_issuer,a.supabase_user_id::text,'supabase',sid,a.email,'auth_import',p_actor);
 INSERT INTO observer_control.staff_admin_events(actor,action,target,detail)
 VALUES(p_actor,'auth_import_link',sid::text,jsonb_build_object('firebase_uid',p_uid,'supabase_user_id',a.supabase_user_id));
 UPDATE firebase_migration.accounts SET staff_id=sid,updated_at=now() WHERE firebase_project=p_project AND firebase_uid=p_uid;
 RETURN 'linked';
END $$;

-- Pre-link an OAuth identity by the provider's own subject (e.g. Google 'sub'), never by email, so a
-- later Google sign-in resolves to the same imported user. Only for users this migration created.
CREATE FUNCTION firebase_migration.link_oauth_identity(p_project text,p_uid text,p_provider text,p_provider_uid text)
RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog AS $$
DECLARE a firebase_migration.accounts; owner uuid;
BEGIN
 IF p_provider NOT IN ('google') OR p_provider_uid !~ '^[0-9A-Za-z_.-]{1,255}$' THEN RAISE EXCEPTION 'invalid_identity' USING ERRCODE='22023'; END IF;
 SELECT * INTO a FROM firebase_migration.accounts WHERE firebase_project=p_project AND firebase_uid=p_uid;
 IF a.supabase_user_id IS NULL OR a.status<>'imported' THEN RAISE EXCEPTION 'not_imported' USING ERRCODE='22023'; END IF;
 IF NOT EXISTS(SELECT 1 FROM jsonb_array_elements(a.provider_identities) e
               WHERE e->>'provider'=p_provider||'.com' AND e->>'provider_uid'=p_provider_uid) THEN
  RAISE EXCEPTION 'identity_not_in_firebase_record' USING ERRCODE='22023';
 END IF;
 IF NOT EXISTS(SELECT 1 FROM auth.users u WHERE u.id=a.supabase_user_id AND u.raw_app_meta_data->>'firebase_uid'=p_uid) THEN
  RAISE EXCEPTION 'not_a_migrated_user' USING ERRCODE='22023';
 END IF;
 SELECT user_id INTO owner FROM auth.identities WHERE provider=p_provider AND provider_id=p_provider_uid;
 IF owner IS NOT NULL THEN RETURN CASE WHEN owner=a.supabase_user_id THEN 'already_linked' ELSE 'conflict_other_user' END; END IF;
 INSERT INTO auth.identities(provider_id,user_id,identity_data,provider,created_at,updated_at)
 VALUES(p_provider_uid,a.supabase_user_id,
        jsonb_strip_nulls(jsonb_build_object('sub',p_provider_uid,'provider_id',p_provider_uid,'email',
          (SELECT e->>'email' FROM jsonb_array_elements(a.provider_identities) e WHERE e->>'provider_uid'=p_provider_uid LIMIT 1),
          'email_verified',true,'iss','https://accounts.google.com')),
        p_provider,now(),now());
 RETURN 'linked';
END $$;

REVOKE ALL ON FUNCTION firebase_migration.firebase_staff_links(text),firebase_migration.copy_staff_link(text,text,text,text),
 firebase_migration.link_oauth_identity(text,text,text,text),firebase_migration.append_only() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION firebase_migration.firebase_staff_links(text),firebase_migration.copy_staff_link(text,text,text,text),
 firebase_migration.link_oauth_identity(text,text,text,text) TO rudo_migrator;
DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
   EXECUTE format('REVOKE ALL ON SCHEMA firebase_migration FROM %I',r);
   EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA firebase_migration FROM %I',r);
   EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA firebase_migration FROM %I',r);
   EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA firebase_migration FROM %I',r);
  END IF;
 END LOOP;
END $$;
ALTER DEFAULT PRIVILEGES IN SCHEMA firebase_migration REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA firebase_migration REVOKE ALL ON FUNCTIONS FROM PUBLIC;
