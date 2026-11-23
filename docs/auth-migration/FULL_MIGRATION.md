# Full Firebase → Supabase migration (every account, every Rudo data set)

**Goal.** Every Firebase account and every Rudo data set in Firebase reaches Supabase or is recorded with a recovery action. The goal is complete migration coverage. It is *not* approval of every account: importing an account never gives it dashboard access.

**Source:** Firebase project `dawa-ca263` (from `js/rudo-auth.js`).
**Target:** Supabase project `cktfbpnxpfbyroqzuibc`, Supabase Auth v2.198.0.

## Status (2026-11-23)

**Owner decision (2026-11-23).** Everything goes into Rudo's Supabase project, kept separate inside it:
- Accounts are tagged with `owner_app` and get no dashboard access.
- Firestore data goes into the private `firebase_import` schema, never into Rudo's `public` tables.
- dawaMom and dawaClinician already run on Supabase, so these copies are historical records.

**Firebase project `dawa-ca263` is shared by:**
- Rudo (web)
- dawaMom (web, Android, iOS)
- dawaClinician (Android, iOS)
- "Analytics" (`com.websolid.csdemo`, Android and iOS)

**Accounts: 87.** All are staged for import, and none need manual review.
- **By app:** 74 dawaMom, 2 dawaClinician, 11 Rudo or unknown.
- **Sign-in:** 80 password accounts, all with exportable hashes, so every password is kept. 8 Google accounts, 7 of them Google-only.
- **Verified email:** 11. The other 76 must confirm their email in Supabase.
- **None** disabled, phone, anonymous, MFA, tenant or duplicate.

**Firestore: 5,348 documents.**
- **By app:**
  - 4,411 dawaClinician: `parity` 4,339, `encounter` 40, `doctor` 21, `first_encounter` 10, `clinic` 1.
  - 675 dawaMom: `mobile_chats` 11 plus 590 messages, `mother` 24, `weeks_of_pregenancy` 40, and 10 records under `users/*` (period-tracker settings, daily notes).
  - 80 shared profiles (`user`).
  - 182 Rudo or unknown: `whatsapp_chats` 18 plus 162 messages, `chatbot_users` 1, `analytics` 1.
- **Realtime Database:** none (404). **Storage:** 2 buckets, 0 objects. **Cloud Functions:** none. **Hosting:** `dawa-ca263.web.app`.

**Exports** (encrypted, in `~/.rudo-migration/`):
- Accounts: sha256 `654ffeb5…`
- Firestore: sha256 `cc646b11…`

| Step | State |
|---|---|
| Firebase access (owner's Google login) | Done |
| Inventory, encrypted exports, dry-run plans | Done; read-only |
| Rehearsal on Supabase Auth v2.198.0 (accounts and Firestore landing) | **49/49 checks pass** |
| Migrations `20261123063840_firebase_account_migration`, `20261123085525_firebase_data_landing` | Written and rehearsed. **Not applied.** |
| Production backup and isolated restore test | **Not done.** Needs `SUPABASE_DB_PASSWORD` and `RUDO_BACKUP_PASSPHRASE`. |

## 1. Secure Firebase access (owner, one time)

Use your own Google account through Application Default Credentials. The login is short-lived, revocable and creates no key file.

```sh
brew install --cask google-cloud-sdk
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/firebase,https://www.googleapis.com/auth/userinfo.email,https://www.googleapis.com/auth/firebase.database
gcloud auth application-default set-quota-project dawa-ca263
```

- **Account:** use the Google account that is Owner, or at least has Firebase Authentication Admin and Viewer access, on `dawa-ca263`. Exporting password hashes needs that permission; without it, Firebase returns `REDACTED`.
- **Hash parameters:** Firebase console → Authentication → Users → ⋮ → **Password hash parameters**. Copy them into `.env` as `FIREBASE_SIGNER_KEY`, `FIREBASE_SALT_SEPARATOR`, `FIREBASE_ROUNDS` and `FIREBASE_MEM_COST`. They are already present in `.env`; the test-account import in step 4 confirms they are correct.
- **Delete the exposed key:** Google Cloud console → IAM → Service accounts → keys → delete `43a1573c…`.
- **After the migration:** `gcloud auth application-default revoke`.

## 2. Inventory (read-only)

```sh
.venv/bin/python scripts/firebase_inventory.py --project dawa-ca263
```

- **What it reports:** Firebase apps (web, Android and iOS, which shows whether Dawa Mom shares the project), enabled services, sign-in providers and MFA, and Auth totals by provider, verification, disabled, phone, anonymous, MFA, custom-claim keys, tenants and duplicates. It also covers Firestore databases, collections, document counts, subcollection groups and how many document IDs equal an Auth UID; Realtime Database top-level keys and child counts; and Storage buckets with object counts and bytes by top-level folder.
- **Where it writes:**
  - **On screen:** counts only.
  - **Per-account worksheet:** `~/.rudo-migration/inventory-*.json`, mode 600, outside Git. It contains emails and UIDs but no hashes.
- **Ownership boundary:** if apps other than Rudo use the project, the owner decides, per data set, whether it belongs to Rudo.
  - Accounts from other apps can be imported too. They get no dashboard access and their custom claims stay out of Supabase tokens.
  - Alternatively, list them in an exclusions file (`{uid: reason}`). They are then reported as `excluded_by_owner`, never skipped silently.
  - Other apps' data is never written into Rudo's `public` patient tables.

## 3. Account rules (implemented in `rudo/firebase_migration.py`)

- **Every Firebase account** gets exactly one outcome:
  - `create`: imported.
  - `already_imported`: a re-run.
  - `manual`: a reason is recorded.
  - `excluded_by_owner`: listed in the exclusions file.
- **Identity is matched by Firebase UID only.**
  - The Supabase user id is a fixed `uuid5(project, uid)` and `app_metadata.firebase_uid` marks the account.
  - An email or phone number already used by a different Supabase user becomes `manual`. It is never linked or merged.
- **Access:** importing grants nothing. Dashboard access exists only through `observer_control.staff_identities`.
  - The import only *copies* an existing Firebase staff link to the same internal staff id, which keeps the same role, status and facility scopes.
  - Nobody else gets a staff record or approval. When an imported non-staff person signs in, they become a pending request and see no patient rows (verified in the rehearsal).
- **Preserved per account:**
  - **In Supabase Auth:** email, phone, email-verified state, display name, photo, and the Google identity, linked by Google's own account id (never by email).
  - **In the private ledger:** creation and last sign-in times, providers, Firebase custom claims and MFA factor types.
  - **Disabled accounts:** imported banned (`ban_duration`).
  - **Unverified emails:** stay unverified, so sign-in is refused until the email is confirmed.
- **Custom claims** are never copied into Supabase tokens, because they may belong to another app. They stay in `firebase_migration.accounts.custom_claims`.

| Case | Outcome |
|---|---|
| Password with an exportable hash | Imported in Firebase's own scrypt format (`$fbscrypt$`). The same password works (rehearsed on v2.198.0). |
| Password, but Firebase returns `REDACTED` | Imported without a password, then set by reset email. Same user id (rehearsed). |
| Google only | Imported. Google sign-in works once the Google provider is enabled in Supabase; until then they can set a password by reset email. |
| Facebook, Apple, GitHub and other providers | Imported by email. Provider not linked (`provider_not_migrated:*`); password set by reset email. |
| Phone only | Imported with a confirmed phone. Sign-in needs an SMS provider configured in Supabase. |
| MFA enrolled | Imported. Firebase does not export MFA secrets, so the person must enrol again (`mfa_must_reenrol`). |
| Anonymous (no email or phone) | `manual`: `no_email_or_phone`. |
| Same email on several Firebase accounts | `manual`: `duplicate_email_in_firebase`. |
| Email already used in Supabase | `manual`: `email_used_by_other_supabase_user`. Never merged. |
| Identity Platform tenant user | `manual`: `firebase_tenant_user`. |

## 4. Run order (production steps need explicit owner approval)

1. **Backup:** `scripts/backup_production.sh`, then `scripts/verify_backup_restore.sh` (isolated restore).
2. **Apply** `20261123063840_firebase_account_migration.sql`, then `20261123085525_firebase_data_landing.sql`, as `postgres`, each in one transaction. Then set the `rudo_migrator` password (SCRAM verifier only) and put `RUDO_MIGRATOR_DATABASE_URL` in `.env`.
3. **Export:** `.venv/bin/python scripts/migrate_firebase_auth.py export`. This writes an AES-256-GCM encrypted file to `~/.rudo-migration/`; the key is in `~/.config/rudo/migration.key`, mode 600.
4. **Plan:** `migrate_firebase_auth.py plan --export <file>`. Dry run: prints the counts and writes the per-account worksheet.
5. **Test account:**
   - Set `RUDO_AUTH_IMPORT_ALLOWED_REF=cktfbpnxpfbyroqzuibc`.
   - Run `migrate_firebase_auth.py import --export <file> --execute --confirm-project cktfbpnxpfbyroqzuibc --only-uid <test uid>`.
   - Sign in with that account's Firebase password, then run `reconcile`.
6. **Everyone:** the same `import` command without `--only-uid`. It is idempotent and restartable; re-running it never duplicates anyone.
7. **Firestore:** `migrate_firebase_auth.py export-data`, then `plan-data`, then `import-data --execute --confirm-project cktfbpnxpfbyroqzuibc`, then `reconcile-data`. Each document is upserted by its original path; reconciliation compares every path and content hash.
8. **Reconcile:** `migrate_firebase_auth.py reconcile --export <file>` must show `coverage_complete: true` and 0 problems. Every `manual` row has a reason.
9. **Keep Firebase running** until the owner signs off. Do not delete Firebase users or data.

## 5. Firestore, Realtime Database and Storage (once the inventory shows data)

- **Firestore and Realtime Database:**
  - Land each data set in a private schema, `firebase_import`, keyed by original path or document id, with the original timestamps and `data jsonb`. Count-reconcile it against the source before any typed mapping.
  - Only owner-approved data sets get typed tables. Nothing is written into `public.users`, `messages`, `orders` or `referrals`.
  - Rows owned by a Firebase user keep the Firebase UID and resolve to the imported Supabase user through the ledger.
- **Storage:** private buckets (`firebase-<bucket>`) with the original object paths. Per-object size and MD5 are reconciled; there is no public access unless the owner approves it.

## 6. Rollback and recovery

- **Accounts:** `migrate_firebase_auth.py rollback --export <file>` is a dry run. Add `--execute --confirm-project …` to delete **only** users whose id is in the ledger *and* that carry the Firebase marker. Then run `supabase/rollback/20261123063840_firebase_account_migration.down.sql`, which removes the copied staff links, the schema and the role. Original Firebase staff links, staff records, scopes and all bot or patient tables are untouched (rehearsed).
- **Firebase** stays the source of truth until sign-off. Switching the dashboard back to Firebase login is `RUDO_IDENTITY_PROVIDERS=firebase` plus `RUDO_BROWSER_AUTH=firebase`.
- **Data recovery:** the encrypted export is the point-in-time source snapshot. The production backup (step 4.1) is the database restore point.
