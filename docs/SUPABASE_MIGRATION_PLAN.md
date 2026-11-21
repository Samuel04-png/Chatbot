# Supabase migration proposal — not implemented

> Historical discovery baseline. Local implementation is now authorized and documented in [LOCAL_IMPLEMENTATION.md](LOCAL_IMPLEMENTATION.md); original source references below describe the audited snapshot. Remote execution remains pending review.

Date: 2026-11-20. Decision status: proposed for owner review. No SQL migration, export/import tool, backend rewrite, frontend integration, deployment, account change or data migration was performed. The later discovery-only request governs this stage.

## Recommended scope and architecture

Preserve the current staff dashboard and Firebase staff identities initially. Replace browser Redis/Meta calls with same-origin authenticated Flask APIs. Move approved persistent healthcare records into relational Supabase Postgres through a persistence adapter. Keep one authoritative WhatsApp ingestion service and one authoritative writer for each record during every stage. First establish whether that service is this cPanel app, the newer bot or an unsupplied deployment: this archive's webhook only logs messages.

Current: browser → Firebase identity; browser → Redis data and Meta sending; optional Flask → Redis QR aggregation and Meta sending; webhook → local logs. Proposed: browser → Firebase → authenticated Flask API → scoped Supabase access; send API → durable outbox → Meta; signed webhook → durable inbox → worker → messages/state. Inference and external agent handoff remain unchanged until separately reviewed. Diagrams: [ARCHITECTURE_DIAGRAMS.md](ARCHITECTURE_DIAGRAMS.md).

Cake orders, payment/design images and unrelated database content are excluded by default pending ownership/scope approval. Never interpret broad `order*` and healthcare `orders:*` as the same domain. Historical log files, local session flags, disposable QR caches and demo records are not business-data migration inputs.

## Authentication decision

| Choice | Benefits | Work and risk | Decision |
|---|---|---|---|
| A: Keep Firebase | Existing email/Google identities and passwords stay with current provider; least user disruption | Add backend Firebase Admin ID-token verification, revocation/disabled checks, staff membership and scoped roles; configure Supabase third-party integration if forwarding user tokens | Recommended first stage |
| B: Supabase Auth | One identity platform later | Requires authorized identity/provider inventory, password-hash import feasibility or reset/re-enrollment, OAuth configuration, UID mapping, sessions/claims/MFA migration and rollback; identities cannot be inferred from local profiles | Separate approved migration after persistence stabilizes |

Do not migrate `rudoSessionActive` or browser role strings into identity/authorization. Staff memberships are server-controlled and keyed by `(issuer, subject)` text, preserving Firebase UIDs without assuming UUIDs or an existing auth.users row. Define admin, operator and analyst permissions with facility scopes before implementation. Public signup does not automatically grant staff access.

Preferred staff path: client attaches fresh Firebase ID token to API; backend verifies expected project/audience/issuer/signature/expiry and revoked/disabled state, loads active membership and scopes, then queries Supabase with that verified identity token through the supported Firebase integration. RLS checks `auth.jwt()->>'sub'` against protected text-subject staff membership and facility scope. Supabase's integration requires the correct Firebase project and authenticated role claim; these are **not currently configured or verified**. Do not grant authenticated custom claims indiscriminately to all Firebase users as a substitute for staff authorization. Never mint an arbitrary client-supplied role JWT.

If user-token forwarding proves unsuitable, use a dedicated backend database role limited to reviewed queries/functions after the API authorization gate. A broad service/secret key bypasses RLS and is not a least-privilege staff access design; reserve it for tightly isolated worker/import operations where justified. Never claim RLS protects requests made with a bypass role. No privileged key reaches browser bundles.

The [official Firebase integration](https://supabase.com/docs/guides/auth/third-party/firebase-auth) supports retaining Firebase, but this is a capability reference, not a tested project integration. [Firebase verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens) and [revocation](https://firebase.google.com/docs/auth/admin/manage-sessions) belong in backend enforcement.

## Proposed data mapping

All tables are proposed, not established production schema. IDs/timestamps below are design requirements, not assertions about exported records. Do not execute CREATE IF NOT EXISTS blindly over an existing project.

| Source | Target | Preservation / validation |
|---|---|---|
| `conversation:<phone>` / conversation* JSON arrays | patients, conversations, messages, migration_records | Preserve source database alias + exact key; original phone text and separately validated canonical form; one conversation mapping per source key; original message sequence, role/text field and timestamp; no deduplication by body alone |
| Message text with `DH-…` display ID | patient_identifiers / migration mapping | Preserve as legacy display identifier with provenance; resolve conflicting IDs explicitly; regex-extracted or hash-derived IDs are not primary keys |
| `orders:*` objects / encoded JSON strings | orders and optional order_items after writer contract confirmed | Exact source key as stable import identity; original order/user ID as separate fields; retain raw amount/currency/status and timestamps; parse validated numeric amount separately; quarantine unknown/malformed values |
| `referrals*` objects | referral_events, clinics, campaigns | Preserve original source string and optional source time; separately normalize clinic/source; unknown classifications remain visible; clarify repeat vs first-touch semantics |
| Authoritative bot profiles/state, if found | patients, conversation_state | Inventory external writer schema first; preserve language/step/state JSON, version, timestamps and expiry; do not infer an empty state just because this archive lacks it |
| Firebase staff | staff_memberships, facility_memberships, optional staff_profiles | Identity stays in Firebase initially; owner-approved UID/role/scope mapping; no password export required for Option A |
| Device profile/preferences | optional staff_preferences | Exclude by default; explicit per-user import/mapping after privacy review; browser role and session fields ignored |
| Temp state/agent session keys, if discovered | expiring_state or retained Redis | Preserve absolute expires_at and atomic claim semantics; read-time expiry enforcement plus cleanup; do not convert expired sessions into permanent rows |
| Current computed risk flags | no automatic historical clinical entity | Preserve source messages and classifier version; approved future triage_flags/escalations are new records, distinguished from observed clinical events |
| Cake `order*` / proof/design images | separate approved commerce tables + private Storage, only if scoped in | Separate database namespace and ID mapping; validate image encoding/type/size, object checksums and joins; private signed access, no public bucket |

### Relational schema specification

- **patients**: UUID primary key; original/canonical phone fields under restricted access; canonical uniqueness only within confirmed WhatsApp account/tenant and after collision review; created_at/updated_at timestamptz; legacy identifiers in a child table. Do not merge people solely by recycled phone number or derived display ID.
- **conversations**: UUID PK, patient_id FK, messaging_account_id FK, source mapping, nullable approved facility_id, status with controlled values, version bigint and original timestamps. Source `(database_alias, key)` unique in migration_records. Index `(patient_id, updated_at desc)` and `(facility_id, status, updated_at desc)`.
- **messages**: UUID PK, conversation_id FK, source ordinal, role, original text, optional message_en, original timestamp/precision metadata, provider message ID/account, delivery state. Unique `(import_source_record_id, ordinal)` for legacy arrays; partial unique `(messaging_account_id, provider_message_id)` when supplied. Index `(conversation_id, occurred_at, source_ordinal)`. Preserve unknown roles in raw import record pending normalization; do not silently reject history.
- **orders**: UUID PK; patient/conversation FKs nullable until proven; source ID/key, raw and normalized status, amount numeric with validated currency, address under restricted permission, source created/updated time and version. Index `(status, created_at desc)` and `(patient_id, created_at desc)`. Quantity positive when known; amounts never inferred as zero from malformed strings. Known current statuses: pending, confirmed, completed, cancelled, paid, unpaid, collected, delivered; unknown legacy status preserved separately.
- **clinics/campaigns/referral_events**: stable lookup IDs, raw source retained; nullable patient/clinic/campaign FKs, event/source time nullable, migration time separate. Unique source mapping; indexes on `(clinic_id, occurred_at)` and `(campaign_id, occurred_at)`. No fabricated clinic or QR scan timestamp.
- **conversation_state/expiring_state**: structured state JSONB, state_version, updated_at, optional expires_at; namespaced key PK for temp state, expiry index. An atomic SQL function handles acquire-if-absent-or-expired rather than multi-request DELETE+INSERT races. Avoid storing high-frequency cache data without measured need.
- **webhook_inbox**: unique `(account_id,event_id)` plus event type, minimal encrypted/restricted processing payload, received_at, processing state, attempts, lease expiry and safe error code; index ready/lease status. A Meta delivery can contain multiple events. Message-ID deduplication does not cover every status event; define stable event identity per type.
- **message_outbox**: operation UUID/idempotency key unique, actor/conversation/account FKs, payload reference, pending/leased/sent/failed/unknown state, provider ID, attempts and timestamps; retry-ready index. Append ledger and reconciliation prevent silent resend on network uncertainty.
- **staff_memberships/facility_memberships**: issuer+subject text unique/PK, active flag, constrained role, facility FK(s), grant/revocation audit metadata. Membership changes require administrator-controlled server path; users cannot grant themselves access.
- **audit_events**: immutable action/actor/resource IDs, timestamp, outcome and request ID; exclude text/phone/token/medical payloads. Separate restricted read policy; retention approved by owner.
- **migration_runs/migration_records**: source alias/key (sensitive, restricted), digest, source type, export time, expiry, target mapping, result and rejection reason; append batch manifest/counts without health content in logs. Restore mappings must survive repeat imports.
- **triage_flags/escalations**, only after approval: conversation/message FK, classifier version, category, original assessed time and reviewer/acknowledgment; do not make historical automated flags look like clinician decisions.

Use `timestamptz` for real instants, preserve original string/precision/timezone separately. Missing/ambiguous times remain NULL with quality metadata; `imported_at` never masquerades as `occurred_at`. Decide legacy timezone with owner. Foreign keys use RESTRICT by default for clinical/business records; avoid automatic cascaded healthcare deletion. JSONB preserves unmapped source fields in restricted migration storage with approved retention. Query/filter frequently used fields relationally, not opaque blobs alone.

### RLS, grants and authorization matrix

Enable RLS on every exposed table before granting access. Default deny anon/public; revoke unnecessary table/function/schema privileges. Staff writes/read scope must match backend authorization. Views must not bypass policies; privileged functions require fixed search_path, revoked public execute and narrowly granted calls. Protect membership lookup against recursive RLS, using a reviewed helper or protected view. Storage buckets private; scoped object policies if used. Audit append is server-controlled.

| Principal | Chats / messages | Outbound | Orders | Referrals / analytics | Membership / audit |
|---|---|---|---|---|---|
| Anonymous or authenticated nonstaff | Deny | Deny | Deny | Deny | Deny |
| Active operator | Assigned facility scope read; approved actions | Scoped conversation/account only | Scoped read/update status with version check | Only approved operational aggregate access | No role grants; no unrestricted audit reads |
| Analyst | No raw health text by default | Deny | Approved aggregates only | Scoped deidentified aggregates | No role grants |
| Administrator | Explicit authorized scope | Approved scope | Approved scope | Approved scope | Controlled staff provisioning/audit access; no browser privilege bypass |
| Webhook worker | Only inbox/message/state operations for configured accounts | Outbox worker only | Defined bot operations if owned | Defined referral inserts if owned | No staff role grants |
| Importer | Isolated staging/import privileges | Deny; Meta credentials unavailable | Approved batch mappings | Approved batch mappings | Restricted run ledger only |

Facility information is not consistently present in source. Default unassigned records to a restricted migration-review scope; do not grant all operators access because a facility is NULL. Owner approves resolution.

## Temporary state and expiry decision

Discard/rebuild QR cache. Use PostgreSQL for modest-volume expiring business state if atomic concurrency/expiry behavior and latency are acceptable; retain Redis for proven high-frequency cache/locks until independently migrated. No blanket Redis replacement. Read paths always enforce `expires_at > now()` or no expiry; cleanup delay must not resurrect expired data. Distinguish Redis PTTL -1 (persistent) and -2 (gone). Record snapshot timestamp and absolute expiry; import remaining lifetime, not original duration. On rollback restore remaining lifetime and skip expired keys. Existing GET/SET code cannot establish actual TTL policy.

## Export/import specification for the implementation stage

1. Owner approves exact databases/key namespaces, encrypted backup location, record scope and external writer inventory. Read-only exporter must accept secure env configuration, never CLI token arguments or printed values.
2. First implement offline `--dry-run` over synthetic/redacted fixtures; no network by default. Live export/import modes require explicit target selection and authorization; fail on unexpected project/database.
3. Inventory SCAN with cursor deduplication, Redis TYPE and PTTL for every approved key. Do not GET non-string types. Unsupported structures are counted and quarantined rather than dropped. Capture raw bytes privately, JSON decoding depth, source ID/time/type/expiry and digest. Never put key names with phone numbers or rejected payloads into console logs.
4. SCAN is not a consistent backup under writes. Use owner-validated provider snapshot or coordinate writer checkpoint + delta capture + final short write pause. Inventory **all** writers, including external bot and legacy clients, before calling the export complete.
5. Decode historical single/double/triple JSON only to a defined depth and validate shapes. Stable source namespace+key/ordinal mappings make re-runs idempotent. Never recreate IDs, timestamps or expirations on every run. Source changes after a checkpoint require version/hash comparison; stop on conflict rather than overwrite newer target edits.
6. Transactional import batches and run checkpoints support resume. Dry-run validates and reports planned creates/updates/skips/rejections without writes. Re-run unchanged fixture creates zero duplicates; interrupted import resumes safely. Preserve source order when timestamps tie or are absent. Keep equal-body messages as distinct messages unless provider IDs prove duplication.
7. Reconcile per namespace/type: discovered = accepted + quarantined + expired/disappeared + explicitly excluded, with each category disjoint. Separately reconcile parsed business entities, message array lengths, target inserts/updates/skips, source-to-target mapping and FKs. Compare canonical digests/aggregates, earliest/latest known timestamps, statuses, currencies and absolute expiries. Counts alone cannot prove parity.
8. Data-quality exceptions need signed disposition before cutover; no patient records in report output. Encrypt restricted export/quarantine bundles, use limited filesystem permissions, keep encryption keys separately, approve retention/deletion and rehearse restore in isolated staging.

## Implementation phases and gates

| Phase | Work | Dependency / completion gate |
|---|---|---|
| 0 — Discovery | This documentation, scope/provenance and risk register | Owner reviews; active callback/writers, healthcare data scope and staff authority identified |
| 1 — Local stabilization | Config/env validation, protected APIs, signature checks, safe logging, pinned environment, offline characterization tests, demo isolation | Written implementation scope; synthetic-only tests with all external sockets blocked; no provider access needed |
| 2 — Isolated Supabase design | Reviewed versioned SQL/RLS/grants/functions, adapter, staff role model, importer/exporter dry-run | Approved target/staging project and schema; migration applies to fresh DB, repeat data import no-op, policy tests including bypass-role limits pass |
| 3 — UI integration | Replace every direct Redis/Meta client including explicitly scoped legacy pages; preserve chats/orders/profile/recovery/analytics/risk workflows | API contract and role tests; browser regression with network blocked; no privileged bundle secrets; no production callback change |
| 4 — Staging parity | Approved export, encrypted restore rehearsal, shadow/read comparisons, synthetic WhatsApp test account, load/failure/retry review | Explicit staging/data access approval; reconciliation exact or signed exceptions; independent clinical and operations sign-off |
| 5 — Production handoff | Coordinated backup/rotation, final delta, controlled switch, monitoring | Separate explicit production approval and validated rollback; no action authorized by this document |

## Migration versioning and rollback design

Future SQL files use ordered immutable timestamps and a migration ledger/checksum. Apply each once; guards should confirm exact expected schema rather than hide drift. Seed lookup data through stable keys and upserts. Rerunnable data import is distinct from replaying destructive schema operations. In CI apply to a fresh isolated database, verify second application through the migration tool produces no changes, compare catalog grants/RLS, rehearse backward-compatible application rollback and restore. Prefer expand/contract; postpone removal of source-compatible fields until rollback window closes.

Before first approved staging write: snapshot existing target schema/data, record project ID/migration checksums and prove restore. Never overwrite a bot's existing `users/messages/orders` tables without a contract/diff review; use a separate staging project or isolated schema if necessary.

At cutover set a per-entity authoritative writer, checkpoint time and watermark; pause approved writes briefly, drain inbox/outbox, take final delta, reconcile and switch backend configuration. Browser bundles containing old credentials cannot remain an alternate write path. Avoid ad hoc dual writes across Redis and Postgres: they cannot be made one transaction. If continuity requires shadowing, use a durable ordered change log, conflict policy and catch-up metrics.

Rollback after target writes requires capture/replay of new messages, order changes, inbox statuses and unmapped records into the prior **secured** backend; changing a database URL alone loses data. Preserve provider message IDs to prevent duplicate sends. Reconcile unknown sends with provider status rather than replaying all outbox rows. Keep one active consumer/sender during switch and rollback. Expiring sessions retain absolute deadlines. Do not reactivate exposed credentials or unsigned/unprotected endpoints as rollback. Destructive down-migrations are not the recovery plan; use app rollback plus reconciled state and tested backups.

## Risk register and acceptance

| Risk | Proposed owner | Mitigation / release evidence |
|---|---|---|
| Active writer/callback unknown | Application + Meta owner | Deployed code/ref and callback inventory; source/target contract test |
| Exposed source credentials | Platform owners | Coordinated replacement/revocation and artifact scan |
| Lost/duplicated WhatsApp work | Backend + operations | Durable inbox/outbox, concurrency/crash tests and sender reconciliation |
| TTL loss / stale handoff resurrection | Backend + data owner | Absolute-expiry fixture tests, restore rehearsal and approved retention |
| Identity/authorization regression | Firebase + security owner | Stable Firebase identities, staff allowlist, role/facility matrix and revoked-user tests |
| Clinical ranking/translation changes | Clinical owner | Baseline snapshots, clinician-reviewed safety suite; inference change separated |
| Metric drift | Analytics owner | Poster 2 decision, definitions/denominators/timezone and golden fixture totals |
| Data loss from online SCAN / schema ambiguity | Data owner | Consistent backup plus delta/writer freeze, quarantine accounting and hashes |
| Newer bot compatibility/privacy/provenance | Repository + clinical owner | Canonical commit/license/schema/model contracts; no blind reuse |
| Host/serverless latency or worker mismatch | Deployment owner | Runtime/queue design, timeout and recovery tests in intended hosting |

Release requires: all SEC critical/high items addressed or formally accepted by named owner; no privileged browser secrets; unauthorized requests never reach providers/database; valid webhook batches durably accepted once; no lost append/update in concurrency tests; exact approved data reconciliation and expiry behavior; known UX preserved with explicit error/demo states; clinical sign-off; staging backup and rollback rehearsal; documented operator, RPO/RTO and monitoring thresholds; separate signed production permission. None of these implementation acceptance gates is claimed complete by this audit.
