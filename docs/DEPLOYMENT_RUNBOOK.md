# Deployment and rollback runbook — approval gates only

> Local implementation and test evidence now exist in [LOCAL_IMPLEMENTATION.md](LOCAL_IMPLEMENTATION.md) and [LOCAL_TEST_RESULTS.md](LOCAL_TEST_RESULTS.md). External staging/production steps below remain unapproved and unexecuted.

Prepared 2026-11-20. **Not a deployment authorization.** No environment was deployed or changed. Exact commands, hostnames, thresholds and operators must be filled in after runtime and ownership verification; this document intentionally contains no credential values or speculative production command sequence.

## Release record to complete

| Required field | Current status |
|---|---|
| Application owner / security reviewer / data approver / clinical reviewer | Unassigned |
| Deployment operator and rollback operator, including backup contact | Unassigned |
| Active webhook host, sender account and deployed source commit | Unverified; browser/server configuration differs |
| Staging project ref, runtime, test sender and fixture manifest | Not selected |
| Production target, backup IDs, migration checksums and release artifact hash | Not authorized / not prepared |
| Recovery point and recovery time objectives, monitored release window | Owner to set |
| Queue age, error rate, duplicate send, reconciliation and latency thresholds | Owner to set before staging acceptance |
| Scope/implementation approval | Pending review of audit |
| External staging/data access approval | Not granted |
| Production deployment/callback/rotation approval | Not granted |

## Staging verification

1. Confirm separate staging runtime, database, staff test identities, Meta test number and recipient allowlist. Production tokens/data must not be reachable from synthetic tests. Record actual WSGI/proxy/subpath behavior, debug-off status and worker/scheduler lifecycle; do not use Flask development server for production.
2. Snapshot target schema before approved DDL; verify exact target ref and migration checksums. Apply reviewed migrations through the version ledger. Verify grants, RLS, private storage and public-function permissions under actual runtime roles.
3. Configure Firebase verification and the approved staff membership/role/facility model. Test revoked/disabled/wrong-project/unauthorized users and direct database denial. Confirm secrets are available only to intended server processes.
4. Run the full synthetic-only offline test suite. Make outbound calls impossible in automated tests; integration smoke tests are a separately labeled, explicitly authorized stage using staging accounts.
5. Exercise webhook GET challenge and valid/invalid signatures, multi-message batches, statuses, concurrent duplicates, out-of-order deliveries and storage failure. Confirm durable acceptance before successful acknowledgement and recoverable worker leases.
6. Exercise admin send, conversation list/history/new thread/resolution, orders, referrals/analytics, account/recovery/logout/delete and error paths. Record pending/sent/failed/unknown states and provider message IDs without message content in logs.
7. Import synthetic fixtures twice and after an interrupted batch. Verify no duplicate entities, exact identifiers/ordinals/times/relationships/absolute-expiry parity and quarantine accounting. If approved real data is later used, keep it in restricted staging and never copy payloads to reports.
8. Verify bounded request concurrency/timeouts/retries and adequate hosting capacity. Monitor queue lag, processing attempts, send uncertainty, auth denials, request latency and upstream error codes. Do not expose PHI through metrics labels or request URLs.
9. Rehearse backup restoration, application rollback and target-only change replay in isolation. Compare digests, mapping coverage, counts, message provider IDs, order versions and session deadlines.
10. Obtain named security, clinical, data and operations acceptance with agreed thresholds and signed exceptions. Store evidence without patient text or secrets. A healthy dashboard alone is not acceptance.

## Production preflight — separate explicit approval required

- Exact application artifact, config changes, migration versions and sender/callback destination approved in writing.
- All external writers and old browser clients accounted for; one authoritative consumer/sender established. Prevent cached legacy credentials/pages from continuing privileged writes.
- Source and target encrypted backups completed and restore-tested; private backup custody/retention documented. Decryption keys separate.
- Updated server-only credentials provisioned securely; coordinated rotation/revocation window agreed with provider owners. No reactivation of compromised browser credentials for rollback.
- Staff permissions and facility mappings approved; unknown-scope records restricted; clinical and metric decisions accepted.
- Final snapshot/delta/checkpoint method and brief write freeze approved; source cannot be assumed consistent from online SCAN alone.
- Rollback operator available; secured prior version, reverse-mapping/replay process, send-uncertainty procedure and threshold-based trigger ready.
- No unresolved data-parity mismatch, missing event lineage, unauthorized access finding or untested restore step.

## Approved cutover procedure to finalize later

1. Record release start, source writer watermark, queue position and backup IDs. Restrict approved mutations temporarily and drain or durably retain in-flight work. Do not interrupt the authoritative webhook without a durable delivery/retry plan.
2. Take the final consistent snapshot/delta. Import approved changes transactionally with stable mappings; reconcile before target becomes writer. Never silently discard changed/malformed records.
3. Switch the designated application persistence setting and frontend release; change Meta callback only if expressly required and separately approved. Run one consumer/sender; retain inbox/provider event dedup history across the transition.
4. Use approved smoke identities/recipients only. Verify scoped read, one authorized send, durable inbound event, order update conflict handling, referral metrics and signout/revoked-user denial. Any real message requires explicit owner authorization.
5. Observe predefined release-window metrics and data parity. Log only safe request/resource IDs, outcomes and error classes. Keep old database/secured code recoverable but prevent split-brain writes.

## Rollback triggers and procedure

Unauthorized access, missing/lost messages, duplicate sends, unreconciled records, clinically unsafe behavior or failures exceeding agreed thresholds stop promotion. Numeric latency/queue/RPO/RTO thresholds must be set by owners before production; they are not invented in this audit.

1. Rollback owner declares rollback and records decision time/watermark. Stop new target mutations/sends safely; maintain or buffer inbound events durably. Fence workers to prevent two senders processing the same outbox.
2. Capture target-only message/order/referral/state changes and inbox/outbox states since cutover. Resolve provider-accepted/unknown sends using provider IDs/status evidence; do not replay all sends or interpret a timeout as definite failure.
3. Reconcile/apply changes to the secured prior persistence backend using approved reverse mappings. Restore remaining TTL from absolute deadlines, skip expired sessions, preserve IDs and message ordering. Validate source and target agree before resuming writes.
4. Restore approved application config/artifact and callback only through the explicit release plan. Never restore exposed browser tokens, raw health logging or unauthenticated sensitive routes as a recovery shortcut.
5. Resume one authoritative consumer and sender; run the approved smoke suite and reconciliation. Record actual recovery point/time, rejected records, undelivered work and any manual remediation without private payloads in reports.
6. Retain target/backup state for incident review. Do not drop migrated tables or destroy exports during the rollback window. Destructive cleanup requires separate owner approval after retention rules are satisfied.

## Handoff evidence

Release record must attach migration checksums, redacted config inventory, role/RLS test results, fixture version and offline network-denial proof, reconciliation summary, staging smoke/latency/failure results, backup/restore and rollback rehearsal, clinical decisions, named approvals and post-release monitoring results. This audit provides source analysis and a preparation baseline only; these release artifacts do not yet exist.
