-- Rollback of 20261123085525_firebase_data_landing (run as "postgres" in ONE transaction).
-- Removes only the landed Firebase copies; Firebase itself and all public.* data are untouched.
DROP SCHEMA firebase_import CASCADE;
ALTER TABLE firebase_migration.accounts DROP COLUMN owner_app;
DO $$ BEGIN
 IF EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='firebase_import') THEN RAISE EXCEPTION 'rollback incomplete'; END IF;
END $$;
