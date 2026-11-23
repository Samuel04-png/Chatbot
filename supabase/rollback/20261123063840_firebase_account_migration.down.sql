-- Rollback of 20261123063840_firebase_account_migration (run as "postgres" in ONE transaction).
-- Order: FIRST remove migrated Supabase Auth users with scripts/migrate_firebase_auth.py rollback
-- (admin API; it deletes only users whose app_metadata.migrated_from='firebase' AND whose id is in the ledger),
-- THEN run this file. Copied staff links (link_method='auth_import') are removed here; the original
-- Firebase staff links, staff records, scopes and all public.* data are untouched.
DELETE FROM observer_control.staff_identities WHERE link_method='auth_import' AND provider='supabase'
 AND subject IN (SELECT supabase_user_id::text FROM firebase_migration.accounts WHERE supabase_user_id IS NOT NULL);
DROP SCHEMA firebase_migration CASCADE;
REVOKE ALL ON SCHEMA observer_control FROM rudo_migrator;
DROP ROLE IF EXISTS rudo_migrator;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='firebase_migration') OR EXISTS(SELECT 1 FROM pg_roles WHERE rolname='rudo_migrator') THEN
  RAISE EXCEPTION 'rollback incomplete';
 END IF;
END $$;
