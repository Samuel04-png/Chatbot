# Local acceptance results

As of 2026-11-21 (Africa/Lusaka), the final fresh `scripts/test_local.sh` run completed with **99 passed, 2 strict expected failures, zero unexpected failures and zero errors** in 18.17 seconds (pytest time). The runner created a new marked temporary PostgreSQL cluster, ran the suite and stopped/removed its own cluster. Reuse of an existing marked disposable cluster was also verified. No linked Supabase settings were used.

Runtime Python statement coverage is **92.66% (795/858)**; the two observer modules together have **96.48% (219/227)**. Coverage includes legacy runtime paths, excludes synthetic harness code, and is statement coverage, not branch or JavaScript coverage. Uncovered lines are retained in the raw report; no 100% claim is made.

All **54 original tests** were rerun and pass. The additional **45 passing tests** include source authorization/database integration, the actual observer browser integration and pinned candidate helper parity. The two new expected failures are not included in the passed count.

## Acceptance matrix

| Requirement | Actual local result |
|---|---|
| Exact source-shaped database | Six-table column names, types, nullability and identity metadata matched the earlier read-only remote snapshot. Local source/control RLS enabled. No private business schema required by observer. |
| Staff/source authorization | Approved active roles and exact mappings succeed. Unknown/disabled/revoked, cross-facility/account, unmapped and ambiguous scopes denied. Removing approval takes effect on later requests. |
| SQL restrictions | Restricted login cannot insert/update/delete/truncate/alter source data or create objects/assume owner roles, even after overriding transaction read-only. Sensitive state/context/address fields, raw mapping and analyst raw rows denied. |
| Audit separation | Reader cannot append logs; append-only audit credential cannot read source/logs or change/delete logs. Audit unavailability fails closed. |
| HTTP restrictions | Direct hidden/legacy mutation requests and webhook/send routes rejected independently of controls; source snapshots unchanged. Default observer cannot use remote flags or owner credentials. |
| Efficient summaries/history | Constant application query count when scope grows from 3 to 43 summaries; bounded keyset results, signed principal/filter-bound cursors, bigint IDs above 2^53 and negative IDs preserved. |
| Concurrent source updates | Independent synthetic writer updates become visible after refresh; anchored history and summary pagination avoid tested duplicates. No immutable snapshot/production-load guarantee is inferred. |
| Source/bot preservation | Six-source-table snapshot hashes unchanged by observer reads. Simulated fixed model context, answer and send count identical with observer on/off; writer continues during observer outage. |
| Pinned candidate comparison | Exact selected helper contracts at commit af2545c92aea2cbcda5c6d717f67598b386a373d produce identical stubbed sends, model context and source history with observer on/off. Deployed/full AI runtime remains unverified. |
| Honest UI | Unknown delivery/provider IDs and incomplete-history labels retained. Null prices/languages, history-only users, empty authorized data and explicit unavailable errors work. Analytics exposes only supported counts. |
| Browser integration | **17 observer checks**, actual Chrome page → Flask test client → restricted PostgreSQL via intercepted IPC. No mocked observer API. Source refresh, 65-message pagination, account-switch race, outage recovery, analyst scope and mobile layout pass. |
| Legacy UI | **7 distinct legacy browser smoke checks** pass with intercepted synthetic API responses. They are regression checks, separate from actual observer DB integration. |
| Isolation | Python network denied and libpq confined to exact local test DB. Page requests intercepted; provider endpoints never called. No real data/credentials, remote migration, production policy change or deployment. |
| Clinical/full migration preservation | SHA-256 of clinical triage and original private migration match architecture-baseline digests. |

The browser check is part of pytest's 99 passing tests; 17 is its internal assertion/check count and is **not added to 99**. The legacy seven checks likewise belong to one passing pytest test. The runner verification also emitted those seven checks separately before its redundant second browser invocation was removed; these remain seven distinct checks, not fourteen.

## Defects found and disposition

The cached initial Firebase user could survive identity changes. Shared auth now reads the current user; in-flight API calls are cancelled or discarded if UID changes. A browser test then caught filters persisting from one account to the next and making a valid new account look empty; identity changes now clear those filters and source data. Contrast and small-label issues found during final UI inspection were corrected. Signed negative bigint pagination was included after code review. Final desktop/mobile renders were inspected.

Two pre-existing inactive private transport behaviors are exposed by strict xfails: late failed status can overwrite delivered; stale completion lacks claim fencing and can overwrite reconciled unknown. These are documented **remaining defects**, requiring the authoritative sender contract. No production transport fix or activation is claimed. They do not execute in observer mode.

No unexpected original-test regression remains. Default startup intentionally changes to observer; private mode must now be selected explicitly. Actual Firebase/provider/production acceptance is still blocked by the dependencies in [ROLLOUT.md](ROLLOUT.md).

## Evidence

- [Machine-readable acceptance](evidence/acceptance.json), [fresh pytest output](evidence/observer-all-tests.txt), [JUnit](evidence/observer-all-tests.xml)
- [Raw coverage](evidence/observer-coverage.json), [17 browser checks](evidence/observer-browser-results.json)
- [Desktop render](evidence/observer-browser.png), [mobile render](evidence/observer-mobile.png)
- [File changes and hashes](evidence/changes.json), [candidate provenance](../../tests/fixtures/candidate_provenance.json)

Screenshots and all retained test evidence use synthetic records. Prior historical audit results were not substituted for this run.

A separately started interactive loopback demo also passed [HTTP smoke checks](evidence/local-http-smoke.json): three authorized summaries, one order, one referral and supported analytics loaded; anonymous requests returned 401, mutation returned 405, external Firebase SDK tags were absent and source snapshots were unchanged. Its database is separate from the runner-created cluster that was stopped/removed.
