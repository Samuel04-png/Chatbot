-- Firebase application data (Firestore) landed in Rudo's project, kept SEPARATE from Rudo's own tables.
-- Target: cktfbpnxpfbyroqzuibc, applied as "postgres" in ONE transaction, after 20261123063840.
-- NOT applied. Production apply needs the owner's explicit approval.
--
-- Every Firestore document (all collections and sub-collections) becomes one row keyed by its full original
-- path, with the original id, parent path, timestamps, owning application and the document data as typed
-- JSON. Nothing here writes to public.* (Rudo patients, messages, orders, referrals) or grants dashboard
-- access. The schema is private: not exposed to the Data API; anon/authenticated/service_role have no access.
-- Owning application per account is also recorded on firebase_migration.accounts.owner_app.
-- Rollback: supabase/rollback/20261123085525_firebase_data_landing.down.sql

DO $$ BEGIN
 IF NOT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='firebase_migration') THEN
  RAISE EXCEPTION 'apply 20261123063840_firebase_account_migration first';
 END IF;
 IF EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='firebase_import') THEN
  RAISE EXCEPTION 'firebase_import already installed';
 END IF;
END $$;

ALTER TABLE firebase_migration.accounts
 ADD COLUMN owner_app text NOT NULL DEFAULT 'unknown' CHECK(owner_app ~ '^[a-z_]{1,40}$');

CREATE SCHEMA firebase_import;
REVOKE ALL ON SCHEMA firebase_import FROM PUBLIC;
GRANT USAGE ON SCHEMA firebase_import TO rudo_migrator;

CREATE TABLE firebase_import.documents (
 firebase_project text NOT NULL,
 database_id text NOT NULL DEFAULT '(default)',
 path text NOT NULL CHECK(length(path) BETWEEN 3 AND 6144),       -- e.g. mobile_chats/abc/messages/xyz
 collection_id text NOT NULL,                                     -- e.g. messages
 collection_path text NOT NULL,                                   -- e.g. mobile_chats/abc/messages
 doc_id text NOT NULL,
 parent_path text,                                                -- parent document path (sub-collections)
 owner_app text NOT NULL CHECK(owner_app ~ '^[a-z_]{1,40}$'),
 data jsonb NOT NULL,                                             -- typed: timestamps/refs/geo/bytes tagged
 firebase_create_time timestamptz,
 firebase_update_time timestamptz,
 content_sha256 text NOT NULL CHECK(content_sha256 ~ '^[0-9a-f]{64}$'),
 last_run uuid NOT NULL REFERENCES firebase_migration.runs(id),
 imported_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(firebase_project,database_id,path)
);
CREATE INDEX documents_collection_idx ON firebase_import.documents(firebase_project,collection_path);
CREATE INDEX documents_owner_idx ON firebase_import.documents(owner_app,collection_id);
CREATE INDEX documents_parent_idx ON firebase_import.documents(parent_path) WHERE parent_path IS NOT NULL;
CREATE INDEX documents_run_idx ON firebase_import.documents(last_run);

ALTER TABLE firebase_import.documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY migrator_all ON firebase_import.documents TO rudo_migrator USING (true) WITH CHECK (true);
GRANT SELECT,INSERT,UPDATE ON firebase_import.documents TO rudo_migrator;

DO $$ DECLARE r text; BEGIN
 FOREACH r IN ARRAY ARRAY['anon','authenticated','service_role'] LOOP
  IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname=r) THEN
   EXECUTE format('REVOKE ALL ON SCHEMA firebase_import FROM %I',r);
   EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA firebase_import FROM %I',r);
  END IF;
 END LOOP;
END $$;
ALTER DEFAULT PRIVILEGES IN SCHEMA firebase_import REVOKE ALL ON TABLES FROM PUBLIC;
