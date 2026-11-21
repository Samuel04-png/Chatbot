> Historical private-schema implementation. The current default is the [local Option C observer](observer-implementation/README.md); this document does not describe its runtime or fresh acceptance results.

# Local implementation status and remaining review gates

Updated 2026-11-20. The owner authorized **local implementation and read-only remote schema inspection**. Remote migration execution, real-data import, existing-table replacement and deployment remain prohibited pending review. Earlier audit files describe the original snapshot; their source line references are historical.

## What changed locally

- app.py is now an app factory with safe server configuration, stable redacted JSON errors, private-response headers and explicit page/asset routes. Provider tokens were removed from application source and browser pages. No CLI secret is consumed by the app.
- Firebase Admin verifies the project, issuer, signature, expiry and revoked/disabled identity. The active staff issuer/UID, role and facilities come from protected database membership, not browser flags or profile roles. No Firebase account/provider/claim configuration was changed.
- A direct Postgres adapter uses `SET LOCAL ROLE` and verified transaction-local identity. Separate NOLOGIN/non-BYPASSRLS API/worker roles have different grants. Remote targets are rejected unless explicitly enabled later; no service-role key or public Data API access is used.
- The draft versioned migration creates a private `rudo` schema. It has RLS, constraints, source mappings, indexes, transactional webhook inbox, message history, status/version control, outbox, expiry-aware state and restricted audit metadata. Existing public tables are untouched. A local-only runner uses checksums and a ledger; repeat application skips unchanged migrations and rejects checksum drift.
- Conversation/order/referral/dashboard requests now use authenticated same-origin APIs. Staff access is checked for every request; scoped SQL policies also enforce it. Analyst access is counts only. The browser waits for Firebase identity before data fetches, no local session flag grants access, and staff enrollment requires database approval.
- Conversation resolution is persisted with optimistic version checks. Order updates also require the expected version. UI write failures remain failures. Real empty datasets remain empty; no sample clinical/order records are substituted.
- Message sends queue an idempotent operation instead of claiming immediate delivery. A separately enabled worker records confirmed delivery/provider IDs, definitive failure or uncertain outcome. Stale claimed work can become unknown; it is never blindly resent. A lost provider response does not mean safe automatic retry.
- Webhooks verify raw-body HMAC and configured account before transactional processing. All batch messages/statuses are handled; duplicate IDs are recorded once, content conflicts are rejected, failed acceptance returns a retryable response, and read/delivered status does not regress on delayed sent events. No raw health text is logged. This implementation adds no AI inference or auto-reply behavior.
- Dry-run import planning accepts synthetic/approved private exports, preserves repeated message bodies/ordering, source IDs/raw JSON/time/expiry and supports stable local re-runs with reconciliation. Remote import and live export are not implemented/enabled. Expiring business history stays in expiry-aware restricted state pending retention/UX decisions.
- The clinical regex module is unchanged. Existing risk ranking and negation limitations are characterized, not clinically endorsed.
- Legacy chat/analytics copies now point to the canonical pages. The separate cake-commerce browser credential path is removed and its Flask route disabled pending explicit scope approval; it is not silently migrated into healthcare records.
- Python 3.12 runtime/development dependency locks include hashes. Existing Firebase compat SDK is retained for now; its upgrade and full external-provider browser integration need staging verification. CSP retains inline-script compatibility and is not presented as strict script-injection protection.

## Schema decision

[REMOTE_SCHEMA_COMPARISON.md](REMOTE_SCHEMA_COMPARISON.md) explains the six existing public tables and differences from the draft. The new isolated schema is a reviewable proposal, not a decision to abandon or duplicate live bot data indefinitely. There is no automatic bridge, mirror or authoritative-writer switch. Actual schema defaults/function definitions, record counts, data quality and deployment state were not inspected; no patient records were accessed.

The conceptual patients/identifiers/clinic/campaign normalization and cross-system state reconciliation are intentionally deferred. The implemented schema is a scoped dashboard/message foundation, not an assertion that all healthcare data and newer-bot workflows have been migrated.

## Tests and evidence

See [LOCAL_TEST_RESULTS.md](LOCAL_TEST_RESULTS.md) for executed commands/results and limits. Synthetic test fixtures initialize only an isolated local PostgreSQL database; remote connections and Python socket calls are denied in the suite. Headless Chrome receives intercepted synthetic responses; SDK certificates/user lookup are stubbed for offline Firebase cryptographic tests. External staging integration, production delivery and medical efficacy are not inferred from local results.

## Remaining blockers before external integration

1. **Schema review:** approve isolation versus selective reuse/bridge of public tables, ownership of users versus user_state, exact source-to-target mapping, source defaults/grants and validated backup/restore plan.
2. **Authoritative service:** identify deployed bot/callback commit and all writers; choose the sole inbox/sending owner. Installing this local webhook over a functioning inference backend would remove its bot behavior; no such cutover is authorized or recommended without a separate contract plan.
3. **Staff/configuration:** confirm Firebase project, provision secure ADC, approved staff issuer/UID/roles/facilities, distinct restricted database logins and permitted origin/subpath. No real identities were read or inserted. Multi-facility staff currently need an explicit facility-selection UI before starting a new conversation; current UI safely refuses ambiguous assignment.
4. **Staging messaging:** provide an approved separate sender/app/recipients, secure app secret/token and supported API version. Review worker hosting/scheduler, monitoring, distributed rate limits and provider-status reconciliation. Current send rate limiting is process-local, not a cluster-wide abuse guarantee.
5. **Data and analytics:** approve private consistent export/key inventory/TTLs, retention of import provenance, facility mapping, Poster 2 reporting, heuristic conversion/response-time definitions and legacy timezone decisions. API reports all three QR source labels; UI retains its existing Poster 1/Flyer chart with an explicit note. No real export/parity claim exists.
6. **Clinical and scope:** clinical reviewer signs off risk behavior; cake/payment/design data remains excluded. Persistent clinical escalation, patient identity normalization and inference/translation changes remain separate approved work.
7. **Credential response:** owners must coordinate revocation/rotation of the Meta/Redis/verification credentials exposed in the original snapshot and remove old published/cached bundles. Local source cleanup does not revoke active credentials; no rotation was performed.
8. **Operational verification:** actual target/runtime migration smoke, provider integration, backup restore, staged read parity, rollback of target-only changes and owner release sign-off. Local tests cannot establish these. The original historical runbook remains a gated production plan.

No production deployment, remote schema alteration, account configuration change, credential rotation, real message or patient-data import has occurred.
