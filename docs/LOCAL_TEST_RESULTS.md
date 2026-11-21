# Local verification results

Executed 2026-11-20. **54 passed, 0 failed, 0 errors, 0 skipped; Python statement coverage 91.2%.** Python 3.12.14 and native PostgreSQL 17.12 were used. Machine-readable evidence: [LOCAL_TEST_RESULTS.json](LOCAL_TEST_RESULTS.json), [BROWSER_TEST_RESULTS.json](BROWSER_TEST_RESULTS.json). The migration file checksum is included in the results.

## Executed checks

```sh
.venv/bin/python -m pytest --cov=rudo --cov=app --cov-report=term-missing --cov-report=json:.local/coverage.json --junitxml=.local/test-results.xml -q
node scripts/test_browser.mjs
uv pip check --python .venv/bin/python
```

The complete pytest suite passed in 4.25 seconds once the isolated database was initialized. The development dependency download needed retries; the verified dependency artifact was checksum-validated before installation. The temporary test cluster was bound to 127.0.0.1:55439, used only synthetic records, required a synthetic-only marker before destructive resets, and was stopped after testing. No background database service was registered. PostgreSQL and its development dependencies remain installed locally; the prior OpenSSL 3 command-line links were restored after installation, while PostgreSQL retains its separately installed dependencies.

| Area | Actual evidence |
|---|---|
| Migration execution | Draft SQL applied to disposable local Postgres; checksum ledger repeat application produces no new migration; no public tables created/modified by the draft; all ten private tables have RLS |
| Authorization / RLS | Anonymous, nonstaff, inactive, wrong-project, revoked and out-of-scope API cases; direct database role queries, analyst raw-data denial, aggregate access and role self-escalation denial; revocation effective on next request |
| Firebase | Real SDK verifies ephemeral synthetic RSA-signed tokens using stubbed certificate fetch/user lookup; rejects wrong signature/project/issuer, expired tokens, disabled users and revoked sessions; network calls denied |
| Webhook | Raw-body HMAC, challenge, tampering/missing signature, oversized/malformed payload, account binding, multi-message batches, concurrent duplicates, changed-payload conflicts, transactional rollback and retryable failure response; status progression does not regress |
| Messages / delivery | Scoped queueing, idempotent operation IDs, conflicting reuse, input validation, origin/rate limits, stubbed Meta 2xx/4xx/429/5xx/malformed responses, timeout uncertainty, no automatic resend and stale-claim handling |
| Chats / orders | Scoped history, new international-number thread, persistent resolution, order version conflict including simultaneous writes; no optimistic success for failed writes |
| Analytics / referrals | Facility-scoped aggregate counts, protected QR endpoint and three source labels; UI retains its two-source chart with explicit disclosure pending owner metric decision |
| Migration data | Repeated encoding, stable source mappings, preserved repeated message bodies/roles/order/timestamps, missing-time preservation, absolute expiry, supported/unsupported types, dry-run accounting, changed-source rejection, repeat import and target reconciliation |
| Expiring state | Expired values hidden, nonexpiring values retained, concurrent acquire produces one winner and does not renew persistent keys |
| Privacy / configuration | No sensitive sentinel in captured errors/logs; privileged browser endpoint/token scan; remote DB default guard, indirect hostaddr guard and verified TLS requirement; Python sockets and non-test libpq targets denied |
| Clinical baseline | Unchanged source hash and synthetic regex characterization, including known ranking and negation limitations; no medical efficacy claim |
| Frontend | Headless Chrome through CDP pipes with all page requests intercepted: seven checks for chat load/queue, resolution, order save, dashboard, real vendored charts/referrals, absence of page errors/provider calls, forged-session denial before data requests |
| Syntax / dependencies | Python compilation; 16 shared/inline JavaScript syntax checks passed; `uv pip check` reports compatible installed packages; runtime/dev locks include hashes |

## Reproduction safety

Tests never discover a target from Supabase CLI link state. They permit libpq only to the synthetic rudo_test database on the designated loopback port and require a server marker before resetting schemas. All Python socket connections are denied. Browser requests are fulfilled from repository files or synthetic API/SDK fixtures; external requests are blocked. No real service token or patient fixture is required or loaded.

The test starter fixes a temporary-log placement issue found during setup; the final full run above is after that correction. Database initialization errors were not counted as passing SQL validation.

## Limits

- Remote table rows, schemas beyond catalog metadata, provider accounts and production deployments were not tested or changed.
- Firebase certificate/user lookup and Meta HTTP responses were stubbed. Actual ADC/project configuration, Google sign-in/recovery links and staging WhatsApp delivery still need authorized integration smoke tests.
- Python coverage is a measurement of exercised statements, not a security guarantee; no JavaScript coverage percentage or exhaustive visual accessibility test is claimed.
- There was no real export, live data-parity check, throughput benchmark, provider reconciliation, backup restoration, deployed rollback rehearsal, clinical validation or dependency vulnerability/advisory scan.
- Private-schema isolation has no automatic synchronization with existing public bot tables. That architecture and the remote migration remain review gates.
