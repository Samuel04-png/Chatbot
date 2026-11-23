# Staff authentication: Firebase Auth → Supabase Auth (foundation)

> **Superseded (2026-11-23):** the staff-only import (`migrate_staff_auth.py`, `staff_inventory.py`) is removed. Every Firebase account is now migrated with no access granted by import; see [FULL_MIGRATION.md](FULL_MIGRATION.md). The verification notes below still apply.

Release 2 of the [production plan](../release/RELEASE_1.md). Status as of 2026-11-21: **implemented and verified locally with synthetic accounts and a real local Supabase Auth server.** No real Firebase users were exported. No Supabase project was changed, nothing was deployed, and no remote schema was touched. Firebase stays the default sign-in path (`RUDO_IDENTITY_PROVIDERS=firebase`, `RUDO_BROWSER_AUTH=firebase`).

Scope is **staff accounts only**. Patients don't have dashboard accounts. The bot's six public tables, inference, webhook, sending and writes are untouched: `snapshot()` hashes are unchanged across the import tests.

## How identity maps to authority

Every staff member has one internal id (`observer_control.staff.id`, a UUID). Each login maps to that id in
`observer_control.staff_identities` (`issuer`, `subject` → `staff_id`). A Firebase UID and a Supabase Auth UUID
are different rows for the same person. At most one login per provider per person is allowed, and each login
belongs to exactly one person.

- **Roles and facilities belong to the person, not the login.** Suspending the person, or removing a facility, applies to every login on their next request.
- **New sign-ups grant nothing.** A verified sign-in with no mapping is recorded in `identity_requests` and gets `403 staff_required`. Approval needs both of these:
  - an admin's invitation for that email, with a role and facilities, or naming an existing person to add a second login;
  - the person's own sign-in whose **verified** email matches.

  Approval is done in `staff.html` through database functions that re-check the admin.
- **Never matched by email alone.** Firebase and Supabase are never linked automatically.
- **Password import.** The Release 2 import (`scripts/migrate_staff_auth.py`) links each created Supabase user to the existing staff id with `link_method='auth_import'`. It is idempotent and refuses email collisions.

## Verified against a real Supabase Auth server (local, synthetic)

`scripts/verify_auth_import_local.py` ran against a disposable local stack (Supabase Auth v2.192.0, CLI 2.109.1). It used a freshly generated random signer key and synthetic accounts, never the project's values. Results are in `.local/auth-import-compat.json`:

| Check | Result |
|---|---|
| Admin create-user accepts a `$fbscrypt$v=1,n=14,r=8,p=1,ss=…,sk=…$salt$hash` `password_hash` | yes |
| Original Firebase password signs in; wrong password rejected | yes / yes |
| Access token algorithm; `SupabaseVerifier` accepts it | ES256; yes |
| Hash rewritten to bcrypt after a successful login | **no**: stays `$fbscrypt$` |
| Signed-out token rejected by the session check; still accepted by signature-only verification | yes; yes, which is why the session check is on by default |
| Admin create accepts a custom UUID `id`; duplicate email refused (HTTP 422) | yes; yes |
| Self sign-up creates an identity only; recovery email issued (seen in local Mailpit) | yes; yes |

My Firebase modified-scrypt implementation reproduces Firebase's published test vector (`tests/test_staff_auth.py`). The format matches Supabase Auth's source (`internal/crypto/password.go`): `n` is the exponent (N = 2^n), and the base64 fields are standard padded. Firebase exports in either base64 alphabet are normalised.

**Trade-off to accept or mitigate.** Supabase does not rehash on login. Every migrated password row in `auth.users` therefore contains the project's Firebase **signer key** (`sk=`). Access to `auth.users` already implies hash access, but the signer key is project-wide and can't be rotated. Mitigation: after cutover, ask migrated staff to set a new password via the reset flow, which stores bcrypt. Or skip hash import and require a reset for everyone; staff count is small.

**Not verifiable locally (needs the staging project):** automatic Google identity linking for imported Google-only staff. Supabase documents automatic linking by matching email; the importer creates these users with `email_confirm=true` and no password. Also unverified locally: real email delivery, redirect URL allow-lists, and the rate limits and CAPTCHA configuration.

## Import procedure (staging first; production needs separate approval)

1. **Rotate the exposed key first.** Follow [KEY_ROTATION.md](../security/KEY_ROTATION.md). Use only the new key file.
2. **Inventory, read-only.** Run `.venv/bin/python scripts/staff_inventory.py`. It compares every Firebase user against approved staff records:
   - non-staff are counted but never listed or imported;
   - held accounts carry reasons (`staff_record_inactive`, `firebase_user_disabled`, `duplicate_email`, `unverified_email`, `password_export_unavailable`, `unsupported_provider:*`);
   - staff records with no Firebase user are listed.

   Output goes to the gitignored `.local/staff-inventory.json` and contains no hashes. **An owner must review this list.**
3. **Dry run.** Run `scripts/migrate_staff_auth.py --actor <admin>` and review the per-UID results: `would_create`, `already_linked`, `link_existing`, or `conflict_email_exists`. Email conflicts are never auto-linked.
4. **One dedicated test account.** Run `--execute --confirm-project <ref> --only-uid <test-uid>`. `RUDO_AUTH_IMPORT_ALLOWED_REF` must equal the same staging ref. Then confirm all of these on staging:
   - password sign-in, wrong password, Google sign-in and linking;
   - reset email and recovery, sign-out revocation;
   - pending sign-up;
   - same conversations and scopes as the Firebase login.
5. **Remaining staff.** Run without `--only-uid`. Re-runs are idempotent: linked staff are skipped, and a user created by an interrupted run is linked rather than duplicated.
6. **Parallel period.** Set `RUDO_IDENTITY_PROVIDERS=firebase,supabase`. Move `RUDO_BROWSER_AUTH` to `supabase` only after staging sign-off. Firebase stays available for rollback: flip both variables back, and no data changes are needed.
7. **Retire Firebase** only after separate approval: remove `firebase` from `RUDO_IDENTITY_PROVIDERS`, then delete the hash-parameter variables and key files.

## Still required before production

- Owner decision on the signer-key trade-off above (import hashes and force a reset, or reset-only).
- Release 1 (the staff schema and dashboard) must be live first.
- Supabase project configuration:
  - asymmetric JWT signing keys (the verifier refuses HS256);
  - Site URL and redirect allow-list for `staff-login.html` and `staff-reset.html?mode=update`;
  - Google provider credentials;
  - email templates and SMTP;
  - leaked-password protection, minimum password length 12, CAPTCHA and rate limits;
  - optionally disable public sign-ups and use admin invites instead.
- Add a Subresource Integrity hash for the pinned `@supabase/supabase-js@2.45.4` script, or self-host it.
- Staging verification of every step-4 check with a dedicated test account, plus an approved staff/facility map from the owner.
- Decide who holds the administrator role for `staff_admin.py` and where its owner connection credential lives.
