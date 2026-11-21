# Replacing the exposed Firebase service-account key

**Status as of 2026-11-21: treat it as compromised.** A private key for `firebase-adminsdk-atqca@dawa-ca263.iam.gserviceaccount.com` (key ID starting `43a1573c`) was pasted into an AI chat session. It was never written to this repository: `scripts/check_secrets.py` finds no credential material. Possession of this key gives full Firebase Admin access to project `dawa-ca263`, including exporting every user's password hash and minting sign-in tokens. That access stays open until the key is deleted.

The Firebase **password-hash signer key**, the SCRYPT `hash_config`, was exposed in the same message. It can't be rotated for an existing project. That raises the value of any leaked password hashes; see step 7.

## Order of operations (no service interruption)

Do the steps in this order: create the new key before disabling the old one, and disable before deleting.

1. **Find every consumer of the old key.** In Google Cloud Console, go to IAM & Admin, then Service accounts, then `firebase-adminsdk-atqca`, then the Keys tab. Note the old key's creation date. Check "Key usage" (Policy Analyzer / Activity Analysis) to see when and where it was last used. Likely consumers:
   - the deployed Rudo bot or webhook host
   - any dashboard backend running Firebase Admin
   - CI secrets
   - developer machines

   Record each one with its owner. Any consumer you can't identify will break at step 5, which is what makes this order safe.
2. **Review for misuse since the exposure.** In Cloud Logging, check Admin Activity and Data Access audit logs, filtered to that service account and the old key ID. Look at auth exports (`downloadAccount`/`batchGet`), user changes, custom-token creation and IAM changes, from 2026-11-20 onward. In the Firebase console, check for new or changed users, especially staff and admin accounts. Escalate anything you can't explain before going further.
3. **Create the replacement credential.** Prefer no key file at all: workload identity or attached service accounts on Google Cloud hosts. If a file is unavoidable:
   - create a **new** key and download it directly to its destination secret store, such as the host's secret manager or a CI secret;
   - for local admin scripts, save it as `./firebase-service.json` and point `GOOGLE_APPLICATION_CREDENTIALS` at it (the file is gitignored);
   - never paste key contents into chat, tickets or email.

   Consider a separate, least-privilege service account for the read-only staff inventory and import scripts (Firebase Authentication Admin only) instead of reusing the full Admin SDK account.
4. **Roll the new key to each consumer from step 1.** Restart each one and verify with a harmless read, such as an ID-token verification or listing one user, before moving on.
5. **Disable (don't delete) the old key.** This step can be undone. Watch error rates and logs for 24–48 hours. If something breaks, it is an undiscovered consumer: re-enable briefly, migrate it, then disable again.
6. **Delete the old key.** Then confirm the Keys tab lists only the new key or keys.
7. **Signer-key exposure follow-up.** Because the signer key can't change:
   - keep the export of password hashes (step 2 of the auth migration) to the minimum number of runs;
   - delete exports immediately;
   - once staff are on Supabase Auth, ask each migrated staff member to set a new password through the reset flow. New passwords are stored as bcrypt, which removes Firebase-scrypt material from `auth.users`.
8. **Clean up copies.** Delete the downloaded `dawa-ca263-firebase-adminsdk-*.json` from Downloads, mail and chat attachments. Consider deleting the chat conversation that contains the key. Run `.venv/bin/python scripts/check_secrets.py` before any `git init` or commit.
9. **Record it.** Write down the date, owner, consumers updated, the old key's deletion time and audit-log findings in the release/security log.

## Firebase web configuration

The `apiKey` in `js/rudo-auth.js` is a public client identifier, not a secret. Still, restrict it in Google Cloud Console (APIs & Services, then Credentials) with HTTP-referrer restrictions to the dashboard's domains.
