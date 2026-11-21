# Linked Supabase schema comparison and review gate

Inspected 2026-11-20. Project: `cktfbpnxpfbyroqzuibc`. Method: `supabase db query --linked --file scripts/inspect_remote_schema.sql --output json`. The script uses **BEGIN READ ONLY**, a statement timeout, catalog SELECTs and ROLLBACK. It does not read application rows, function bodies, column defaults, auth users or patient records. Only application-schema metadata was retained in [schema/remote-schema.json](schema/remote-schema.json); internal auth/storage metadata was discarded locally.

No remote DDL, migration push/pull/history repair, import, role/grant changes, table overwrite, Firebase/Meta changes or deployment was performed. Management API query execution is an authenticated SQL transport; using it for inspection does not authorize executing the proposed SQL.

## Confirmed remote state

| Existing public table | Primary key and columns | Compatibility impact |
|---|---|---|
| users | phone text PK; user_id, language, step, state jsonb, created_at, updated_at | Matches the newer bot's phone-based state model, not the proposed facility-scoped conversation model |
| user_state | user_id varchar PK; step/language/topic JSON, registered, phone_digits, needs_language_confirmation, first_message | A second state representation exists; purpose/active writer unresolved; do not merge or drop |
| messages | id bigint PK; phone, role, message, message_en, created_at | role CHECK accepts only user/bot; no provider ID, operation ID, conversation FK or delivery state; legacy unknown/system roles would fail a naive import |
| orders | id bigint PK; phone, user_id, product, price text, quantity int, address, status, created_at | No facility, optimistic version, source mapping, currency constraint or conversation relation |
| referrals | id bigint PK; phone, source, user_id, created_at | Source retained as text; no normalized clinic/campaign or facility scope |
| kv | key text PK; value text, expires_at timestamptz | Expiry-aware schema exists, but actual TTL semantics and expired-row cleanup were not inspected |

All six tables have RLS enabled, FORCE RLS disabled, and **zero RLS policies**. Metadata lists broad privileges for anon/authenticated/service_role/postgres. This does not prove anonymous row access: ordinary SELECT/INSERT/UPDATE/DELETE remain denied without RLS policies; bypass roles and operations not covered by RLS require separate review. No API calls were made to test access, and no grants were changed. There are no catalog-visible foreign keys among these tables and no public application functions. Existing indexes include messages(phone,id), kv(expires_at) and primary-key indexes. Row counts/data quality/default expressions were deliberately not queried.

## Comparison to the earlier proposal

The existing public tables resemble the newer bot's persistence contract and could already support a live service. Replacing them with CREATE TABLE statements, importing over their IDs, or adding dashboard access policies without ownership review would be unsafe. The local repository previously had no executable Rudo migrations; the earlier plan was a design specification.

The **new local draft** `supabase/migrations/202611200001_rudo_private.sql` creates a separate private `rudo` schema with staff_memberships, conversations, messages, orders, referrals, expiring_state, webhook_inbox, outbox, audit_events and migration_records. It neither alters nor writes public tables. It fails if that schema unexpectedly exists rather than silently hiding drift. Its local runner records migration checksums and skips unchanged applied files; SQL is not intended to be replayed blindly.

Key changes from the conceptual proposal are explicit:

- Existing public tables stay untouched; no automatic mirroring, live migration, or read-through of patient records is enabled.
- Firebase identities remain external. Staff authorization uses protected issuer/subject memberships and facility allowlists. Runtime uses server-only direct Postgres connections with non-BYPASSRLS roles; no Supabase third-party integration/custom claim change is needed for this local design.
- Database transaction context is set only after Firebase verification. The private schema is not exposed through PostgREST and grants nothing to anon/authenticated/service_role. No broad service key is used by the application.
- UUID conversations separate staff workflow state from existing public bigint/phone IDs. The importer preserves exact legacy source keys/JSON and deterministic UUID mappings; it does not infer patient merges.
- A patients/identifiers/clinic/campaign normalization layer is deferred until owner decisions resolve phone reuse, legacy identifiers and facility mapping. Current implementation keeps account-bound phone and raw source metadata; it must not be represented as the full normalized clinical record system.
- Inbox acceptance and local message persistence occur in one transaction. The implementation does not add AI replies or replace the authoritative bot. Outbound processing uses an explicit worker and operation ledger; uncertain sends require reconciliation.
- Temporarily expiring imported business records are quarantined into expiry-aware state rather than made permanent dashboard history. Promotion/reinterpretation requires retention review. This is preservation, not completed UX parity for expiring threads/orders.
- Analyst access is aggregate counts only. Operators/admins require explicit facilities; admin is not a global bypass. No source records are assigned to facilities automatically.

## Decisions required before remote execution

1. Confirm the live writer/deployed commit for each public table, especially user_state versus users.state, and the active WhatsApp callback/sender. The schema's resemblance to the public reference is not proof of deployment provenance.
2. Review whether to retain the isolated private schema, selectively extend the bot tables, or introduce an approved compatibility bridge. The supplied draft chooses isolation for review; it does not synchronize the two systems.
3. Approve staff roles/facility mappings, identity project, unassigned-record handling, retention/region and whether a separate staging project is required. No existing patient/facility assignment was read or inferred.
4. Approve runtime login provisioning: distinct non-superuser, non-BYPASSRLS logins with only rudo_api or rudo_worker membership. No password/login provisioning is included in the migration.
5. Obtain an approved consistent backup and schema/default/function/grant review before any actual migration; test restoration. Catalog metadata alone is not a validated backup.
6. Review migration SQL and mappings, stage synthetic smoke tests, and approve exact external actions separately. Do not run `supabase db push`, `db reset --linked`, remote imports or deployment as a consequence of this local implementation.

Remote writes and actual message delivery remain disabled by default. The application never reads Supabase CLI credentials or `.temp` connection data. CLI linking is used only by the explicitly read-only inspection script during this assignment.
