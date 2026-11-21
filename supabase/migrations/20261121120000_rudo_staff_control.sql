-- Rudo staff management + read-only dashboard access control.
-- Target: Supabase project cktfbpnxpfbyroqzuibc (PostgreSQL 17), applied as role "postgres" in ONE transaction.
--
-- What this changes in the existing bot schema (public): ONLY additive, scoped objects.
--   * SELECT policies "rudo_observer_read" on users/messages/orders/referrals, TO rudo_observer only.
--   * Column-level SELECT grants on those four tables to rudo_observer.
--   Nothing is granted on public.kv or public.user_state. No bot table, row, column, index, existing grant,
--   RLS setting or service_role permission is altered. The bot (service_role, BYPASSRLS) is unaffected.
--
-- New objects live in schema observer_control, which is NOT exposed through the Data API (PostgREST)
-- and gives anon/authenticated/service_role no privileges.
-- Login passwords are set out-of-band at release time (never in this file).
-- Rollback: supabase/rollback/20261121120000_rudo_staff_control.down.sql

DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='observer_control') THEN
  RAISE EXCEPTION 'observer_control already exists; refusing to re-apply';
 END IF;
 IF (SELECT count(*) FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind='r'
     AND relname IN ('users','messages','orders','referrals','kv','user_state'))<>6 THEN
  RAISE EXCEPTION 'expected the six existing bot tables in schema public';
 END IF;
END $$;

-- 1. Login roles: no superuser, no BYPASSRLS, no DDL, no inherited memberships.
DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['rudo_observer','rudo_observer_audit','rudo_staff_admin'] LOOP
  IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
   EXECUTE format('CREATE ROLE %I LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION',r);
  END IF;
 END LOOP;
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN ('rudo_observer','rudo_observer_audit','rudo_staff_admin')
           AND (rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolreplication)) THEN
  RAISE EXCEPTION 'unsafe rudo role attributes';
 END IF;
 IF EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
           WHERE r.rolname IN ('rudo_observer','rudo_observer_audit','rudo_staff_admin')) THEN
  RAISE EXCEPTION 'rudo roles must not be members of other roles';
 END IF;
END $$;
ALTER ROLE rudo_observer SET default_transaction_read_only=on;
ALTER ROLE rudo_observer SET statement_timeout='5s';
ALTER ROLE rudo_observer_audit SET statement_timeout='5s';
ALTER ROLE rudo_staff_admin SET statement_timeout='5s';

CREATE SCHEMA observer_control;
REVOKE ALL ON SCHEMA observer_control FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA observer_control REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
GRANT USAGE ON SCHEMA observer_control TO rudo_observer,rudo_observer_audit,rudo_staff_admin;

-- 2. Facilities and accounts that staff can be scoped to.
CREATE TABLE observer_control.facilities (
 source_id text NOT NULL,account_id text NOT NULL,facility_id text NOT NULL,
 display_name text NOT NULL CHECK(length(display_name) BETWEEN 1 AND 200),
 active boolean NOT NULL DEFAULT true,created_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(source_id,account_id,facility_id),
 CHECK(source_id ~ '^[a-z0-9][a-z0-9_.-]{0,63}$' AND account_id ~ '^[a-z0-9][a-z0-9_.-]{0,63}$' AND facility_id ~ '^[a-z0-9][a-z0-9_.-]{0,63}$')
);

-- 3. Staff: one internal id per person, independent of login provider.
CREATE TABLE observer_control.staff (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 email text NOT NULL CHECK(email ~ '^[^@\s]+@[^@\s]+$' AND length(email)<=254),
 display_name text CHECK(length(display_name)<=200),
 role text NOT NULL CHECK(role IN ('admin','operator','analyst')),
 status text NOT NULL DEFAULT 'active' CHECK(status IN ('active','suspended')),
 created_by text NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX staff_email_unique ON observer_control.staff(lower(email));

-- Login identities (Firebase UID, Supabase Auth UUID) mapped to the internal staff id.
CREATE TABLE observer_control.staff_identities (
 issuer text NOT NULL,subject text NOT NULL,
 provider text NOT NULL CHECK(provider IN ('firebase','supabase')),
 staff_id uuid NOT NULL REFERENCES observer_control.staff(id),
 email text,link_method text NOT NULL CHECK(link_method IN ('bootstrap','invitation','auth_import')),
 linked_by text NOT NULL,linked_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(issuer,subject),UNIQUE(staff_id,issuer)
);

CREATE TABLE observer_control.staff_scopes (
 staff_id uuid NOT NULL REFERENCES observer_control.staff(id),
 source_id text NOT NULL,account_id text NOT NULL,facility_id text NOT NULL,
 granted_by text NOT NULL,granted_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(staff_id,source_id,account_id,facility_id),
 FOREIGN KEY(source_id,account_id,facility_id) REFERENCES observer_control.facilities
);

-- Invitations: an admin pre-approves role + scopes (or a link to an existing staff member) for an email.
-- Accepting requires a separately verified sign-in with that email AND an explicit admin approval.
CREATE TABLE observer_control.staff_invitations (
 id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 email text NOT NULL CHECK(email ~ '^[^@\s]+@[^@\s]+$' AND length(email)<=254),
 role text CHECK(role IN ('admin','operator','analyst')),
 scopes jsonb NOT NULL DEFAULT '[]'::jsonb CHECK(jsonb_typeof(scopes)='array'),
 staff_id uuid REFERENCES observer_control.staff(id),
 status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','revoked')),
 invited_by text NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL DEFAULT now()+interval '14 days',
 accepted_at timestamptz,accepted_issuer text,accepted_subject text,
 CHECK((staff_id IS NULL)=(role IS NOT NULL))
);
CREATE UNIQUE INDEX one_pending_invitation_per_email ON observer_control.staff_invitations(lower(email)) WHERE status='pending';

-- Verified sign-ins that have no staff link yet (pending). Grants nothing by itself.
CREATE TABLE observer_control.identity_requests (
 issuer text NOT NULL,subject text NOT NULL,provider text NOT NULL CHECK(provider IN ('firebase','supabase')),
 email text,email_verified boolean NOT NULL DEFAULT false,
 first_seen timestamptz NOT NULL DEFAULT now(),last_seen timestamptz NOT NULL DEFAULT now(),
 attempts integer NOT NULL DEFAULT 1,PRIMARY KEY(issuer,subject)
);

-- 4. Owner-approved phone -> account/facility mappings. Unmapped or ambiguous phones stay invisible.
CREATE TABLE observer_control.source_mappings (
 source_id text NOT NULL,phone text NOT NULL,account_id text NOT NULL,facility_id text NOT NULL,
 approved boolean NOT NULL DEFAULT false,method text NOT NULL DEFAULT 'manual',
 approved_by text,approved_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(source_id,phone,account_id,facility_id),
 FOREIGN KEY(source_id,account_id,facility_id) REFERENCES observer_control.facilities
);
CREATE INDEX source_scope_idx ON observer_control.source_mappings(source_id,account_id,facility_id,phone) WHERE approved;
CREATE INDEX source_phone_idx ON observer_control.source_mappings(source_id,phone) WHERE approved;

-- 5. Audit: data access (append-only via its own credential) and privileged staff actions (append-only).
CREATE TABLE observer_control.access_audit (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 issuer text NOT NULL,subject text NOT NULL,source_id text NOT NULL,
 action text NOT NULL CHECK(action IN ('membership','conversations','history','orders','referrals','analytics','staff_admin')),
 resource_digest text,rows_returned integer NOT NULL CHECK(rows_returned>=0),recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE observer_control.staff_admin_events (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 actor text NOT NULL,action text NOT NULL,target text NOT NULL,detail jsonb NOT NULL DEFAULT '{}'::jsonb,
 recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE FUNCTION observer_control.forbid_change() RETURNS trigger LANGUAGE plpgsql SET search_path=pg_catalog AS $$
BEGIN RAISE EXCEPTION 'append-only table'; END $$;
-- Statement-level, so UPDATE/DELETE/TRUNCATE are refused even when no row matches (owner included).
CREATE TRIGGER staff_admin_events_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON observer_control.staff_admin_events
 FOR EACH STATEMENT EXECUTE FUNCTION observer_control.forbid_change();
CREATE TRIGGER access_audit_append_only BEFORE UPDATE OR DELETE OR TRUNCATE ON observer_control.access_audit
 FOR EACH STATEMENT EXECUTE FUNCTION observer_control.forbid_change();

ALTER TABLE observer_control.facilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE observer_control.staff ENABLE ROW LEVEL SECURITY;
ALTER TABLE observer_control.staff_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE observer_control.staff_scopes ENABLE ROW LEVEL SECURITY;
ALTER TABLE observer_control.staff_invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE observer_control.identity_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE observer_control.source_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE observer_control.access_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE observer_control.staff_admin_events ENABLE ROW LEVEL SECURITY;

-- 6. Request identity -> active staff id. The Flask server sets observer.issuer/subject/source per
-- transaction only after verifying the Firebase or Supabase token. Suspended staff resolve to NULL.
CREATE FUNCTION observer_control.current_staff() RETURNS uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
 SELECT i.staff_id FROM observer_control.staff_identities i JOIN observer_control.staff s ON s.id=i.staff_id
 WHERE s.status='active' AND i.issuer=current_setting('observer.issuer',true) AND i.subject=current_setting('observer.subject',true)
$$;
CREATE POLICY staff_self ON observer_control.staff FOR SELECT TO rudo_observer USING(id=observer_control.current_staff());
CREATE POLICY scopes_self ON observer_control.staff_scopes FOR SELECT TO rudo_observer USING(staff_id=observer_control.current_staff());
CREATE POLICY facilities_read ON observer_control.facilities FOR SELECT TO rudo_observer USING(true);
GRANT SELECT(id,email,display_name,role,status) ON observer_control.staff TO rudo_observer;
GRANT SELECT ON observer_control.staff_scopes,observer_control.facilities TO rudo_observer;

-- Approved, unambiguous source rows for the current staff member. Raw access needs admin/operator.
CREATE FUNCTION observer_control.scopes(raw_access boolean DEFAULT true)
RETURNS TABLE(source_id text,phone text,account_id text,facility_id text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
 SELECT m.source_id,m.phone,m.account_id,m.facility_id
 FROM observer_control.source_mappings m
 JOIN observer_control.staff_scopes s USING(source_id,account_id,facility_id)
 JOIN observer_control.staff st ON st.id=s.staff_id
 JOIN observer_control.facilities f USING(source_id,account_id,facility_id)
 WHERE st.id=observer_control.current_staff() AND f.active AND (NOT raw_access OR st.role IN ('admin','operator'))
 AND m.source_id=current_setting('observer.source',true) AND m.approved
 AND 1=(SELECT count(*) FROM observer_control.source_mappings x WHERE x.source_id=m.source_id AND x.phone=m.phone AND x.approved)
$$;
CREATE FUNCTION observer_control.visible_scopes()
RETURNS TABLE(source_id text,phone text,account_id text,facility_id text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
 SELECT * FROM observer_control.scopes(true)
$$;
CREATE FUNCTION observer_control.visible(phone_value text) RETURNS boolean
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
 SELECT EXISTS(SELECT 1 FROM observer_control.scopes(true) s WHERE s.phone=phone_value)
$$;
-- Aggregates are the only public-data interface for analysts. Fixed query, scoped, no dynamic SQL.
CREATE FUNCTION observer_control.counts(account_filter text DEFAULT NULL,facility_filter text DEFAULT NULL)
RETURNS TABLE(source_users bigint,conversations bigint,captured_messages bigint,orders bigint,referrals bigint)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
 WITH allowed AS MATERIALIZED (SELECT * FROM observer_control.scopes(false) s
  WHERE (account_filter IS NULL OR s.account_id=account_filter) AND (facility_filter IS NULL OR s.facility_id=facility_filter))
 SELECT
 (SELECT count(*) FROM public.users u JOIN allowed a USING(phone)),
 (SELECT count(*) FROM allowed a WHERE EXISTS(SELECT 1 FROM public.users u WHERE u.phone=a.phone) OR EXISTS(SELECT 1 FROM public.messages m WHERE m.phone=a.phone)),
 (SELECT count(*) FROM public.messages m JOIN allowed a USING(phone)),
 (SELECT count(*) FROM public.orders o JOIN allowed a USING(phone)),
 (SELECT count(*) FROM public.referrals r JOIN allowed a USING(phone))
$$;

-- 7. Additive read path on the bot tables for rudo_observer only: approved rows, minimal columns.
CREATE POLICY rudo_observer_read ON public.users FOR SELECT TO rudo_observer USING(observer_control.visible(phone));
CREATE POLICY rudo_observer_read ON public.messages FOR SELECT TO rudo_observer USING(observer_control.visible(phone));
CREATE POLICY rudo_observer_read ON public.orders FOR SELECT TO rudo_observer USING(observer_control.visible(phone));
CREATE POLICY rudo_observer_read ON public.referrals FOR SELECT TO rudo_observer USING(observer_control.visible(phone));
GRANT USAGE ON SCHEMA public TO rudo_observer;
GRANT SELECT(phone,user_id,language,created_at,updated_at) ON public.users TO rudo_observer;
GRANT SELECT(id,phone,role,message,created_at) ON public.messages TO rudo_observer;
GRANT SELECT(id,phone,product,price,quantity,status,created_at) ON public.orders TO rudo_observer;
GRANT SELECT(id,phone,source,created_at) ON public.referrals TO rudo_observer;

-- 8. Append-only access audit and pending sign-in recording (separate credential).
CREATE POLICY audit_append ON observer_control.access_audit FOR INSERT TO rudo_observer_audit WITH CHECK(true);
GRANT INSERT(issuer,subject,source_id,action,resource_digest,rows_returned) ON observer_control.access_audit TO rudo_observer_audit;
CREATE FUNCTION observer_control.record_identity_request(p_issuer text,p_subject text,p_provider text,p_email text,p_verified boolean)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
BEGIN
 IF length(p_issuer)>300 OR length(p_subject)>200 OR length(p_email)>254 THEN RAISE EXCEPTION 'invalid identity'; END IF;
 IF EXISTS(SELECT 1 FROM observer_control.staff_identities WHERE issuer=p_issuer AND subject=p_subject) THEN RETURN; END IF;
 INSERT INTO observer_control.identity_requests(issuer,subject,provider,email,email_verified)
 VALUES(p_issuer,p_subject,p_provider,lower(p_email),coalesce(p_verified,false))
 ON CONFLICT(issuer,subject) DO UPDATE SET last_seen=now(),attempts=observer_control.identity_requests.attempts+1,
  email=EXCLUDED.email,email_verified=EXCLUDED.email_verified;
END $$;

-- 9. Staff administration. Every function re-checks, inside the database, that the verified request
-- identity is an ACTIVE ADMIN, limits scopes to the admin's own facilities and appends an event.
CREATE FUNCTION observer_control.require_admin() RETURNS uuid
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
DECLARE v uuid;
BEGIN
 SELECT s.id INTO v FROM observer_control.staff s WHERE s.id=observer_control.current_staff() AND s.role='admin';
 IF v IS NULL THEN RAISE EXCEPTION 'admin_required' USING ERRCODE='42501'; END IF;
 RETURN v;
END $$;
CREATE FUNCTION observer_control.admin_event(p_actor uuid,p_action text,p_target text,p_detail jsonb) RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
 INSERT INTO observer_control.staff_admin_events(actor,action,target,detail) VALUES(p_actor::text,p_action,p_target,p_detail)
$$;
-- Validates [{"account":..,"facility":..}] against existing facilities in the admin's own scopes.
CREATE FUNCTION observer_control.admin_scopes(p_admin uuid,p_scopes jsonb)
RETURNS TABLE(source_id text,account_id text,facility_id text)
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
DECLARE item jsonb; src text:=current_setting('observer.source',true);
BEGIN
 IF jsonb_typeof(p_scopes)<>'array' OR jsonb_array_length(p_scopes)>100 THEN RAISE EXCEPTION 'invalid_scopes' USING ERRCODE='22023'; END IF;
 FOR item IN SELECT * FROM jsonb_array_elements(p_scopes) LOOP
  IF NOT EXISTS(SELECT 1 FROM observer_control.staff_scopes s WHERE s.staff_id=p_admin AND s.source_id=src
                AND s.account_id=item->>'account' AND s.facility_id=item->>'facility') THEN
   RAISE EXCEPTION 'scope_not_permitted' USING ERRCODE='42501';
  END IF;
  source_id:=src;account_id:=item->>'account';facility_id:=item->>'facility';RETURN NEXT;
 END LOOP;
END $$;

CREATE FUNCTION observer_control.admin_overview() RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
DECLARE a uuid:=observer_control.require_admin(); src text:=current_setting('observer.source',true);
BEGIN
 RETURN jsonb_build_object(
  'facilities',(SELECT coalesce(jsonb_agg(jsonb_build_object('account',f.account_id,'facility',f.facility_id,'name',f.display_name) ORDER BY f.display_name),'[]')
     FROM observer_control.facilities f JOIN observer_control.staff_scopes s USING(source_id,account_id,facility_id)
     WHERE s.staff_id=a AND f.source_id=src AND f.active),
  'staff',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',s.id,'email',s.email,'name',s.display_name,'role',s.role,'status',s.status,'created_at',s.created_at,
     'identities',(SELECT coalesce(jsonb_agg(jsonb_build_object('provider',i.provider,'issuer',i.issuer,'subject',i.subject,'email',i.email,'method',i.link_method) ORDER BY i.provider),'[]') FROM observer_control.staff_identities i WHERE i.staff_id=s.id),
     'scopes',(SELECT coalesce(jsonb_agg(jsonb_build_object('account',c.account_id,'facility',c.facility_id) ORDER BY c.account_id,c.facility_id),'[]') FROM observer_control.staff_scopes c WHERE c.staff_id=s.id AND c.source_id=src),
     'self',s.id=a) ORDER BY s.status,s.email),'[]') FROM observer_control.staff s),
  'invitations',(SELECT coalesce(jsonb_agg(jsonb_build_object('id',v.id,'email',v.email,'role',v.role,'scopes',v.scopes,'staff_id',v.staff_id,
     'expires_at',v.expires_at,'expired',v.expires_at<now(),'invited_by',v.invited_by) ORDER BY v.created_at DESC),'[]')
     FROM observer_control.staff_invitations v WHERE v.status='pending'),
  'requests',(SELECT coalesce(jsonb_agg(jsonb_build_object('issuer',r.issuer,'subject',r.subject,'provider',r.provider,'email',r.email,
     'email_verified',r.email_verified,'last_seen',r.last_seen,'attempts',r.attempts) ORDER BY r.last_seen DESC),'[]')
     FROM observer_control.identity_requests r WHERE NOT EXISTS(SELECT 1 FROM observer_control.staff_identities i WHERE i.issuer=r.issuer AND i.subject=r.subject)),
  'events',(SELECT coalesce(jsonb_agg(jsonb_build_object('actor',e.actor,'action',e.action,'target',e.target,'detail',e.detail,'at',e.recorded_at) ORDER BY e.id DESC),'[]')
     FROM (SELECT * FROM observer_control.staff_admin_events ORDER BY id DESC LIMIT 50) e));
END $$;

CREATE FUNCTION observer_control.admin_invite(p_email text,p_role text,p_scopes jsonb,p_staff uuid DEFAULT NULL) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
DECLARE a uuid:=observer_control.require_admin(); v uuid;
BEGIN
 IF p_staff IS NULL THEN
  IF p_role NOT IN ('admin','operator','analyst') THEN RAISE EXCEPTION 'invalid_role' USING ERRCODE='22023'; END IF;
  IF jsonb_array_length(p_scopes)=0 THEN RAISE EXCEPTION 'scope_required' USING ERRCODE='22023'; END IF;
  PERFORM count(*) FROM observer_control.admin_scopes(a,p_scopes);
  IF EXISTS(SELECT 1 FROM observer_control.staff WHERE lower(email)=lower(p_email)) THEN RAISE EXCEPTION 'staff_exists' USING ERRCODE='23505'; END IF;
  INSERT INTO observer_control.staff_invitations(email,role,scopes,invited_by) VALUES(lower(p_email),p_role,p_scopes,a::text) RETURNING id INTO v;
 ELSE
  -- Link an additional login (e.g. Supabase Auth during the transition) to an existing staff member.
  IF NOT EXISTS(SELECT 1 FROM observer_control.staff WHERE id=p_staff AND lower(email)=lower(p_email)) THEN
   RAISE EXCEPTION 'staff_email_mismatch' USING ERRCODE='22023';
  END IF;
  INSERT INTO observer_control.staff_invitations(email,staff_id,invited_by) VALUES(lower(p_email),p_staff,a::text) RETURNING id INTO v;
 END IF;
 PERFORM observer_control.admin_event(a,'invite',lower(p_email),jsonb_build_object('invitation',v,'role',p_role,'scopes',p_scopes,'staff_id',p_staff));
 RETURN v;
END $$;

-- Approve = pair ONE verified pending sign-in with ONE pending invitation for the same email.
CREATE FUNCTION observer_control.admin_approve(p_invitation uuid,p_issuer text,p_subject text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
DECLARE a uuid:=observer_control.require_admin(); inv observer_control.staff_invitations; req observer_control.identity_requests; sid uuid;
BEGIN
 SELECT * INTO inv FROM observer_control.staff_invitations WHERE id=p_invitation FOR UPDATE;
 IF inv.id IS NULL OR inv.status<>'pending' THEN RAISE EXCEPTION 'invitation_not_pending' USING ERRCODE='22023'; END IF;
 IF inv.expires_at<now() THEN RAISE EXCEPTION 'invitation_expired' USING ERRCODE='22023'; END IF;
 SELECT * INTO req FROM observer_control.identity_requests WHERE issuer=p_issuer AND subject=p_subject;
 IF req.issuer IS NULL THEN RAISE EXCEPTION 'sign_in_required' USING ERRCODE='22023'; END IF;
 IF NOT req.email_verified THEN RAISE EXCEPTION 'email_not_verified' USING ERRCODE='22023'; END IF;
 IF lower(req.email)<>lower(inv.email) THEN RAISE EXCEPTION 'email_mismatch' USING ERRCODE='22023'; END IF;
 IF EXISTS(SELECT 1 FROM observer_control.staff_identities WHERE issuer=p_issuer AND subject=p_subject) THEN
  RAISE EXCEPTION 'identity_already_linked' USING ERRCODE='23505';
 END IF;
 IF inv.staff_id IS NULL THEN
  INSERT INTO observer_control.staff(email,role,created_by) VALUES(inv.email,inv.role,a::text) RETURNING id INTO sid;
  INSERT INTO observer_control.staff_scopes(staff_id,source_id,account_id,facility_id,granted_by)
   SELECT sid,s.source_id,s.account_id,s.facility_id,a::text FROM observer_control.admin_scopes(a,inv.scopes) s;
 ELSE
  sid:=inv.staff_id;
  IF EXISTS(SELECT 1 FROM observer_control.staff_identities WHERE staff_id=sid AND issuer=p_issuer) THEN
   RAISE EXCEPTION 'provider_already_linked' USING ERRCODE='23505';
  END IF;
 END IF;
 INSERT INTO observer_control.staff_identities(issuer,subject,provider,staff_id,email,link_method,linked_by)
 VALUES(p_issuer,p_subject,req.provider,sid,req.email,'invitation',a::text);
 UPDATE observer_control.staff_invitations SET status='accepted',accepted_at=now(),accepted_issuer=p_issuer,accepted_subject=p_subject WHERE id=inv.id;
 DELETE FROM observer_control.identity_requests WHERE issuer=p_issuer AND subject=p_subject;
 PERFORM observer_control.admin_event(a,'approve',sid::text,jsonb_build_object('invitation',inv.id,'provider',req.provider,'issuer',p_issuer,'subject',p_subject));
 RETURN sid;
END $$;

CREATE FUNCTION observer_control.admin_update_staff(p_staff uuid,p_role text DEFAULT NULL,p_status text DEFAULT NULL,p_scopes jsonb DEFAULT NULL)
RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
DECLARE a uuid:=observer_control.require_admin(); src text:=current_setting('observer.source',true); target observer_control.staff;
BEGIN
 SELECT * INTO target FROM observer_control.staff WHERE id=p_staff FOR UPDATE;
 IF target.id IS NULL THEN RAISE EXCEPTION 'not_found' USING ERRCODE='22023'; END IF;
 IF p_staff=a THEN RAISE EXCEPTION 'cannot_change_self' USING ERRCODE='42501'; END IF;
 IF p_role IS NOT NULL AND p_role NOT IN ('admin','operator','analyst') THEN RAISE EXCEPTION 'invalid_role' USING ERRCODE='22023'; END IF;
 IF p_status IS NOT NULL AND p_status NOT IN ('active','suspended') THEN RAISE EXCEPTION 'invalid_status' USING ERRCODE='22023'; END IF;
 UPDATE observer_control.staff SET role=coalesce(p_role,role),status=coalesce(p_status,status),updated_at=now() WHERE id=p_staff;
 IF p_scopes IS NOT NULL THEN
  -- Replace only the scopes this admin controls; scopes outside the admin's facilities are preserved.
  DELETE FROM observer_control.staff_scopes s WHERE s.staff_id=p_staff AND s.source_id=src
   AND EXISTS(SELECT 1 FROM observer_control.staff_scopes m WHERE m.staff_id=a AND m.source_id=s.source_id AND m.account_id=s.account_id AND m.facility_id=s.facility_id);
  INSERT INTO observer_control.staff_scopes(staff_id,source_id,account_id,facility_id,granted_by)
   SELECT p_staff,s.source_id,s.account_id,s.facility_id,a::text FROM observer_control.admin_scopes(a,p_scopes) s ON CONFLICT DO NOTHING;
 END IF;
 IF NOT EXISTS(SELECT 1 FROM observer_control.staff WHERE role='admin' AND status='active') THEN
  RAISE EXCEPTION 'last_admin' USING ERRCODE='42501';
 END IF;
 PERFORM observer_control.admin_event(a,'update',p_staff::text,jsonb_build_object('role',p_role,'status',p_status,'scopes',p_scopes));
END $$;

CREATE FUNCTION observer_control.admin_revoke_invitation(p_invitation uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
DECLARE a uuid:=observer_control.require_admin();
BEGIN
 UPDATE observer_control.staff_invitations SET status='revoked' WHERE id=p_invitation AND status='pending';
 IF NOT FOUND THEN RAISE EXCEPTION 'invitation_not_pending' USING ERRCODE='22023'; END IF;
 PERFORM observer_control.admin_event(a,'revoke_invitation',p_invitation::text,'{}'::jsonb);
END $$;

CREATE FUNCTION observer_control.admin_unlink_identity(p_issuer text,p_subject text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
DECLARE a uuid:=observer_control.require_admin(); sid uuid;
BEGIN
 IF p_issuer=current_setting('observer.issuer',true) AND p_subject=current_setting('observer.subject',true) THEN
  RAISE EXCEPTION 'cannot_change_self' USING ERRCODE='42501';
 END IF;
 DELETE FROM observer_control.staff_identities WHERE issuer=p_issuer AND subject=p_subject RETURNING staff_id INTO sid;
 IF sid IS NULL THEN RAISE EXCEPTION 'not_found' USING ERRCODE='22023'; END IF;
 PERFORM observer_control.admin_event(a,'unlink',sid::text,jsonb_build_object('issuer',p_issuer,'subject',p_subject));
END $$;

CREATE FUNCTION observer_control.admin_dismiss_request(p_issuer text,p_subject text) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,observer_control AS $$
DECLARE a uuid:=observer_control.require_admin();
BEGIN
 DELETE FROM observer_control.identity_requests WHERE issuer=p_issuer AND subject=p_subject;
 IF NOT FOUND THEN RAISE EXCEPTION 'not_found' USING ERRCODE='22023'; END IF;
 PERFORM observer_control.admin_event(a,'dismiss_request',p_subject,jsonb_build_object('issuer',p_issuer));
END $$;

-- 10. Execute grants: nothing to PUBLIC; each login role gets exactly its functions.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA observer_control FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA observer_control FROM PUBLIC;
GRANT EXECUTE ON FUNCTION observer_control.current_staff(),observer_control.visible(text),observer_control.visible_scopes(),
 observer_control.counts(text,text) TO rudo_observer;
GRANT EXECUTE ON FUNCTION observer_control.record_identity_request(text,text,text,text,boolean) TO rudo_observer_audit;
GRANT EXECUTE ON FUNCTION observer_control.admin_overview(),observer_control.admin_invite(text,text,jsonb,uuid),
 observer_control.admin_approve(uuid,text,text),observer_control.admin_update_staff(uuid,text,text,jsonb),
 observer_control.admin_revoke_invitation(uuid),observer_control.admin_unlink_identity(text,text),
 observer_control.admin_dismiss_request(text,text) TO rudo_staff_admin;

-- Supabase API roles get nothing in this schema (explicit, even though the schema is not exposed).
DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
   EXECUTE format('REVOKE ALL ON SCHEMA observer_control FROM %I',r);
   EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA observer_control FROM %I',r);
   EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA observer_control FROM %I',r);
   EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA observer_control FROM %I',r);
  END IF;
 END LOOP;
END $$;
