# Option C local observer implementation

Status as of 2026-11-21 (Africa/Lusaka): **implemented and tested locally; production remains on HOLD**. The user authorized local implementation following the [architecture audit](../integration-readiness/README.md). This deliverable uses disposable synthetic PostgreSQL only. No remote SQL, migrations, patient imports, policy changes, webhook changes, provider sends or deployment were performed in this implementation stage.

The earlier [remote schema comparison](../REMOTE_SCHEMA_COMPARISON.md) remains the inspected baseline: six RLS-enabled public tables, no policies, and no remote private `rudo` business schema. The observer uses minimal projections from that source shape. It does not require the full private migration or create a second business database.

- [Run, test and stop locally](RUNBOOK.md)
- [Actual test evidence and acceptance results](TEST_RESULTS.md)
- [Production dependencies and proposed rollout/rollback](ROLLOUT.md)
- [Changed file manifest](evidence/changes.json)

## Implemented boundary

`app.create_app` defaults to `observer`. Its observer blueprint returns before private mutation routes are registered. The legacy implementation remains available explicitly as `MODE=private` for regression tests. Observer aliases for conversations, orders, referrals and analytics all render the same read-only workspace. Other legacy business/profile/settings/registration/cake pages are not served. Sending, resolving, editing and webhook ingestion are rejected independently at the HTTP boundary; hiding buttons is supplementary.

Firebase ID-token verification and revocation checking remain server-side in `rudo/auth.py`. Automated integration substitutes a synthetic verifier, and isolated SDK unit tests stub verification. Actual Firebase login, ADC and revocation against the configured project remain external acceptance dependencies. The offline demo does not contact Firebase and is visibly labelled synthetic; the fake identity asset is unavailable in normal observer mode.

Every request gets a transaction-local issuer, subject and source context after verification. Protected `observer_control.staff` and `staff_scopes` select an active staff member and permitted account/facility pairs. Only **exactly one approved mapping for the source + phone across all scopes** permits raw records. Unmapped, conflicting, inactive and unknown identities are denied; no facility is inferred from a phone, source label or state object.

The source mapping is an owner-approved authorization decision, not a discovered business relationship. The six-table source does not independently prove account/facility ownership. `users.state`, `users.step`, `user_state`, `kv`, translated model context and order addresses are excluded from observer permissions. Their ownership and relationships are left intact and unresolved.

The server-only `rudo_observer` login has no superuser, BYPASSRLS, DDL, source DML, role membership or raw mapping access. Column grants plus SELECT-only RLS constrain raw projections. Analysts have only a fixed aggregate function and receive no raw source rows. The separate `rudo_observer_audit` login can append access metadata but cannot read source rows or read/change/delete audit entries. Audit failure prevents results from being returned while the independent synthetic writer continues.

Database authorization context trusts the verified Flask process. It is not an independently verified JWT inside PostgreSQL: possession of a server database credential would permit setting context for another staff identity. These credentials must never reach a browser. Local SECURITY DEFINER helpers use a fixed search path and no caller-controlled SQL; production function ownership, inherited grants and policies require a fresh review.

## Query and UI behavior

Conversation listing uses one bounded summary query with a lateral latest-message projection; it does not fetch histories or issue a Python query per conversation. The local source fixture has a `(phone,id)` history index. This proves a constant application query count, not production latency: production query plans and any additive index proposal still need review.

Summaries paginate by phone, not latest activity, to keep pages stable while new messages arrive. History is fetched only on selection, with bounded signed keyset cursors and an initial maximum-ID anchor. Message, order and referral bigint IDs are serialized as strings, including values above JavaScript's exact integer range and signed source IDs. Original text, roles, timestamps, phone identifiers and nulls are retained. Concurrent inserts appear on explicit refresh; refresh replaces the current history. Late backfilled rows can alter subsequent reads: this is not an immutable database snapshot.

Orders preserve source product, text price, quantity, status and timestamp. Referrals preserve source ID, phone, attribution and timestamp. Missing values read “Unknown / not recorded.” Analytics exposes only scoped counts of source users, conversations, captured messages, orders and referrals. Conversion, delivery, response-time and clinical-resolution metrics remain unavailable. History is explicitly incomplete; bot-role text is never evidence of confirmed delivery, and provider IDs are not invented.

The frontend uses text nodes for source content, clears results on read errors or identity changes, cancels pending requests and discards responses belonging to earlier identities. Search/filter state is cleared when switching staff accounts. Bounded loading, empty, unavailable, unauthorized and refresh states are distinct. Desktop and mobile renders were inspected.

## Files and compatibility

| Files | Purpose |
|---|---|
| `rudo/observer.py`, `rudo/observer_api.py` | Restricted source adapter, signed cursors, audit, observer-only API/pages |
| `staging/observer/source_fixture.sql`, `control.sql` | Exact synthetic public column shape; local control metadata, grants, RLS and functions |
| `rudo/synthetic.py`, `scripts/bootstrap_observer.py`, `run_observer_demo.py` | Guarded disposable fixtures, independent simulated bot writer, offline demo |
| `observer.html`, `css/observer.css`, `js/observer.js`, `observer-demo-auth.js` | Functional source-shaped observer workspace and gated synthetic identity provider |
| `app.py`, `js/rudo-auth.js`, `js/rudo-api.js`, `.env.example` | Explicit modes, shared identity isolation, environment variable names |
| `scripts/test_local.sh`, `test_observer_browser.mjs`, `tests/test_observer*.py` | Automated local cluster runner, restricted DB integration, browser-to-Flask IPC |
| `tests/test_candidate_observer.py`, `tests/fixtures/candidate_*`, `CANDIDATE_LICENSE.txt` | Pinned candidate helper comparison only, with attribution/license |
| `tests/test_deferred_transport.py`, `tests/conftest.py`, `.coveragerc` | Explicit known legacy failures, preserved private tests, runtime-only coverage |

The pinned public candidate is `Samuel04-png/rudo_medgemma` commit `af2545c92aea2cbcda5c6d717f67598b386a373d`. Test-only excerpts exercise history/context/send helper contracts with a fixed model result, stubbed sender and synthetic DB. This is **candidate helper validation**, not full bot or deployed inference validation. The excerpts retain AGPL attribution/license; runtime observer code does not import them.

Clinical triage and the original ten-table migration are unchanged by digest. The full migration runs only in disposable legacy regression fixtures, never as the observer business store. No new package dependencies were required.
