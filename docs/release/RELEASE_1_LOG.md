# Release 1 execution log (2026-11-21, Africa/Lusaka)

Approved by the owner in chat: apply Release 1 **without a backup** (backup script had not completed; Supabase
has no physical backups/PITR), map unassigned conversations to a holding facility, run the dashboard on the
owner's Mac. Target: `cktfbpnxpfbyroqzuibc`.

| Step | Result | Evidence |
|---|---|---|
| Migration/rollback hashes match the rehearsed files (`350b0236…`, `9c085b63…`) | yes | `shasum` |
| Read-only pre-check matches baseline (no observer_control, no rudo roles, 0 policies, RLS on, ACL fingerprint `e67855d4…`) | PASS | [release1-precheck.json](evidence/release1-precheck.json) |
| Apply migration in one transaction (`BEGIN; …; COMMIT;` via `supabase db query --linked`) | committed: schema + 9 tables, 3 roles, 4 policies | CLI exit 1 was its telemetry (PostHog) shutdown, verified by read-only query |
| Passwords for 3 logins: SCRAM verifiers only sent; plaintext only in `backups/release1-dashboard.env` (0600, gitignored) | each login connects as itself; reader read-only by default; client TLS `verify-full` with Supabase Root 2021 CA | direct connection test |
| Post-check | all pass: roles not super/bypassrls/createrole; only the 4 `rudo_observer_read` policies; RLS on; bot ACLs unchanged; API roles no access; kv/user_state/message_en/address hidden; bot rows unchanged | [release1-postcheck.json](evidence/release1-postcheck.json) |
| Facilities (6) and approved mappings (919 phones: 531 by referral rules, 388 to "Dawa central (unassigned)") | written in one transaction to observer_control only | [release1-postcheck-after-mapping.json](evidence/release1-postcheck-after-mapping.json) |
| Dashboard on the owner's Mac (`scripts/run_dashboard_local.py`, http://localhost:8080, Firebase login) | `/readyz` ready through all restricted logins | `.local/dashboard-prod.log` (route templates only) |

Fixes made during the release (tested, 164 tests passing):
- Firebase Admin SDK demanded service-account credentials even without revocation checks, so every sign-in
  would have failed. With `RUDO_FIREBASE_CHECK_REVOKED=false` tokens are now verified with Google's public
  keys (Firebase's documented third-party method).
- Connection pooling (`psycopg-pool`) and fewer round trips: each new TLS connection from this network takes
  ~20 s and each round trip ~0.25 s.

Outstanding: encrypted backup + restore verification; first admin bootstrap (after the admin's first sign-in);
end-to-end check by a real staff sign-in; bot liveness (last message 2026-11-20 09:16 UTC).
