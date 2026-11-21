# Current migration review plan

Local implementation is complete and tested as recorded in [LOCAL_IMPLEMENTATION.md](LOCAL_IMPLEMENTATION.md) and [LOCAL_TEST_RESULTS.md](LOCAL_TEST_RESULTS.md). **No remote migration, real-data import, table replacement or deployment has been executed.**

Review these concrete artifacts before approving any external change:

1. [Remote schema differences](REMOTE_SCHEMA_COMPARISON.md) and [metadata snapshot](schema/remote-schema.json).
2. [Private-schema SQL draft](../supabase/migrations/202611200001_rudo_private.sql): creates new rudo objects only; existing public bot tables remain unchanged.
3. [Current local architecture](ARCHITECTURE_CURRENT.md): Firebase server verification plus private Postgres roles; no third-party-auth configuration change or service key required.
4. [Local implementation and blockers](LOCAL_IMPLEMENTATION.md): source mappings, writer ownership, staff/facility approvals, approved staging sender, clinical/analytics decisions and operational recovery gates.
5. [Production runbook](DEPLOYMENT_RUNBOOK.md): backups, data parity, rollback rehearsal and named approvals remain release prerequisites.

The earlier [conceptual migration proposal](SUPABASE_MIGRATION_PLAN.md) remains historical design context. Its broader patient/clinic normalization and user-token-forwarding option were not silently implemented. The draft now uses isolation and direct server-only database roles; approval must resolve how it should coexist with the live bot before data moves.

Local tools cannot target remote databases. Running Supabase CLI migration commands directly is outside the current authorization. Review does not by itself imply permission to switch a webhook, sender or production service.
