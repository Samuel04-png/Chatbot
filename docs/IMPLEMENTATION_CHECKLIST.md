# Implementation checklist and acceptance gates

> Historical discovery baseline. Local implementation is now authorized and documented in [LOCAL_IMPLEMENTATION.md](LOCAL_IMPLEMENTATION.md); original source references below describe the audited snapshot. Remote execution remains pending review.

Status: preparation only, 2026-11-20. Checked items are audit outputs, not deployed fixes. Proposed owners are roles to be assigned by Dawa Health. See [SUPABASE_MIGRATION_PLAN.md](SUPABASE_MIGRATION_PLAN.md) for design and [DEPLOYMENT_RUNBOOK.md](DEPLOYMENT_RUNBOOK.md) for release gates.

## Gate 0 — Audit and scope

- [x] Inventory local files/pages/routes, data key patterns, integrations and legacy assets.
- [x] Trace login/dashboard/chats/webhook/send/orders/referrals/triage/logout/delete-account behavior.
- [x] Record security locations without copying credential values into deliverables.
- [x] Compare public newer bot at a pinned commit and distinguish README assertions from code.
- [x] Prepare schema/auth/data migration proposal, access requests, diagrams and rollback design.
- [x] Perform offline syntax and narrowly scoped synthetic characterization; document its limits.
- [ ] Owner reviews audit and authorizes local implementation scope. **Dependency:** none. **Accept:** named decision/owner recorded.
- [ ] Application/Meta owner identifies callback, deployed commit and all Redis writers. **Accept:** deployment graph including external bot and both sender configurations.
- [ ] Data owner approves namespaces, cake exclusion/inclusion, region, retention and private fixture process. **Accept:** written scope, no unknown database silently included.
- [ ] Security/operations owner defines staff roles, facility scopes and unassigned-record handling. **Accept:** explicit permission matrix and synthetic principals.
- [ ] Analytics/clinical owner decides metric discrepancies and supplies safety reviewer. **Accept:** signed definitions and independent clinical review plan.

## Gate 1 — Offline stabilization (after implementation approval)

- [ ] Add config validation/environment template with names/placeholders only; remove hardcoded provider credentials and all privileged browser tokens. **Depends:** Gate 0. **Accept:** missing secrets fail closed; source/build scan covers all HTML copies and assets; no secret in exceptions.
- [ ] Establish reproducible Python environment and pinned vendor asset inventory. **Accept:** clean install with compatible supported runtime; advisory scan records real versions/results; licenses reviewed where reusing bundles.
- [ ] Build test harness that denies outbound sockets by default, stubs Redis/Meta/Firebase/Supabase/model services, and uses synthetic fixtures only. **Accept:** deliberate unmocked outbound attempt fails; no real credential loaded; tests cannot contact production.
- [ ] Characterize current data/UX contracts before changing them. **Accept:** normal/error/empty contracts for all workflow rows in CODEBASE_ANALYSIS; each intentional correction has approved expected behavior.
- [ ] Implement Firebase server token validation and staff scope checks for every sensitive route. **Accept:** anonymous, expired, invalid signature, wrong issuer/audience, revoked/disabled, nonstaff and cross-facility requests denied without downstream operations; localStorage role/flag does nothing.
- [ ] Remove local session fallback and client PIN as access authority; restrict staff enrollment. **Accept:** SDK missing/offline and forged local state fail closed; pending auth does not start patient reads; new unapproved identity denied.
- [ ] Implement scoped message sending with validation, operation IDs and provider time budgets. **Accept:** unauthorized recipient/account denied, bounded content and rates, provider 4xx/429/5xx/timeouts return safe stable errors.
- [ ] Validate raw webhook signatures and request budget before parsing. **Accept:** signature matrix including Unicode/body mutation and invalid content passes; non-message/status events handled separately.
- [ ] Replace raw payload logging and public exception bodies with sanitized observability. **Accept:** synthetic phone/body/token/health sentinels absent from captured logs/client errors; action metadata retained.
- [ ] Set origin/cache/CSP/frame/referrer policy appropriate to actual hosting; add CSRF defenses if cookies used. **Accept:** browser origin tests and private-response cache tests; no claim that CORS alone provides auth.

## Gate 2 — Schema and migration tooling

- [ ] Obtain approved staging target identity and schema-only baseline. **Depends:** Gate 0 + explicit staging access. **Accept:** verified project ref and collision review; no production target selected implicitly.
- [ ] Create reviewed versioned SQL for proposed tables/FKs/indexes/grants/RLS and scoped atomic functions. **Accept:** fresh isolated DB apply succeeds; migration ledger makes second apply a no-op; schema drift rejected; no accidental cascade of clinical data.
- [ ] Configure selected Firebase-to-Supabase path only with approval; protect text UID membership. **Accept:** valid user token with approved role/scope works; unrelated Firebase project, anonymous and nonstaff denied; membership self-escalation denied.
- [ ] Test RLS for actual execution roles and privileged worker boundary. **Accept:** operator/analyst/admin scope matrix; function execute grants and security-invoker views reviewed; service bypass explicitly tested/documented, never counted as RLS enforcement.
- [ ] Implement inbox atomic acceptance and leased/retryable processing. **Accept:** concurrent duplicate event inserts produce one logical job; multiple messages in a delivery all handled; worker crash before/after claim recovers; DB failure does not acknowledge undurable work.
- [ ] Implement durable outbox/delivery ledger and order optimistic concurrency. **Accept:** duplicate operation ID does not duplicate send; provider acceptance followed by timeout/crash becomes reconcilable unknown; racing status edit returns conflict; appends never overwrite inbound history.
- [ ] Build synthetic export fixtures covering types, aliases, repeated encoding, missing/malformed timestamps, duplicate scan keys, tied message times, unknown roles/statuses and IDs. **Accept:** parser preserves raw facts, ordinals, relationships and quality flags.
- [ ] Implement dry-run exporter/importer with explicit live modes, checkpoints, target validation and restricted artifacts. **Accept:** dry-run makes zero writes/network by default; unchanged re-run creates zero duplicate entities; interrupted resume deterministic; changed-source/new-target conflict stops safely.
- [ ] Implement absolute-expiry mapping and restore. **Accept:** persistent/-1, gone/-2, expired, near-expiry and clock-boundary tests; import/rollback never renews elapsed session lifetime; atomic acquire tested under contention.
- [ ] Implement reconciler. **Accept:** disjoint source accounting, message counts, per-key mappings/digests, FK/orphan checks, status/amount/time/TTL checks; failures block promotion and reveal no payloads or phone-bearing keys.
- [ ] Validate backup/restore to isolated environment. **Accept:** encrypted backup can actually restore and matches approved source manifest; source remains intact.

## Gate 3 — Frontend and workflow regression

- [ ] Replace direct Redis/Meta paths across every approved page, including legacy copies if retained. **Depends:** protected API and adapter. **Accept:** browser request inventory has no privileged provider call or key; private pages cannot bypass API auth.
- [ ] Chats: load/search/sort/risk filter/new thread/send/read-only history, pending/failure/unknown-send states, mobile layout. **Accept:** fixture-based browser tests with providers stubbed; no lost concurrent message; ambiguous phone rejected and both supported countries covered.
- [ ] Resolve: implement explicit persisted lifecycle only if approved. **Accept:** survives reload, authorized role only, audit event, consistent analytics; legacy heuristic retained separately if needed.
- [ ] Orders: parse approved legacy shapes, list/filter/status update and conflict/error handling. **Accept:** multi-encoded input handled; failed writes never claim saved; read-only demo cannot mutate live-shaped keys; no invented amount/currency/timestamp.
- [ ] Dashboard/analytics: approved denominator/date/timezone rules and safe export. **Accept:** deterministic golden metrics for empty/partial/malformed/success, date boundaries and out-of-order messages; no preview mistaken for live data.
- [ ] Referrals: approved Poster 2 and clinic/source mapping. **Accept:** UI/API totals agree for synthetic aliases/unknown labels; read failures distinguished from zero; classification version recorded.
- [ ] Risk: preserve baseline and review approved corrections separately. **Accept:** category/tie/rank/role/message-alias/negation/multilingual fixtures; no automatic clinical-safety claim; clinic reviewer signs change before release.
- [ ] Account: login/register/password recovery/profile/settings/logout/delete. **Accept:** provider stubs, recent-login failure, disabled identity, shared-browser profile clearing, role cannot be edited into authority; deletion never falsely implies patient-record erasure.
- [ ] Legacy XSS regression. **Accept:** synthetic payloads in message/order/id/due fields do not execute; unsafe legacy page either secured or explicitly retired with owner sign-off.

## Gate 4 — Staging verification

- [ ] Deploy only to expressly authorized isolated staging with separate secrets/data/sender. **Accept:** staging config and debug-off runtime verified; no production credentials/recipients available.
- [ ] Use approved encrypted data copy only after explicit data-access permission. **Accept:** private access/retention controls, exact reconciliation or signed quarantines; no patient payload in test artifacts.
- [ ] Rehearse multi-message webhook, retry, status updates, out-of-order delivery and concurrent operators. **Accept:** durable processing and delivery ledger proves no missing or duplicate logical work.
- [ ] Run failure/latency tests within agreed budgets: Redis/Postgres/Meta unavailable, slow calls, worker restarts, invalid auth and cache expiry. **Accept:** stable errors, bounded retries, monitoring and recovery evidence.
- [ ] Rehearse cutover delta and rollback including target-only changes, unknown sends and remaining TTL. **Accept:** owner-approved RPO/RTO achieved and reconciliation exact; no duplicate real send during replay.
- [ ] Obtain security, clinical, data and operations sign-off. **Accept:** named approvals and unresolved-risk dispositions attached to release record.

## Gate 5 — Production (separate authorization required)

- [ ] Production owner approves exact release/config/migrations, backups, secret rotation plan and callback decision in writing.
- [ ] Named rollback operator can restore secured application/data; monitoring thresholds and release window approved.
- [ ] Validate backups and final source watermark; suspend/drain approved writers; import final delta; reconcile before enabling target writes.
- [ ] Switch only designated app/data path, keeping one webhook consumer/sender; test only expressly approved production smoke flow.
- [ ] Monitor durable queue lag, duplicate/event failures, send uncertainty, auth failures, metrics/data parity and privacy-safe errors.
- [ ] Execute rollback on approved triggers; reconcile post-switch writes and message IDs first; never return to compromised browser tokens.
- [ ] Close rollback window only after owner acceptance; retain backups/export for approved duration then securely expire them. Delay source deletion/contracting schema until separate approval.

No item in Gates 1–5 was implemented by this discovery assignment. The ten offline characterization assertions in AUDIT_EVIDENCE document current behavior, including unsafe behavior; they are not security regression passes.
