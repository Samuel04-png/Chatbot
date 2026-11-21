# Security, privacy and clinical integration risk register

Date: 2026-11-20. Status: **production integration blocked**. Findings are source/catalog assessments; no production exploit, patient access, clinical validation or live delivery test was performed. Existing synthetic results remain valuable but cannot establish operational readiness.

## Prioritized risks

| ID / priority / category | Evidence and failure scenario | Required mitigation / release evidence |
|---|---|---|
| IR-01 Critical — clinical continuity / technical | Local app.py:264–298 and rudo/db.py:163–224 persist events without an AI path. Registered production callback owner is **UNVERIFIED** | Do not replace callback. Verify deployed source/owner and preserve its inference path; stage observer-only integration before any routing change |
| IR-02 Critical — duplicate transport / technical | Candidate main.py:200–229 and local delivery.py:13–31 both can send; runtime co-activity **UNVERIFIED** | One account-bound processing/sending owner, fenced handoff and durable operation contract; prove one external send per approved synthetic intent and reconcile uncertainty |
| IR-03 Critical — facility privacy / security + business | Public tables lack account/facility scope; local ingestion uses one configured facility, import uses a supplied facility for a whole input; no approved record-to-facility map | Approved explicit account/source/facility mapping with unknown scope denied; cross-facility and multi-account fixtures, phone reuse review; never authorize from QR attribution alone |
| IR-04 Critical — credential exposure / security | Original audit identifies embedded Meta/Redis/verification credentials; active revocation status **UNVERIFIED** | Owner-coordinated rotation/revocation and old bundle/archive removal before production integration; secure secret delivery and continuity plan. No rotation is authorized in this audit |
| IR-05 High — incomplete or misleading history / clinical + business | Candidate main.py:200–234,2110–2113 excludes fixed UI/shop inputs, saves whole split answers, can save bot history despite HTTP failure | Label captured history and unknown delivery; approved transport ledger/lineage before completeness claims; do not alter AI history for dashboard convenience |
| IR-06 High — hidden message loss/retry / technical | Candidate main.py:2024–2036 preclaims before processing and fails open; 2143–2152 acknowledges processing errors | Verify actual deployed behavior; owner-approved durable completion/retry design and crash tests. Do not copy candidate reliability claims without evidence |
| IR-07 High — event ordering / technical | Local db.py:190–196 permits delivered→failed; delivery.py:55–63 has status-before-history race | Add occurred/received timestamps, append-only evidence, deterministic derivation/reconciliation and concurrent status/send fixtures in a separately approved implementation |
| IR-08 High — stale-worker writes / technical | Local delivery.py:41,53–54,67–70 lacks claim fencing between sending, stale→unknown and completion | Owner/attempt token, lease expiry and conditional completion; demonstrate stale worker cannot overwrite a newer decision or cause a manually retried duplicate |
| IR-09 High — AI data disclosure / security + clinical | Candidate main.py:1311,1338,2099,2134 logs context/prompts/payload; translation client:333–383 can send clinical text to Gemini | Verify deployed logging/egress settings and processors; approve minimized routing/retention, sanitize observability; local logging fixes do not secure a separate deployed bot |
| IR-10 High — provenance/unknown writers / technical | Remote schema resembles candidate but environment binding is unknown; user_state has no identified writer | Writer register tied to deployed commits/credential principals; no table removal, schema overwrite, blanket import or assumed single source |
| IR-11 High — access/control boundary / security | Draft staff/allowed helpers trust backend-set subject/issuer; worker has broad table-level access; no remote roles/memberships | Dedicated protected logins, role/grant/definer audit, no browser credentials or broad API-role membership; database does not independently validate Firebase JWTs in this design |
| IR-12 High — new account/handoff authority / security + business | UI can register with Firebase; actual provider enrollment unknown; role display is local. Candidate agent accept main.py:343–374 is read-modify-write | Controlled staff provisioning/revocation, scoped audit and independent membership authority; atomic handoff acceptance and owner epoch before outbound integration |
| IR-13 High — state/history divergence / technical + clinical | Full private business-store draft has no synchronization; public users and user_state differ; candidate state storage failures can appear empty | Prefer thin source read adapter and private control metadata; preserve bot state/context/TTL and existing writers; no bidirectional sync or new-private canonical cutover without a separate migration project |
| IR-14 High — clinical logic limits / clinical approval | Risk module is unchanged English regex with ranking/negation limits; reference guardrails are source heuristics | Clinician-approved regression/labeling and escalation protocol; keep current inference/triage behavior unchanged during observer slice; local test passes are not medical efficacy evidence |
| IR-15 High — recovery / technical + security | No tested production backup, consistent export, reverse replay, RPO/RTO or rollback operator evidence | Validated encrypted backup/restore in isolated environment and feature-specific rollback rehearsal; preserve new writes/provider IDs before any later writer switch |
| IR-16 Medium — read-only operational load / technical | Local db.py:61–82 loads full histories per list item; rudo-api.js:30–37 fetches up to 10,000 entries | Summary-first/keyset queries, bounded on-demand history, tested indexes/latency/resource budget, observer disable switch; no live full scan to prove readiness |
| IR-17 Medium — access modes / security | RUDO_ENABLE_REMOTE_WRITES gates all remote access; local reads append audit records; current API has no observer-only mode | Separate least-privilege observer role and server-side write disablement; audit channel separated from read-only public transaction; no flag-only rollout |
| IR-18 Medium — sessions / security | Firebase backend checks revoked state; RudoAuth authReady caches its initial user; signOut catches via finally redirect; stale local role display possible | Test identity A→B, session revocation, timeout, signout failure and recent-login deletion; display roles never authorize; define staff deprovision and retention separately |
| IR-19 Medium — retention/expiry / privacy | kv expiry is not a proven deletion schedule; import retains source_payload, state expiry is read-time behavior | Owner-approved retention, backup lifetime, cleanup/crypto deletion and export custody; map absolute expiry; no automatic import of logs or cake/payment images |
| IR-20 Medium — metrics / business + clinical | Poster 2 UI/API difference and keyword-derived conversion/closure/response-time definitions | Approve definitions/timezone/source coverage; golden fixtures; label uncertainty instead of interpreting absent history as no care event |
| IR-21 Medium — deployment/supply chain / technical | Python 3.12 local vs unknown host; API/worker scheduler/ADC/TLS/network settings unverified; inline-compatible CSP and old Firebase compat SDK retained | Pin artifacts, dependency advisory review, verified host topology, strict server secret custody and staging provider/browser tests before deployment |
| IR-22 High — reply-queue semantics / clinical workflow | Local db.py:79–82 appends pending/failed/unknown intents as bot-role history; chats.html:getChatState 311–326 infers needs-reply from the last role | Keep intents separate from communication evidence; a failed/pending send must not clear a patient needs-reply item or become an actual response in analytics; add failure-state UI fixtures before staff sending |

IR-07, IR-08 and IR-22 are gates for a later transport/staff-send release. The synthetic read-only observer can be developed while those capabilities stay disabled and lack production sender credentials. Pre-existing bot risks require named owner disposition; they do not authorize an unrequested bot rewrite during observer integration.

## Authentication and authorization assessment

The intended path is Firebase SDK → ID token → Flask Firebase Admin verification (including revoked/disabled identity) → active `(issuer,subject)` membership → facility scope → transaction-local rudo_api role and protected SQL policies. Evidence: `rudo/auth.py:14–36`, `app.py:55–68`, `rudo/db.py:43–59`, draft SQL:20–39,134–168.

This path has been tested with synthetic identities and ephemeral signing keys; actual Firebase project ownership, ADC permissions, provider settings, MFA policy, real staff membership and deployment environment remain **UNVERIFIED**. The browser project config names dawa-ca263; that is a configuration clue, not console/ownership evidence. No real accounts were created/read and no existing credentials were changed.

Required policy decisions and implementation gaps:

- Define who provisions/deactivates staff and facilities, with separate administrative authority and audited approval. The inspected remote schema has none of these control objects; current local code has no staff-management API.
- Admin is scoped to listed facilities, not a global bypass. Operator/admin write permissions are presently similar; the `writing` helper parameter does not implement a separate finer-grained policy. Decide clinician, operator, analyst and account-administration duties explicitly.
- Source public tables cannot be directly exposed to Firebase users by treating local roles or a public API key as authority. Scope remains a protected server/database assignment.
- If a database credential is exposed, its holder can assert the custom identity context accepted by these helpers. Never grant rudo_api/rudo_worker membership to broad Supabase roles or expose a generic SQL/RPC path; keep logins least-privilege and private.
- Provide a real multi-facility selection workflow. The current UI safely refuses new-conversation creation unless the staff member has one facility (`chats.html`, new-chat handler after sendMessage); it does not solve source-record facility ownership.
- `authReady` caches the initially resolved Firebase user for the page lifetime (`js/rudo-auth.js:84–101`). Reauthentication/account-switch behavior needs coverage; the server still checks every supplied token and membership.
- Client signout removes local markers/preferences and calls Firebase signOut (`126–138`), but it is not global token revocation. Deleting identity (`141–162`) does not erase clinical records, remove all membership metadata, or implement a retention policy. [Firebase session semantics](https://firebase.google.com/docs/auth/admin/manage-sessions).

## Safety and privacy boundaries

The clinical reviewer must assess scope labels, human escalation and language/failure behavior using approved synthetic cases before staff rely on the observer. No model, translation, triage category, rank, prompt or guardrail was modified. Do not interpret a no-match regex result as safe, a closed UI status as handoff ownership, or an AI-context row as a complete care record.

Approve actual third-party destinations and payload minimization from the deployed configuration. The candidate's translation fallback means a statement that Gemini receives only language labels would be incorrect for this source. No inference endpoint was contacted to verify runtime behavior, and no patient prompt was used.

Keep source exports, message content, addresses, phone mappings and retained source_payload restricted and out of logs/screenshots/reports. This audit retains safe catalog metadata and aggregate planner estimates only. Exact data parity, cleanup and regulatory suitability are **UNVERIFIED**; no compliance certification is claimed.

## Approval categories

| Category | Required decision/evidence owner |
|---|---|
| Technical blockers | Application/hosting/Meta owners identify deployed callback, commit, sender, writer contracts, read interface and scheduler; platform owner approves staged roles/policies and restore procedure |
| Business decisions | Dawa Health product/data owner approves authoritative source, facility mapping, staff powers, transcript/analytics definitions and exclusions |
| Security approvals | Security/platform owners approve secrets response, access model, processor egress, least privilege, artifact/backup custody and monitoring |
| Clinical approvals | Named clinical owner approves unchanged-path regression evidence, escalation protocol and honest staff-facing limitations |
| Release approval | Named release/rollback owners approve exact stage/production actions, window, thresholds and reversal evidence; not implied by CLI access or this report |

No stakeholder was contacted or account/configuration changed by this audit. Owners/approvers are role placeholders until explicitly assigned.
