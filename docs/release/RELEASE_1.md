# Release 1: production dashboard (for approval)

**Status: prepared and rehearsed, NOT applied.** Nothing has been changed in production. Every production query so far has been read-only, run inside `BEGIN READ ONLY … ROLLBACK`, and returned only metadata or aggregate counts.

## What Release 1 delivers

- A read-only Rudo dashboard over the bot's existing Supabase data: conversations, message history, orders, referrals and supported analytics.
- Supabase-managed staff: profiles, roles, invitations, approvals, suspension, facilities and audit.
- Firebase stays the sign-in provider (Mode A).
- The bot stays the only writer and sender. Staff messaging stays disabled.

## Target

| | |
|---|---|
| Project | `cktfbpnxpfbyroqzuibc` ("Rudo"), eu-west-1, PostgreSQL 17.6 |
| Applied as | `postgres` (not a superuser; has BYPASSRLS and CREATEROLE), in **one transaction** |
| Migration | [`supabase/migrations/20261121120000_rudo_staff_control.sql`](../../supabase/migrations/20261121120000_rudo_staff_control.sql), sha256 `350b0236…efca44` |
| Rollback | [`supabase/rollback/20261121120000_rudo_staff_control.down.sql`](../../supabase/rollback/20261121120000_rudo_staff_control.down.sql), sha256 `9c085b63…efd95bd` |

## Verified production facts (2026-11-21, read-only)

- **Writers.** `pg_stat_statements` shows the bot writes every table as **`service_role`** (BYPASSRLS). `postgres` appears only for selects and a few deletes. There are no `rudo_*` roles, no policies on the six tables, no triggers, and RLS is enabled on all six.
- **Data.** 916 users, 7,861 messages (596 phones), 5 orders, 1,356 referrals, 25 kv rows, 0 user_state rows. The latest message is at 2026-11-20 09:16 UTC, so the bot is active.
- **Message order.** Order by `id` (insert order) differs from `created_at` order for exactly 1 message. The dashboard orders by `id` and shows each message's timestamp.
- **Backups.** **None. Physical backups list is empty and PITR is disabled.** See blocker B1.
- **Default privileges.** In schema `public`, new tables and functions are granted to `anon` and `authenticated`. The migration therefore uses a separate schema, `observer_control`, which the Data API does not expose, and revokes all grants on it from `anon`, `authenticated` and `service_role`.
- **Fixture match.** The local test fixture matches production column for column (type, nullability, identity), including all 21 columns the migration grants.
- **Pre-check baseline** (`deploy/release/precheck.sql`): `observer_control_exists=false`, `rudo_roles=[]`, `public_policies=0`, `rls_enabled_all=true`, `acl_fingerprint=e67855d42d2eff721a28e78c35cc4919`.

## Exact effect on the bot's tables (rehearsed on Supabase's own Postgres image)

| Object | Change |
|---|---|
| Table ACLs on all six tables | **Unchanged** (fingerprint must stay `e67855d4…`) |
| RLS enable/force flags | **Unchanged** |
| Policies | **Added** 4: `rudo_observer_read` `FOR SELECT TO rudo_observer` on users, messages, orders, referrals. The `USING` clause allows only phones with exactly one approved facility mapping in the caller's scope. None removed. |
| Column grants | **Added** 21 `SELECT` grants to `rudo_observer` only: users(phone, user_id, language, created_at, updated_at), messages(id, phone, role, message, created_at), orders(id, phone, product, price, quantity, status, created_at), referrals(id, phone, source, created_at). None removed. |
| Not granted | `messages.message_en`, `orders.address`, `users.state`/`step`, all of `kv` and `user_state` |
| Schema `public` | `USAGE` added for `rudo_observer` |
| Rows | None read or written by the migration |
| `service_role` / bot behaviour | Unchanged: insert, update, delete and select round trip verified before, during and after the migration and after rollback |

**New objects.**
- Schema `observer_control`:
  - tables: `facilities`, `staff`, `staff_identities`, `staff_scopes`, `staff_invitations`, `identity_requests`, `source_mappings`, `access_audit` (append-only), `staff_admin_events` (append-only)
  - security-definer functions with fixed `search_path`
- Three `NOLOGIN`-free login roles, each `NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOINHERIT` with no memberships:

| Role | Can do | Cannot do |
|---|---|---|
| `rudo_observer` | Read-only by default; minimal columns of mapped rows only | Read `kv`, `user_state`, model context or addresses; read staff mappings; write anything |
| `rudo_observer_audit` | Append access-audit rows; record pending sign-ins | Read anything |
| `rudo_staff_admin` | Call `admin_*` functions | Read or write tables directly. Each function re-checks *inside the database* that the verified caller is an active admin, limits granted facilities to the admin's own, blocks self-changes, keeps at least one admin, and appends an event. |

**Rehearsal evidence.**
- [supabase-image-rehearsal.json](evidence/supabase-image-rehearsal.json): 25 checks, all true. Covers apply as non-superuser `postgres`; API roles locked out; least privilege per role; a real Supabase Auth sign-in through the dashboard; facility scope, ordering, orders and analytics; admin invite; rollback restores identical state; second apply and rollback cycle.
- [supabase-auth-hash-compat.json](evidence/supabase-auth-hash-compat.json): Release 2 password-hash import.
- 162 local tests pass (see the [handover](../HANDOVER.md)).

## Blockers: what is needed from you before release

| # | Blocker | Needed | Why |
|---|---|---|---|
| B1 | **No backup exists.** | Database password (Dashboard → Project Settings → Database) and a backup passphrase, set as environment variables for `scripts/backup_production.sh` | Backup and verified restore are required before any change |
| B2 | Hosting for the dashboard | A platform that runs the Docker image (Render, Fly.io, Railway, Cloud Run…) or a server, plus the URL or domain | There is no verified dashboard URL yet |
| B3 | Facility access decision | Approve the facility list and mapping rule (below) | Unmapped conversations are invisible by design |
| B4 | First admin | Tari's sign-in email and **Firebase UID** (Firebase console → Authentication → Users → User UID) | Bootstraps the only admin; Tari invites everyone else in the Staff page |
| B5 | Firebase authorized domain | Add the dashboard domain in Firebase console → Authentication → Settings → Authorized domains | Firebase login only works on allowed domains |
| B6 | Supabase CA certificate | Download into `deploy/certs/prod-supabase.crt` (Dashboard → Database → SSL Configuration) | Required for `sslmode=verify-full` |
| B7 | Your explicit approval of this document | "Approved: Release 1 as documented" | |

**Not a blocker for Release 1:** the exposed Firebase service-account key. The dashboard never uses it: `RUDO_FIREBASE_CHECK_REVOKED=false` still verifies every token's signature, expiry, audience and issuer, and access is revoked by suspending staff. **The key is still a live credential for your Firebase project, so delete it in Google Cloud regardless.**

### B3: facility mapping decision

Mapping each phone by its normalized referral source ([`deploy/facility_rules.json`](../../deploy/facility_rules.json)):

| Facility | Phones mapped to exactly one facility |
|---|---|
| N'gombe Clinic | 168 |
| Chelstone Clinic | 141 |
| Avondale Clinic | 89 |
| Mandebvu Clinic | 78 |
| Mandebvu Pharmacy | 55 |
| **Total** | **531 of 919** (314 have messages) |

- **14 phones are ambiguous** (referrals from several facilities). They stay hidden unless mapped manually (`map-csv`).
- **374 phones have no clinic referral** (269 have messages). Examples: "Cancer Awareness", "Zim 3", or no referral at all.

Options for the 374:
- **(a)** Keep them hidden.
- **(b)** Map them to a holding facility such as "Dawa central (unassigned)", visible only to staff given that facility (`map-remaining`). **Recommended:** Tari as admin gets every facility including the holding one; clinic staff get only their clinic.

## Execution after approval (each step verified before the next)

1. **Pre-check (read-only).** `supabase db query --linked -f deploy/release/precheck.sql`. Must match the baseline above. Users and messages may have grown; the latest message may be newer.
2. **Backup.** Run `SUPABASE_DB_PASSWORD=… RUDO_BACKUP_PASSPHRASE=… scripts/backup_production.sh`, then `scripts/verify_backup_restore.sh backups/rudo-<stamp>.tar.enc`. This restores into an isolated local database and compares counts with production. **Stop if it reports `RESTORE MISMATCH`.**
3. **Apply.**
   ```sh
   (echo 'BEGIN;'; cat supabase/migrations/20261121120000_rudo_staff_control.sql; echo 'COMMIT;') > backups/release1-apply.sql
   supabase db query --linked -f backups/release1-apply.sql
   ```
   This is a single transaction. Any error aborts it with no partial change.
4. **Login passwords.**
   ```sh
   scripts/release1_credentials.py --pooler-host aws-1-eu-west-1.pooler.supabase.com
   supabase db query --linked -f backups/release1-set-passwords.sql
   ```
   Only SCRAM verifiers are sent. Copy `backups/release1-dashboard.env` into the hosting platform's secrets, then delete it.
5. **Post-check (read-only).** `supabase db query --linked -f deploy/release/postcheck.sql`. Expect all of the following:
   - three roles, none superuser, BYPASSRLS or CREATEROLE, each with a password
   - only the 4 `rudo_observer_read` policies
   - `acl_fingerprint` unchanged
   - API roles `false` on `observer_control`
   - kv, user_state, message_en and address not visible to `rudo_observer`
   - counts unchanged or growing
6. **Facilities, mappings, first admin.** Use the owner connection, with `RUDO_CONTROL_ADMIN_DATABASE_URL` set to the postgres pooler URL, `sslmode=verify-full`, and `RUDO_STAFF_ADMIN_ALLOW_REMOTE=true`.
   ```sh
   S=scripts/staff_admin.py; A=--actor owner
   $S facility-add --account rudo-whatsapp --facility ngombe-clinic --name "N'gombe Clinic" $A   # ...and the other 4 (+ holding, if B3(b))
   $S map-referrals --rules deploy/facility_rules.json $A            # dry run: counts only
   $S map-referrals --rules deploy/facility_rules.json $A --execute
   $S map-remaining --account rudo-whatsapp --facility unassigned $A --execute   # only if B3(b)
   $S bootstrap-admin --email <tari> --name Tari --firebase-uid <uid> --scope rudo-whatsapp:ngombe-clinic ... $A
   ```
7. **Deploy the image** with these environment variables:
   - `RUDO_MODE=observer`
   - `RUDO_OBSERVER_ALLOW_REMOTE=true`
   - the three database URLs and `RUDO_CURSOR_SECRET` from step 4
   - `RUDO_OBSERVER_SOURCE_ID=rudo-production`
   - `FIREBASE_PROJECT_ID=dawa-ca263`
   - `RUDO_IDENTITY_PROVIDERS=firebase`
   - `RUDO_BROWSER_AUTH=firebase`
   - `RUDO_FIREBASE_CHECK_REVOKED=false`
   - `RUDO_ALLOWED_ORIGIN=https://<domain>`
   - `RUDO_TRUST_PROXY=true`
8. **Verify the live URL.**
   - `/healthz` returns 200 and `/readyz` returns `ready`.
   - Tari signs in and sees conversations, orders, referrals and analytics.
   - Dashboard counts match `postcheck.sql` for Tari's facilities.
   - An invitation round trip works with a test staff account.
   - Re-run `postcheck.sql`: `latest_message_at` keeps advancing, so the bot is unaffected.
   - Only after this passes is the deployment "complete".

## Rollback

- **Dashboard only.** Stop or roll back the hosting service. The database stays and the bot is unaffected.
- **Database.**
  1. Export staff records first: `supabase db query --linked "SELECT … FROM observer_control.staff …"`, or rely on the step-2 backup plus a fresh `scripts/backup_production.sh`.
  2. Run `supabase db query --linked -f supabase/rollback/20261121120000_rudo_staff_control.down.sql`. It is one transaction with built-in post-condition checks.
  3. Re-run `precheck.sql`. It must show `observer_control_exists=false`, `rudo_roles=[]`, `public_policies=0` and the original `acl_fingerprint`.
- **Rehearsed.** Rollback restored byte-identical ACLs, policies and RLS twice, and kept all bot rows.

## Monitoring and operations

| What | How |
|---|---|
| Uptime | Hosting platform health check on `/healthz`; alert on `/readyz` returning not `ready`, which means the database or a restricted login is failing |
| Errors | App logs carry `route=<template> status=<code> ms=<n> request_id=<id>` only: no URLs, phones, tokens or bodies. Alert on 5xx rate, on `audit_unavailable`, which fails closed, and on `staff_admin_unavailable`. |
| Bot liveness | `postcheck.sql`'s `latest_message_at` (read-only). Alert if it stops advancing during normal hours. That signals a bot problem; the dashboard cannot cause it. |
| Access review | `observer_control.access_audit` (who read what, digests only) and `staff_admin_events` (every privileged change). Both are append-only, even for the owner. |
| Backups | Enable Supabase physical backups or PITR (paid plan) or schedule `backup_production.sh`. Today there are none. |
