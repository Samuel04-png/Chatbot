# Integration readiness review

**Historical architecture baseline (2026-11-20).** The subsequent authorized local Option C implementation and fresh tests are documented in [observer implementation](../observer-implementation/README.md). Statements below about no implementation apply to this earlier audit stage. Production remains on HOLD.

Date: 2026-11-20. **HOLD production integration.** Audit and planning are complete within available access. No integration was implemented after this audit.

## Engineering conclusions

1. **Confirmed working:** authorized read-only access to the linked PostgreSQL project succeeded; the six public tables/defaults/grants were freshly inspected. Retained local evidence records 54 passing tests, 91.2% Python coverage and seven browser checks; the draft migration checksum is unchanged. Those tests were not rerun or represented as integration tests in this audit.
2. **Local but disconnected:** Firebase-verifying staff API, private-role/RLS design, inbox/outbox and UI are implemented locally. They query rudo objects that do not exist remotely. No public-table adapter, approved staff/facility map or live provider configuration is in place.
3. **Production/runtime proof:** a PostgreSQL 17.6 connection to project cktfbpnxpfbyroqzuibc and its catalog are verified. The user reports a functioning bot, but its callback, hosting deployment, deployed commit, inference endpoints and sender owner are **UNVERIFIED**. No specific production bot deployment can be certified from current evidence.
4. **Unknown/access dependencies:** actual table writers, users versus user_state ownership, active Redis use, Firebase provider/ADC setup, account/facility mappings, test sender, scheduler, backups, retention and on-call/release ownership need approved configuration evidence. No secret or patient data is requested in chat.
5. **Serious risks:** replacing the bot with the local persistence-only webhook would lose AI behavior; independent senders or competing histories can duplicate or lose work; source history is incomplete and not delivery-verified; scope and credential gaps block production integration; status-race, stale-worker and pending-reply gaps must be addressed before new staff sending is enabled.
6. **Recommended target:** Option C — a controlled read-only adapter to the verified authoritative bot store, with private staff/scope/audit metadata. Existing public tables are the best current candidate, not a proven production binding. Revise/review the full private business-schema draft before considering its application.
7. **Safest first implementation:** after architecture/staging authorization, build a synthetic public-shaped staging observer with scoped read-only access, bounded projections and disabled mutation/send/webhook capabilities. Demonstrate bot write visibility with unchanged model context, state and send count.
8. **Approval required next:** approve/revise Option C and the single-owner contract; identify actual deployed callback/commit/writers and approval owners; authorize the exact isolated synthetic staging scope. Production schema/access changes, real imports, credential rotation, provider sends, callback changes and deployments need separate explicit approval and recovery evidence.

## Required reports

| Report | Purpose |
|---|---|
| [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) | Local, remote and candidate-source evidence; diagrams and deployment unknowns |
| [DATABASE_ASSESSMENT.md](DATABASE_ASSESSMENT.md) | Exact metadata, writer matrix, A/B/C comparison and proposed read boundary |
| [WHATSAPP_INTEGRATION.md](WHATSAPP_INTEGRATION.md) | Candidate AI path, history gaps, provider lifecycle, owner contract and reliability risks |
| [SECURITY_AND_CLINICAL_RISKS.md](SECURITY_AND_CLINICAL_RISKS.md) | Prioritized technical/security/clinical findings and identity/access gaps |
| [INTEGRATION_PLAN.md](INTEGRATION_PLAN.md) | Five gated phases, smallest staging slice, tests and prioritized owner dependencies |
| [RELEASE_READINESS.md](RELEASE_READINESS.md) | Readiness assessment, approval objects, monitoring, rollback and release limits |

## Reproducible evidence

- [Read-only metadata SQL](evidence/inspect_metadata.sql) and [remote metadata snapshot](evidence/remote-metadata.json): catalog SELECT only; all actual defaults passed the safe allowlist, no application records were read. Planner estimates are not exact counts; -1 means unknown statistics.
- [Inspection status](evidence/inspection-status.json): successful connection/full metadata inspection; no application-schema DDL or messaging/model calls requested.
- [Public reference provenance](evidence/public-reference.json): public fork/parent and current HEAD; HEAD matches the pinned candidate source, whose deployment remains UNVERIFIED.
- [Source fingerprints](evidence/source-manifest.json): current application/migration/test/config paths; no logs or patient content included.
- [Prior local test results](../LOCAL_TEST_RESULTS.json) and [browser results](../BROWSER_TEST_RESULTS.json): historical synthetic validation of the local draft, with the same migration checksum.

No source, migration, test, clinical logic or production configuration was changed in this audit. Files created/updated for this task are confined to this documentation directory; temporary local inspection files are not runtime integrations.
