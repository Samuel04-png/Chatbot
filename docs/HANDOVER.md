# Rudo dashboard: handover

Status as of 2026-11-21.

| What | Status |
|---|---|
| **Local version** | Built, tested and running locally. |
| **Production release** | Prepared and rehearsed, **awaiting approval and the items in [Release 1 blockers](release/RELEASE_1.md#blockers-what-is-needed-from-you-before-release)**. |
| **Production URL** | **Not yet assigned.** Deployment is not complete until the live URL passes the checks in Release 1, step 8. |

## Try it now (local, synthetic data)

On the handover machine:

```sh
scripts/start_test_database.sh               # temporary local database (prints its stop command)
.venv/bin/python scripts/bootstrap_observer.py
.venv/bin/python scripts/run_observer_demo.py
```

Then open http://127.0.0.1:5051/observer.html. All records are synthetic, and no real patient data or login provider is involved.

To switch identity, open the browser console and run `syntheticSwitchIdentity('<name>')`:

| Identity | What you see |
|---|---|
| `operator` (default) | Conversations, orders and referrals for Facility A |
| `admin` | Everything, plus the **Staff** page at `staff.html` |
| `analyst` | Analytics only |
| `other` | A different facility |
| `empty` | No records |

## What works

| Feature | Notes |
|---|---|
| Conversations | Searchable list and full captured history in source order, with 50-message pages and "load older". Marked read-only; delivery status is shown as unknown because the bot does not record it. |
| Orders, referrals | Exactly as the bot stored them (product, raw price, quantity, status, referral source, timestamps). Missing values say "Unknown / not recorded". |
| Analytics | Counts the source data supports: users, conversations, messages, orders and referrals. Delivery, conversion, response-time and clinical metrics are explicitly marked unavailable. |
| Facility scoping | Staff see only phones mapped to exactly one of their facilities. Unmapped and ambiguous conversations are hidden. |
| Staff management (admins) | Invite by email with a role and facilities; approve the person's verified sign-in; change roles; suspend or reactivate (effective on the next request); edit facilities; add a Supabase login to an existing person; full activity log. |
| Roles | **Admin**: everything plus staff management. **Operator**: conversations, orders and referrals. **Analyst**: aggregate analytics only. |
| States | Loading, empty, "pending approval", "not permitted", "source unavailable" and audit-failure states are all distinct. A failure never looks like an empty result. |
| Safety | No sending, editing or webhook in the dashboard. The bot stays the only writer and sender, and its tables are unchanged. |

## Signing in (production, Release 1: Firebase)

1. Tari, the first admin, signs in at `https://<dashboard>/login.html` with the existing Firebase email/password or Google login.
2. To add staff, Tari opens **Staff**, creates an invitation (email, role, facilities), and tells the person to sign in.
   - New people can create a Firebase login at `register.html` or use Google.
   - Until approved, they see "pending administrator approval" and no records.
3. Their verified sign-in appears under **Pending sign-ins**. Tari clicks **Approve**.
   - Approval only works when the sign-in's **verified** email matches the invitation, which prevents account takeover.
4. Forgot password: `forgot-password.html`.

## Architecture (short)

```
Rudo bot ──service_role──▶ Supabase Postgres: public.users / messages / orders / referrals / kv / user_state  (unchanged)
                                   ▲ SELECT only: mapped rows, minimal columns (RLS + column grants)
Browser ──Firebase ID token──▶ Flask dashboard ──rudo_observer (read-only)──┘
                                   ├──rudo_observer_audit──▶ observer_control.access_audit (append-only)
                                   └──rudo_staff_admin────▶ observer_control.admin_*() (admin re-checked in the DB)
observer_control: staff (internal UUID) · staff_identities (Firebase UID / Supabase UUID → staff id) · staff_scopes ·
                  facilities · staff_invitations · identity_requests · source_mappings · staff_admin_events
```

- **Data.** Supabase project `cktfbpnxpfbyroqzuibc`. No data is copied: the dashboard reads the bot's tables through a restricted login.
- **Staff.** Everything about staff lives in Supabase, under one internal ID per person, whichever login provider they use.
- **Keys.** No privileged key ever reaches a browser. The service-role key is not used by the dashboard.
- **Migration.** One versioned file, [supabase/migrations/20261121120000_rudo_staff_control.sql](../supabase/migrations/20261121120000_rudo_staff_control.sql), with a tested [rollback](../supabase/rollback/20261121120000_rudo_staff_control.down.sql).

## Authentication modes and switching

Switching is done with two environment variables plus a restart. No rebuild is needed.

| Mode | `RUDO_IDENTITY_PROVIDERS` | `RUDO_BROWSER_AUTH` | Sign-in pages |
|---|---|---|---|
| A: Firebase (Release 1) | `firebase` | `firebase` | `login.html`, `register.html`, `forgot-password.html` |
| C: Parallel (Release 2) | `firebase,supabase` | `firebase` or `supabase` | Both work; each login resolves to the same staff ID |
| B: Supabase (after Release 2) | `supabase` | `supabase` | `staff-login.html` (email/password, Google, request access), `staff-reset.html` |

- **Release 2 (staff login migration):**
  - Admins link a Supabase login to each person: Staff → "Invite Supabase login", the person signs in on `staff-login.html`, then the admin approves.
  - Alternatively, existing Firebase passwords can be imported with `scripts/migrate_staff_auth.py`. This is verified against Supabase Auth v2.192.0; see [auth-migration](auth-migration/README.md).
  - Firebase is never matched to Supabase by email alone.
- **Release 3 (cleanup):** remove Firebase only after every active staff member has signed in with Supabase and recovery has been tested.

## Tests (fresh, 2026-11-21)

| Suite | Result |
|---|---|
| `scripts/test_local.sh` (unit, database-authorization, API, admin-workflow, import, owner-CLI, three real-browser suites, existing bot regression) | **162 passed**, 2 expected failures (documented legacy transport gaps in the disabled private mode). Statement coverage 94%. |
| Firebase browser flow | 11 checks (sign-in redirect, wrong password, admin dashboard, invite → pending → approve → scoped access, non-admin refused, reset, Google) |
| Supabase browser flow | 14 checks |
| Dashboard browser flow | 17 checks |
| Release rehearsal on Supabase's own Postgres image, with real Supabase Auth | 25 of 25: [evidence](release/evidence/supabase-image-rehearsal.json) |
| Container | Runs as non-root; `/healthz` 200; no secrets, tests or docs in the image |
| Secret scan (`scripts/check_secrets.py`) | Clean |

Earlier synthetic results are not evidence for production. Production is proven only by Release 1 steps 5 and 8.

## Limitations

- **Captured history only.** The bot does not store WhatsApp delivery receipts or provider message IDs, so the dashboard never claims delivery.
- **Facility mapping is an owner decision.** Only phones with an approved mapping are visible (see Release 1, B3). New bot users need mapping too: re-run `map-referrals` (and `map-remaining` if chosen) on a schedule, for example daily.
- **Read-only.** Staff cannot reply or change orders. That needs a separately approved ownership and delivery contract with the bot.
- **Sign-out timing.** With `RUDO_FIREBASE_CHECK_REVOKED=false`, a Firebase sign-out or disable takes up to an hour to expire. Suspending the person in **Staff** takes effect immediately. Turn the check on once a **new** Firebase service-account key exists.
- **No backups yet.** Production has no physical backups and PITR is disabled. Enable them or schedule `scripts/backup_production.sh`.
- **Compromised key.** The exposed Firebase service-account key (`43a1573c…`) is not used by the dashboard but is still valid. Delete it ([procedure](security/KEY_ROTATION.md)).
