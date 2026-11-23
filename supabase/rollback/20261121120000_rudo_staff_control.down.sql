-- Rollback for 20261121120000_rudo_staff_control.sql. Run as "postgres" in ONE transaction.
-- Removes ONLY what the migration added. Bot tables, rows, existing grants, RLS settings and
-- service_role access are untouched. Staff records/audit are DELETED: export them first
-- (see docs/release/RELEASE_1.md, "Before rollback").
BEGIN;
DROP POLICY IF EXISTS rudo_observer_read ON public.users;
DROP POLICY IF EXISTS rudo_observer_read ON public.messages;
DROP POLICY IF EXISTS rudo_observer_read ON public.orders;
DROP POLICY IF EXISTS rudo_observer_read ON public.referrals;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='rudo_observer') THEN
  REVOKE ALL ON public.users,public.messages,public.orders,public.referrals FROM rudo_observer;
  REVOKE SELECT(phone,user_id,language,created_at,updated_at) ON public.users FROM rudo_observer;
  REVOKE SELECT(id,phone,role,message,created_at) ON public.messages FROM rudo_observer;
  REVOKE SELECT(id,phone,product,price,quantity,status,created_at) ON public.orders FROM rudo_observer;
  REVOKE SELECT(id,phone,source,created_at) ON public.referrals FROM rudo_observer;
  REVOKE USAGE ON SCHEMA public FROM rudo_observer;
 END IF;
END $$;
DROP SCHEMA IF EXISTS observer_control CASCADE;
DROP ROLE IF EXISTS rudo_observer;
DROP ROLE IF EXISTS rudo_observer_audit;
DROP ROLE IF EXISTS rudo_staff_admin;
DROP ROLE IF EXISTS rudo_sender;  -- Created by 20261121150000 (staff replies), if applied.
-- Post-condition checks: fail (and roll back) if anything remains.
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_policies WHERE schemaname='public' AND policyname='rudo_observer_read') THEN RAISE EXCEPTION 'policy remains'; END IF;
 IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname IN ('rudo_observer','rudo_observer_audit','rudo_staff_admin','rudo_sender')) THEN RAISE EXCEPTION 'role remains'; END IF;
 IF EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='observer_control') THEN RAISE EXCEPTION 'schema remains'; END IF;
END $$;
COMMIT;
