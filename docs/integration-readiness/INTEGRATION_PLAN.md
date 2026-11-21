# Safe incremental integration plan

Date: 2026-11-20. **Plan only. Do not implement or execute this integration on the authority of the audit.** Current phase: discovery completed within available access; architecture approval pending. Every external write, deployment and provider test still requires the applicable explicit approval.

## Architecture decision proposed for approval

Select **Option C: a thin authenticated read adapter to the confirmed authoritative bot store, plus private staff/scope/audit metadata**. Existing public Supabase tables are the strongest current source candidate, conditional on deployed-writer proof. Do not make the existing full private business-schema draft canonical because it passed local tests.

Preserve one inference/message-processing/sending owner. The first observer slice has no new webhook consumer, inference path, sender, clinical-state writer, source-data import or dual-write synchronization. Keep cake-commerce excluded. Database options and limitations: [DATABASE_ASSESSMENT.md](DATABASE_ASSESSMENT.md); transport contract: [WHATSAPP_INTEGRATION.md](WHATSAPP_INTEGRATION.md).

## Phase 1 — Read-only discovery

| Work | Status / dependency | Acceptance |
|---|---|---|
| Inspect local routes, identity, private DB layer, outbox and tests | Completed from source/artifacts; application unchanged | Source paths/line references and local-only claims documented |
| Inspect linked database metadata, defaults, grants, triggers and migration relation | Completed read-only; no patient rows | Six public tables, zero relevant functions/triggers/policies, no private schema/roles; exact defaults/identity and estimates saved |
| Revalidate public candidate source/provenance | Completed; HEAD matches pinned source; fork parent identified | Distinguish source calls from actual deployment; do not import its code or claim deployment |
| Confirm registered callback and sole sender | **UNVERIFIED**, requires authorized Meta configuration evidence | Callback/subscriptions/account IDs tied to named service and deployment commit; no secret values needed in report |
| Confirm deployment and all table/state writers | **UNVERIFIED**, application/platform owner | Writer register includes source commit, service principal name, tables/operations and schedulers; reconcile users.state vs user_state |
| Verify Firebase/hosting/inference configuration | **UNVERIFIED**, authorized respective owners | Project/provider/ADC permissions, WSGI/serverless/scheduler topology, permitted origin/subpath and model endpoint/contracts identified using sanitized configuration |

**Exit gate:** owners identify authoritative services and data source; unresolved items remain explicit rather than guessed. Database schema resemblance and planner estimates do not meet this gate. No extra account access is necessary to review the six audit documents.

## Phase 2 — Architecture and contract approval

Dependencies: Phase 1 owner register, data/security/clinical representatives and a separate staging decision.

Approve a written architecture record covering:

1. Which store owns messages, users/state, orders/referrals and temporary handoff/dedup state; unknown or unused tables remain untouched.
2. The observer interface and source-record identity. Preserve public bigint IDs and known timestamps/roles. Where account/thread/provider linkage is absent, expose explicit unknown values; never invent it from body matches.
3. Protected staff issuer/UID membership, role duties, account/facility mapping and unknown-scope denial. No country/QR-derived permissions or default facility applied to all historical records.
4. A private control-plane schema only as required. Review/revise the current private SQL instead of applying all ten business tables by default; avoid clinical-history replication for initial visibility.
5. Read-role grants and observer-only SELECT policies/narrow functions in staging. Current RLS denies ordinary readers; do not relax anon/authenticated policies, disable RLS or use a browser service key.
6. One inbound/AI/transport owner per account. Keep the local worker and callback disconnected from production accounts. Define future staff-intent/human-takeover contract separately.
7. Honest UI coverage, delivery/pending/unknown semantics, retention/export custody and audit/monitoring design. Preserve current AI prompts, history selection, translation and triage logic.
8. Rollback boundary: first release must be disableable without reverse-replaying patient writes. Record exact planned additive roles/policies/metadata and artifacts to restore later.

**Exit gate:** named owners approve the target, source/writer registry, data/access scope, staging operations and success/rollback criteria. This document requests a decision, not permission to run unspecified production commands.

## Phase 3 — Smallest reversible staging implementation

**Not implemented in this audit.** Start only after Phase 2 approval and explicit staging permission.

| Step | Implementation scope | Acceptance evidence |
|---|---|---|
| 3.1 Isolate fixtures | Separate staging project or disposable local clone of inspected public schema, synthetic IDs/phones/messages only; separate test identities | Project/DSN allowlist, environment manifest, no production secrets/data, network-denied offline tests |
| 3.2 Define access metadata | Minimal private staff/source-account/facility mapping and append-only access audit; approved synthetic principals | Unknown mapping denies; operator/analyst/admin matrix and helper/definer grants reviewed; no self-enrollment/escalation |
| 3.3 Implement observer persistence adapter | Project approved public-shaped fields into dashboard contracts with explicit source IDs, gaps and unknown delivery; do not call candidate helpers that turn failures into empty history | Adapter contract tests, nullable fields, user_state ambiguity, no fabricated UUID/provider lineage, explicit unavailable vs empty |
| 3.4 Enforce actual read-only capability | Dedicated observer login, database read-only public transactions and scoped policies; separate audit append channel | INSERT/UPDATE/DELETE/TRUNCATE/CREATE and mutation API attempts denied, including manually crafted calls; send worker cannot obtain credentials |
| 3.5 Bound read load | Summary-first conversation listing, keyset pages, on-demand history, bounded aggregates/timeouts; no eager whole-history N+1 scan | Query plans/latency and resource budgets approved by operations; completeness and load behavior tested with large synthetic fixtures |
| 3.6 Integrate UI observer mode | Hide/disable write affordances and enforce the same restriction server-side; label captured history/delivery unknown | Chats/orders/referrals visibility and facility filters; refresh/relogin/failure states; no private pending intent counted as a delivered reply |
| 3.7 Prove bot independence | Run identified bot version in synthetic staging against source-shaped tables, with stubbed model/transport first | Bot writes become visible to authorized dashboard; model context, state, reply count and sender calls remain baseline-identical with observer enabled/disabled |

The current implementation needs a new adapter and capability boundary for these steps: its database methods query rudo tables, reads append audit writes, and the remote flag enables connections generally. Changing its DSN/flag is not the implementation of observer mode.

Do not copy production records simply to test schema compatibility. A later minimized staging data copy needs explicit data-access authorization, encryption/retention and a validated backup. No live export/import is included in this first slice.

## Phase 4 — End-to-end verification and acceptance matrix

Offline CI denies external calls, substitutes Firebase cert/user lookup and Meta/model responses, and confines DB access to disposable staging fixtures. Separately authorized provider smoke tests use a dedicated test app/number and approved synthetic recipients. Never send a real patient message to prove the architecture.

| Test | Required outcome | Applies when |
|---|---|---|
| Inbound text / interactive / supported media | Owner accepts configured account/signature, preserves event identity and correct existing routing; unsupported types follow existing approved behavior | Stubbed first; test number only with approval |
| AI question and guarded reply | Identical approved inference/history/translation/guardrail path with observer enabled or disabled; response visible where source persists it | Synthetic bot staging |
| Fixed UI/shop interactions | UI clearly distinguishes omitted history; source history/state unchanged | Observer slice |
| Staff/facility/analyst matrix | Zero unauthorized raw rows, cross-account/facility denial, unmapped records inaccessible, aggregate-only analyst | All adapters/roles |
| Token expiry/revocation/account switch | Expired/wrong-project/revoked/disabled identities denied; staff deactivation takes effect; no stale-user leakage A→B/signout failure | Firebase/staff integration |
| Read-only operations | Direct DB mutations, hidden API calls and worker sends fail; audit cannot turn public reader into writer | Observer slice release blocker |
| Dashboard visibility | Bot synthetic source writes appear with stable IDs/order and honest coverage; no competing history copy or provider call | Observer slice |
| Concurrent source writes and browsing | Keyset pages/refresh show coherent lineage without duplicates or silent gaps; no lost source update | Observer slice |
| Database outage / slow source | Explicit unavailable/stale status, bounded resource use; bot inference/transport unaffected by observer failure | Observer slice |
| Order/referral parsing and metrics | Nullable/unknown facts preserved, approved timezone/attribution rules, no invented amounts or timestamps | Observer slice |
| Outgoing queue idempotency | Duplicate logical intent yields one owner-side operation; request/body conflicts rejected; split chunks have per-attempt provider linkage | Later authorized staff-send slice |
| Failed/unknown send | Failed or pending intent does not remove a needs-reply item or appear delivered; uncertain acceptance never triggers blind resend | Later send slice |
| Out-of-order statuses | Delivered→late failed/sent and early status around message insertion produce correct derived state and retained event evidence | Later transport slice; current local gap |
| Worker crash/stale claim | Stale worker cannot overwrite reconciled state or commit/send after ownership change; unknown claims quarantined | Later transport slice; current local gap |
| Meta redelivery/crash boundaries | Durable accept/process/completion tested separately; no preclaim-only lost work; retries bounded and observable | Authoritative owner reliability approval |
| Human takeover vs simultaneous AI | Atomic single winner/ownership epoch prevents competing AI/staff send; approved escalation/fallback retained | Later human messaging slice |
| Reconciliation / recovery | Source IDs, roles, timestamps, message_en/context integrity, TTL deadlines and mapping accounting agree; errors/quarantines explicit | Any approved backfill/state migration |
| Backup/restore / rollback | Isolated restore proves approved recovery objectives; observer can be disabled without losing bot work | Required before production proposal |

Acceptance metrics: zero unauthorized fixture reads/writes, zero duplicate logical sends in covered scenarios, full accounting of eligible synthetic mappings and no hidden reconciliation mismatch. Queue-age, latency, DB resource, RPO/RTO and observation-window numbers require owner approval; none are invented or claimed met here. Logical idempotency is not a guarantee of exactly-once external delivery under network uncertainty.

The retained 54 passing tests / 91.2% coverage / seven browser checks validate the existing local draft, not this adapter, the reference bot or any deployed integration. No new integration test result is claimed by this audit.

## Phase 5 — Production release proposal

Dependencies: approved architecture, verified authoritative owner, passed staging matrix, secure credentials, restoration/rollback evidence, clinical/security/data acceptance and explicit production authorization.

The first production proposal should contain only the reviewed observer release: additive scoped access/private control metadata where approved, feature disabled by default, small authorized staff cohort, bounded read load and existing callback/sending/inference unchanged. No patient import or source writer switch is necessary for this first visibility goal.

The release record must name the target project/host, exact migration diff/checksum, artifact version, permissions, source scope, credentials principal, backups, operators, rollout limits, monitoring/abort thresholds and rollback steps. No `supabase db push`, table change, deployment, real provider send or secret rotation is authorized by this plan.

Any later messaging/consolidation release needs a new proposal: owner API/transport migration, durable provider/message linkage, fencing and status repair, reverse replay of target-only writes, source checkpoint/delta, consistent backups and a test-number rehearsal. Do not combine that writer transition with the observer rollout.

## Prioritized owner inputs

| Needed | Why / when | Category |
|---|---|---|
| Redacted Meta callback/subscription/sender IDs plus deployed service/commit and writer register | Identify authoritative source and processing owner before architecture approval | Technical blocker |
| Decision on Option C and source coverage; staff roles/facility/account mapping | Bound data visibility before adapter implementation | Business + security approval |
| Isolated staging project/runtime and permitted operations | Build/prove synthetic observer after architecture approval | Platform approval |
| Firebase project/provider/ADC access, approved test staff identities | Verify real identity integration in staging; provision privately, no credential JSON in chat | Security/integration dependency |
| Dedicated staging WhatsApp number/approved recipients and secure model/transport test configuration | Separate authorized provider smoke test; not needed for offline adapter development | Integration approval |
| Secret-rotation owner, backup/retention policy and recovery targets | Secure any eventual production release without interrupting current bot | Security + data + operations |
| Clinical reviewer and transcript/metric expectations | Prevent misleading visibility or changed escalation/inference behavior | Clinical + business approval |
| Named release/rollback owners and exact production authorization | Required only for Phase 5 execution | Release approval |

Passwords, tokens, private keys and real patient content are not requested in conversation. Use platform invitations, secret-manager provisioning and encrypted restricted backups when approved. No other platform's credentials are needed to review this report.
