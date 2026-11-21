# Proposed observer rollout and rollback — not executed

As of 2026-11-21 production remains **HOLD**. Local Option C acceptance does not authorize a release. The additive local control SQL is a review artifact, deliberately outside `supabase/migrations/`; it is not a production-ready migration. The current observer rejects remote targets.

## Remaining external dependencies

| Dependency | Evidence/action needed before a production observer |
|---|---|
| Authoritative deployed bot and writers | Identify hosting, callback, deployed commit, six-table writers, sending owner and any Redis/state owner. Confirm these tables are the intended observer source. Candidate helper parity does not establish deployed parity. |
| Approved authorization map | Owners approve each source/phone/account/facility assignment and staff issuer/subject/role/scopes. No blanket facility defaults or inferred state relationships. Establish a correction/review process for conflicts. |
| Firebase environment | Verify actual provider settings, server project/ADC, revoked/disabled token handling, staff provisioning and removal using dedicated nonpatient test identities. |
| Database security and connectivity | Reinspect schema/defaults/grants/policies using read-only metadata. Review additive policies for interaction with existing roles, TLS/pooler topology, fixed function ownership, PUBLIC/inherited grants and audit isolation. Production function owners should be dedicated nonlogin least-privilege roles. |
| Query load | Explain/analyze reviewed synthetic-scale plans on an isolated clone; establish latency/connection/statement budgets and review any needed additive indexes separately. Constant query count is not a load test. |
| Privacy/operations | Approve access-audit retention, pseudonymous resource linkage, read-denial logging, backup/restore, credential storage/rotation, alerting, on-call and release/rollback owners. Audit values still need protection. |
| Clinical and transport ownership | Confirm observer labels are acceptable, and retain existing inference, translation, prompt, clinical workflow and sender unchanged. Any later sending feature needs its own reviewed owner contract and clinical/provider acceptance. |

## Smallest next safe step

Review the source projections, private control model and exact scoped SQL with the database and bot owners. Then authorize an **isolated staging clone or synthetic equivalent**, dedicated test identities and explicit test mappings. Keep all production callbacks/senders untouched. Resolve source ownership and authorization evidence while testing this slice. No real patient export is needed for this step.

## Separately approved production sequence

1. Record current metadata, deployed commit/callback and source ownership. Verify recoverable backups and a reviewed narrow change set. Do not apply the full private business migration, import or synchronize records.
2. On an isolated environment, validate reviewed production-equivalent roles/function owners/grants/RLS against the source schema, including existing policy interactions. Validate allow/deny and revocation using dedicated identities. Confirm the observer cannot alter tables or state even with transaction read-only defaults overridden.
3. Add a narrowly reviewed remote-read connection capability to the server adapter only after authorization; retain independent append-only audit, TLS verification, dedicated credentials and fail-closed behavior. Review stable cursor key storage/rotation for multiple workers; current per-process keys invalidate cursors after restart and are suitable for this local scope.
4. Review a concrete additive production migration containing only necessary control metadata, scoped policies/grants/functions and any approved indexes. Execute only with explicit approval, monitoring and recovery ownership. The synthetic bootstrap is never a deployment tool.
5. Provision individually approved staff and mappings server-side. Verify least privilege using nonpatient canary records. Observe connection load, read errors/denials, audit failures and cross-scope negative checks before widening access.
6. Release the observer UI through the approved hosting route. Verify configured Firebase in staging and production canary; keep synthetic auth absent. Confirm all mutation/webhook paths reject requests. Existing bot callback, sender, business source, clinical inference and state remain unchanged.
7. Expand to approved staff only after canary sign-off. Reconcile source counts within approved scopes; label incomplete history and unsupported analytics throughout. Treat approved-scope corrections as audited access changes.

## Rollback

Disable observer ingress/feature routing and revoke its login/connect/execute/select grants using the separately reviewed reversal script. Stop its application sessions if required. This removes dashboard access without touching the bot callback, source history, model context, state or sender.

Preserve private access-audit evidence under the approved retention policy. Reverse only observer-specific policies/functions/indexes or control metadata after checking dependencies and recording their exact names. Do not drop public tables, truncate records, restore over an active bot or use the old full migration as rollback. Restore the previous UI route only if it cannot activate a writer. Confirm the bot still processes the approved canary and that observer credentials cannot read after revocation.

## Deferred inactive transport defects

Two strict regression tests expose existing private-mode transport gaps: a late `failed` callback can regress `delivered`, and a stale worker completion can overwrite a reconciled `unknown` claim. They remain expected failures, not fixed behavior. Observer mode never registers that webhook, queues a send, invokes the worker or consumes private pending history. Fixing status precedence and claim fencing requires the confirmed authoritative sender contract before any staff sending is considered. No production transport redesign or activation occurred.
