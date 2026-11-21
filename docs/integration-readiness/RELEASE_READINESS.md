# Release readiness and approval gates

Date: 2026-11-20. Overall: **NOT READY for production integration**. Ready for owner review of a staged read-only observer proposal. The existing production bot must remain in place. This is a gated plan, not an executable deployment authorization.

## Evidence-based readiness

| Area | State | Evidence / missing proof |
|---|---|---|
| Local foundation | LOCAL-VERIFIED, limited | Previous 54 tests, 91.2% Python coverage and seven browser checks; private migration checksum unchanged; tests not rerun in this documentation audit |
| Remote database architecture | REMOTE-METADATA-VERIFIED | PostgreSQL 17.6, six public tables, exact defaults/identity, zero relevant functions/triggers/policies, private schema/roles absent |
| Public candidate provenance | SOURCE-VERIFIED | Fork relationship and current HEAD match pinned candidate; source module hashes match retained provenance |
| Active webhook / inference / sender | **UNVERIFIED — BLOCKED** | Need actual Meta and deployment configuration tied to source commit; no endpoint was probed |
| Authoritative table/state writers | **UNVERIFIED — BLOCKED** | No producer for user_state identified; no actual project binding demonstrated for candidate |
| Observer adapter / read-only mode | **NOT IMPLEMENTED — BLOCKED** | Current app queries private rudo schema and exposes mutation routes; no bridge/source projection exists |
| Staff/facility/project provisioning | **UNVERIFIED / ABSENT REMOTELY — BLOCKED** | No remote rudo roles/control tables; approved membership/scope/ADC/provider evidence missing |
| Provider integration tests | **UNVERIFIED — BLOCKED** | Synthetic SDK/Meta tests do not prove real Firebase sign-in or WhatsApp delivery |
| Secrets response | **UNVERIFIED — BLOCKED** | Original exposed credentials not rotated/revoked by this work |
| Backups / restore / rollback | **UNVERIFIED — BLOCKED** | No approved production backup or recovery rehearsal evidence |
| Monitoring, release and clinical sign-off | **UNASSIGNED / UNVERIFIED — BLOCKED** | Named owners, approved thresholds, clinical assessment and release window missing |

## Required approval record

| Decision | Required approver / concrete object to approve | Current status |
|---|---|---|
| Architecture | Application + data + security owners: Option C, verified source/owner register, read interface and private control metadata scope | Pending |
| Staging implementation | Platform owner: isolated project/runtime, synthetic fixtures, precise staging DDL/grants/config access | Pending; this audit does not implement it |
| Staff/data access | Data/security owners: issuer/UID, roles, facilities/account mapping and approved column projections | Pending |
| Provider testing | Meta/Firebase/model owners: test app/number/users, allowed recipients, configured endpoints and safe credentials custody | Pending |
| Clinical behavior | Clinical owner: unchanged-path regression evidence, coverage labels and human escalation protocol | Pending |
| Production observer release | Release owner: exact artifact, target, reviewed migration/access diff, backups, cohort, thresholds and rollback | Not authorized |
| Later staff messaging / owner changes | Application + Meta + clinical/security owners: single-owner contract, status/fencing fixes, recovery/replay and approved deployment plan | Separately required; not part of observer release |

CLI authentication and a linked project are access capabilities, not any of these approvals. No approval is requested for a vague production action; the relevant artifact/diff and evidence must be reviewable first.

## Staging checklist and exit gate

- [ ] Confirm actual authoritative bot commit and account/phone IDs. Reproduce its source contract with synthetic public-shaped tables; keep inference/transport baseline fixed.
- [ ] Approve minimal private staff/source-scope metadata and read interface; review exact SQL/grants/functions before staging application.
- [ ] Enforce dedicated observer permissions at both API and SQL layers. Prove mutation endpoints/direct SQL/hidden controls cannot send or write source records.
- [ ] Test approved Firebase test identities, revoked/disabled/unapproved users, role separation, cross-account/facility denial and unknown mappings.
- [ ] Show authorized dashboard visibility of bot-created synthetic history/orders/referrals without changing model context, state or send count.
- [ ] Label captured-history gaps, unknown delivery, source timestamps/IDs and unavailable data truthfully. No failed/pending intent should masquerade as a reply.
- [ ] Verify summary-first/history pagination, index/query plans, bounded concurrency/timeouts and operations-approved read-load budget.
- [ ] Run failure/recovery cases, order/conversation concurrency and all relevant Phase 4 cases in INTEGRATION_PLAN.md.
- [ ] If separately authorized, run one dedicated test-number/provider smoke flow; correlate inbound ID, approved AI result, source write and authorized dashboard display without logging bodies.
- [ ] Validate encrypted backup/restore and observer-disable rollback in isolation. Record measured recovery outcomes against owner-approved targets.
- [ ] Obtain security, data, clinical and operations acceptance with named exceptions and time-bound owners. Do not infer compliance or clinical efficacy from engineering tests.

Initial tests use no patient data. An approved real-data staging copy, if later necessary, needs separate authorization, minimization, retention and access controls.

## Production observer proposal checklist — future approval only

1. **Freeze the release scope.** Record artifact hash, source commit, target hostname/project, exact proposed control tables/policies/grants and schema diff. Do not apply the existing full private business migration by default.
2. **Validate backups.** Owner captures schema/grants/defaults/functions and an appropriate consistent data backup privately. Verify restore into an isolated environment and record custody, encryption, retention, backup IDs and approved recovery targets. Catalog JSON is not a backup.
3. **Inventory/fence write owners.** Existing callback, inference and sender remain unchanged for observer release. Identify all services and scheduled jobs; no duplicate local transport can start with production credentials.
4. **Prepare secrets securely.** Owners coordinate previously exposed credential rotation/revocation under a separate continuity-approved procedure. Provision dedicated restricted observer/audit identities and verified database TLS. No secret values enter this report, chat or repo.
5. **Approve activation.** Exact production steps, time window, cohort, monitoring limits and rollback owner must be signed off before executing any schema/access/config/deployment change.
6. **Activate narrowly if authorized.** Additive access/control changes first; observer disabled by default until grants and deployment are verified. Use approved staff cohort and read budget. No production WhatsApp message is implied by a read-only smoke test.
7. **Observe and decide.** Watch source write/AI/send health, observer latency/load/auth denials and private audit failures. A working dashboard alone does not prove no disruption. Keep release/rollback record current.

No production command sequence or real target-changing action was executed or authorized by this audit.

## Monitoring and alerting contract to define

| Signal | Purpose / privacy boundary | Required owner decision |
|---|---|---|
| Owner callback accept/processing failures and queue age | Detect lost/delayed bot work using event IDs/error classes, never raw payloads | Baseline, thresholds, on-call and dead-letter workflow |
| Model/translation latency/error/fallback rate | Preserve clinical continuity; no prompt/reply logging | Approved destinations, safe fallback/escalation, clinical contact |
| Send attempts/unknowns/duplicates/status gaps | Detect transport uncertainty per logical operation/provider ID | Reconciliation rules, escalation time and transport owner |
| DB query latency/connections/locks and source errors | Ensure observer does not degrade bot | Read budget, timeout, cohort limit and disable threshold |
| Auth/role/scope denial and staff provisioning audit | Detect unauthorized access; minimize identity metadata | Security alert routing, retention and access |
| Dashboard data freshness/completeness labels | Avoid misleading staff during outage or partial history | Approved freshness window, UI unavailable/stale semantics |
| Backup restore and mapping/TTL parity failures | Prevent unsafe migration/promotion | Recovery targets and block/abort criteria |

Numeric thresholds, SLOs, RPO/RTO, alert recipients and observation duration are **UNVERIFIED/unapproved**, not fabricated. These must be settled before release. No alerts/messages were sent to stakeholders during this audit.

## Rollback by release type

### Observer-only rollback

Disable the observer feature or remove the new application from staff access. Stop observer queries, revoke its dedicated source-read capability if needed and restore only the reviewed prior observer artifact/config. Preserve existing bot callback/sender/AI configuration. Review failed reads/audit metadata privately. Verify source service health and authorized access denial after disablement.

Because this release performs no source business writes, source data reverse replay should not be necessary. Keep approved private access audit/control metadata for its retention window. Do not drop control tables or mass-revoke unrelated bot privileges as an emergency shortcut. Reversal of additive policy/grant changes must be an exact reviewed diff, with backup, owner and validation.

### Later writer/transport migration rollback

This needs a separate rehearsal: fence new writes/sends, durably retain inbound work, checkpoint both systems, capture target-only changes, reconcile provider-accepted/unknown operations, reverse-map source IDs and remaining TTLs, then restore one authoritative secured owner. Never blindly replay all outbox entries or re-enable exposed browser credentials. Validate state/history/order/referral parity and recovery objectives before resuming. No schema drop or database-URL switch alone can provide this recovery.

### Abort conditions

Any unauthorized data visibility/write, duplicate send, lost AI capability, unassigned callback/transport ownership, unexplained source-history mutation, clinical safety concern, parity failure or lack of a working rollback operator stops promotion. Operational threshold breaches follow the owner-approved limits. If those limits or evidence are missing, the release remains blocked.

## Exactly what the owner should approve next

Review these six reports and approve or revise **Option C plus the single-owner contract**. Supply redacted deployment/callback/writer evidence and nominate the data/security/clinical/platform owners. Then authorize a narrowly defined **synthetic-only staging observer implementation**, including its target and permitted DDL/grants.

Production schemas, patient imports, sender/callback changes, credential rotation and deployment remain separately approval-gated. Do not provide tokens, passwords, private keys or patient conversations in chat. No implementation follows this audit automatically.
