# Rudo local observer

Option C is implemented locally: a read-only Flask/Firebase dashboard over a synthetic version of the inspected six-table bot database, with explicit staff/account/facility scope and a separate append-only audit connection. **Production integration remains on HOLD.** No remote migrations, real patient imports, provider sends or deployment were performed.

Start with the [implementation and file map](docs/observer-implementation/README.md), [actual test results](docs/observer-implementation/TEST_RESULTS.md), [local runbook](docs/observer-implementation/RUNBOOK.md) and [proposed rollout/rollback](docs/observer-implementation/ROLLOUT.md).

Run the isolated synthetic suite (requires the existing `.venv`, PostgreSQL 17, Node and Chrome):

```sh
scripts/test_local.sh
```

For an interactive local demo, start the disposable marked database if needed, then bootstrap and serve:

```sh
scripts/start_test_database.sh
.venv/bin/python scripts/bootstrap_observer.py
.venv/bin/python scripts/run_observer_demo.py
```

Open [the synthetic observer](http://127.0.0.1:5051/observer.html). Use the [runbook](docs/observer-implementation/RUNBOOK.md) for prerequisites, source-update demonstration and safe stop instructions. Tests and bootstrap reset synthetic schemas; stop the demo before running tests. Never point fixture tools at useful data.

`RUDO_MODE=observer` is the default. Normal observer mode uses Firebase ID-token verification; the explicit demo entrypoint alone substitutes offline synthetic identities. Server-only reader/audit credentials remain separate, source writes and legacy mutations/webhooks are rejected, and remote observer DSNs are blocked regardless of other flags. The app reads process environment and does not load Supabase CLI credentials or link settings. `.env.example` contains configuration names only.

The [remote schema comparison](docs/REMOTE_SCHEMA_COMPARISON.md) and [integration-readiness audit](docs/integration-readiness/README.md) are the architecture baseline. Earlier [private implementation](docs/LOCAL_IMPLEMENTATION.md) and [test results](docs/LOCAL_TEST_RESULTS.md) describe a historical stage. The private implementation remains explicitly selected for regression tests; its full migration is not the observer business database. Clinical triage remains unchanged, cake commerce excluded, and staff sending disabled. Two known private transport defects remain documented expected failures pending the authoritative sender contract.

## Staff authentication migration (Supabase Auth)

The staff-only Firebase → Supabase Auth foundation (issuer-routed verification, identity links that preserve roles and facility scopes, pending sign-ups, staff inventory, an idempotent import and admin approval) is described in [docs/auth-migration/README.md](docs/auth-migration/README.md). Firebase remains the default sign-in until staging verification. The exposed service-account key must be replaced first: see [docs/security/KEY_ROTATION.md](docs/security/KEY_ROTATION.md). Run `.venv/bin/python scripts/check_secrets.py` before `git init` or any commit.

## Production delivery (current)

Start with **[docs/HANDOVER.md](docs/HANDOVER.md)** (what works, how to sign in, test results, limitations) and **[docs/release/RELEASE_1.md](docs/release/RELEASE_1.md)** (the exact production change, blockers, steps, rollback and monitoring, awaiting approval). The staff/control schema is now the versioned migration `supabase/migrations/20261121120000_rudo_staff_control.sql`; the old private-mode draft lives in `staging/private/` and is used only by its regression tests.
