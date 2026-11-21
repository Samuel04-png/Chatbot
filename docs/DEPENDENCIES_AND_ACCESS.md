# Dependencies and owner access requests

> Historical discovery baseline. Local implementation is now authorized and documented in [LOCAL_IMPLEMENTATION.md](LOCAL_IMPLEMENTATION.md); original source references below describe the audited snapshot. Remote execution remains pending review.

Date: 2026-11-20. No credentials or account changes are requested in chat. This audit is complete without private platform access. **No platform credentials are required to start the next local, synthetic-only development stage** after the owner approves its scope. Integration and production access are later gates, not prerequisites for writing unit tests or preparing reviewed changes.

## Decisions needed first

| Priority / timing | Owner request | Why / completion evidence |
|---|---|---|
| 1 — Start development | Review this audit and authorize a bounded local stabilization/migration implementation scope | Current instruction stops after documentation; owner review determines next work |
| 1 — Start development | Name application/data owner and confirm active bot/callback deployment, its source/commit, and which service writes conversations/orders/referrals | Local webhook does not persist messages; changing the wrong app cannot deliver continuity. Public callback hostname and deployment identifiers are enough initially; no secrets |
| 1 — Start development | Confirm healthcare pages/key namespaces in scope; expressly include or exclude cake orders and the second Redis database | Prevent unrelated commerce/payment data being mixed into healthcare migration |
| 1 — Start development | Approve retaining Firebase initially and define staff roles/facility access; nominate clinical reviewer | Establish API contracts and test role matrix. Names of roles and synthetic staff fixtures suffice initially; actual UID inventory comes later |
| 2 — Before analytics acceptance | Decide whether Poster 2 belongs in reports; define closure/resolution, conversion, unique-referral counts, date timezone and handling of demo data | Existing views disagree; migration must distinguish preserved behavior from approved corrections |
| 2 — Before approved data integration | Name retention/data-access approver, approved hosting region, backup retention and recovery objectives | Guides schema/backup design and permissible data handling; real records remain outside prompts/logs |

## Supabase

| Needed | Timing | Reason / secure method |
|---|---|---|
| Confirm new isolated staging project versus existing project; share non-secret URL/ref and owning organization | Later integration | Prefer isolated staging; existing project may already serve the newer bot. Project identifiers alone are not privileged keys |
| Sanitized current schema/grants/RLS/functions/extensions and existing bot table contracts, if project exists | Later integration, before SQL implementation targets that project | Avoid collisions, validate third-party auth and compatibility; schema-only export should exclude secrets/function literals containing credentials |
| Invitation with least required development permissions; explicit authorization for staging DDL and backups | Later integration, before any external writes | Connection does not imply permission to migrate. No project creation, table changes or deployment authorized now |
| Server runtime DB credentials / worker-import privileges provisioned securely | Later integration when execution is approved | Owner sets restricted credentials in approved local secret store/deployment environment; never paste into conversation or repo. Browser never receives service/secret keys |
| Production project access, tested backups/PITR or equivalent recovery, final release approval | Production only | Needed for controlled cutover and recovery, not local development |

## Firebase

| Needed | Timing | Reason / secure method |
|---|---|---|
| Confirm project `dawa-ca263` ownership and whether it is the correct environment | Later integration | Source configuration is a clue, not ownership proof |
| Read-only provider, authorized-domain, MFA/session and custom-claim configuration | Later integration | Verify actual email/Google login, signup restrictions and revocation behavior |
| Approved staff UID/role/facility mapping and disabled-user policy | Later integration before real staff tests | Store restricted inventory outside documentation/prompts; test fixture users separately; no need for passwords |
| Backend verification identity through least-privilege approved service account/ADC and test identities | Later integration | Validate tokens and revocation; provision via secure env/file path or workload identity outside repo |
| Authorization to configure Supabase Firebase integration/custom claims, if selected | Later integration | Required for RLS token forwarding; additive changes must preserve existing claims |
| Authorized account export / provider migration access | Only if separately choosing Supabase Auth | Not required for the recommended Firebase-retaining stage; do not export password hashes unnecessarily |

## Upstash Redis

| Needed | Timing | Reason / secure method |
|---|---|---|
| Database IDs/ownership for primary host and, only if scoped in, second host | Later integration | Identify approved data source without using embedded credentials |
| Owner-approved schema/key-pattern/type/count/PTTL inventory, external-writer list and expiry rules | Later integration | Determine string versus list/hash structures, active sessions and all writers; provide aggregate or redacted information first, no phone-bearing keys in chat |
| Encrypted consistent export/backup, snapshot time, checksums and restore instructions | Before any approved real-data import | SCAN during writes is not a consistent backup; use private restricted storage; decryption material delivered separately via secret manager |
| Time-limited read-only exporter access, if backup cannot answer approved questions | Later integration, explicit data-access approval first | Configure privately with approved scope; no use of compromised source tokens |
| Final delta/write-pause plan, source retention and cleanup approval | Production only | Prevent missed writes and maintain rollback continuity |

## Meta WhatsApp

| Needed | Timing | Reason / secure method |
|---|---|---|
| Non-secret app/business/phone-number IDs, authoritative sender and exact active callback service; enabled webhook fields | Later integration, identity of active service needed early | Browser/server IDs and API versions differ; verify which route handles real messages |
| Separate staging app/number and explicitly authorized test recipients | Later integration | End-to-end messaging must never use patients or production recipients |
| Secure server-only test access token, app secret, verification token and approved webhook config access | Later integration after staging approval | Signature checks require app secret; verify token is separate; configure in secret store, never conversation |
| Production rotation/callback plan with owner and rollback window | Production only | No webhook changes, token rotation or real messaging authorized in this assignment |

## Namecheap and deployment

| Needed | Timing | Reason / secure method |
|---|---|---|
| Sanitized cPanel Python app configuration: Python version, WSGI startup/entry point, working directory, URL/subpath, process manager, proxy/TLS controls and environment variable names | Later integration | No Passenger/WSGI config provided; Flask direct-run is not proof of deployed runtime |
| Source/deployment map for cPanel, Vercel, Hugging Face and other active services | Active writer identity before implementation; detailed hosting later | Determine callback ownership, route rewriting, scheduled workers and persistence boundaries |
| Sanitized operational errors/metrics if needed | Later integration, only when a specific question needs them | Owner filters body/phone/token/health data first; no request for raw server logs |
| Restricted staging deploy access, backup/restore procedure and intended worker/scheduler runtime | Later integration | Test deployment layout and durable work processing without touching active service |
| Named deploy operator/rollback owner, release window, recovery thresholds and explicit production permission | Production only | These are release prerequisites, not inferred from cPanel access |

## GitHub and AI services

The public reference was readable without access grants. Confirm canonical repository/organization, intended branch and deployed commit; source README and requested repository ownership differ. Provide missing `supabase_schema.sql` or actual schema-only export through approved private storage if the newer bot is relevant. Confirm license/reuse rights before copying components.

No Hugging Face, Gemini or model token is needed for the dashboard persistence migration. If later integrating the bot, request private read access only where needed, deployed API contracts and versions, model/adapter identifiers, safe synthetic response fixtures and clinical evaluation protocol. Staging model endpoints/credentials, data-sharing authorization and multilingual clinical review are **later integration** requirements. Production model hosting permissions are **production only**. The newer source can route translations to Gemini; owners must approve that actual data flow, not rely on its README description.

## Secure provisioning rule

Use platform invitations and least-privilege identities. Owners enter secrets directly into the approved deployment secret manager or a permission-restricted local file outside version control when required. Share only variable names, non-secret IDs and success/failure metadata here. Use encrypted private backups with separate key delivery. Never paste passwords, access tokens, private keys, Firebase credential JSON, patient records or unredacted Redis exports into conversation. No private integration access or production change is necessary for reviewing these documents.
