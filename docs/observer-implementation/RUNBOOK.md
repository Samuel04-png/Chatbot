# Local synthetic runbook

Run commands from the project root. Python 3.12 with the pinned development dependencies, libpq, PostgreSQL 17, Node and Google Chrome are required. The existing `.venv` is usable here. For a fresh environment:

```sh
uv venv --python 3.12 .venv
uv pip sync --python .venv/bin/python requirements-dev.txt
```

## Automated acceptance

```sh
scripts/test_local.sh
```

The runner creates a temporary PostgreSQL cluster bound to `127.0.0.1:55439`, database `rudo_test`, synthetic owner `rudo_test_owner`, with the `rudo.synthetic_test_cluster=synthetic-only` server marker. It stops/removes only a cluster it created. If that port is already accepting connections, it reuses it only after checking the exact synthetic database/owner and marker; an unrelated service is refused. Override `RUDO_TEST_PGBIN` only for the PostgreSQL binaries directory. Set `RUDO_TEST_CHROME` only for a different Chrome executable.

**Tests reset all six synthetic public tables and the local control/private migration schemas. Do not run while using the demo.** The fixed marked cluster must contain synthetic fixtures only. Local trust authentication is for this disposable cluster; it is not a production authentication design.

The runner executes pytest with runtime statement coverage, including the seven legacy browser checks. Pytest also includes the real observer browser-to-Flask-to-restricted-PostgreSQL test, whose page requests are intercepted and carried over IPC. Python sockets are denied; libpq is restricted to the exact local test destination. All provider integrations are stubbed. It never reads the Supabase CLI target or credentials.

Outputs under ignored `.local/`: `observer-all-tests.txt`, `observer-all-tests.xml`, `observer-coverage.json`, `observer-browser-results.json`, desktop/mobile PNGs. Two strict expected failures document inactive legacy transport gaps. They must not be reported as passed tests. Current checked-in acceptance evidence is in [TEST_RESULTS.md](TEST_RESULTS.md).

## Interactive synthetic demo

If no marked test cluster is running, start a new one:

```sh
scripts/start_test_database.sh
```

Keep its exact temporary directory and printed stop command. Bootstrap and run:

```sh
.venv/bin/python scripts/bootstrap_observer.py
.venv/bin/python scripts/run_observer_demo.py
```

Open [the local observer](http://127.0.0.1:5051/observer.html). The loopback-only demo uses synthetic staff and source records, no real login/provider/production credentials. Its identity shim defaults to the mapped `operator` fixture. All views are read-only. In the browser console, `syntheticSwitchIdentity('other')`, `syntheticSwitchIdentity('analyst')` and `syntheticSwitchIdentity('empty')` demonstrate scope, aggregate-only and empty states. This helper is absent from normal observer pages.

To simulate a new source message locally in a separate terminal:

```sh
.venv/bin/python -c 'from rudo.synthetic import SyntheticBot,PHONES; SyntheticBot().receive(PHONES["a"],"local review update")'
```

Select that source conversation and choose **Refresh history**. This writes synthetic source rows as the simulated owner; the dashboard credential remains read-only. `Refresh source` updates summaries.

Stop the foreground demo with Ctrl-C. Stop **only** the exact cluster started for this task using the helper's printed command. Do not stop a system PostgreSQL service. Re-bootstrap only when the demo is stopped; fixtures are intentionally disposable.

## Configured local observer

Normal startup is `.venv/bin/python app.py` with `RUDO_MODE=observer` (also the default). It reads process environment only; it does not load `.env` or linked CLI settings. Configure server-only loopback reader/audit DSNs and `RUDO_OBSERVER_SOURCE_ID` through secure local environment, plus Firebase project/ADC and exact origin. `.env.example` contains variable names, not usable secrets. Without configuration reads fail closed.

Normal pages use the existing browser Firebase project configuration; server project ID, providers, ADC and staff membership must agree. Successful local synthetic tests do not certify that external configuration. Never substitute a service-role key or owner DSN. Both effective connection users are checked.

The observer adapter **always rejects remote DSNs**, even if `RUDO_ENABLE_REMOTE_WRITES=true`. It has no production-enable switch in this deliverable. Remote read connectivity requires a separately reviewed code/config change and explicit authorization. Never run the staging SQL or fixture bootstrap against the linked project.

## Review session prepared by this task

A synthetic demo was started and smoke-tested on loopback port 5051. Its process ID, exact temporary database directory and stop commands are recorded in the ignored [local session file](../../.local/observer-demo-session.json). Use that file's `stop_demo` and `stop_database` commands to stop only these task-owned processes. This session is temporary; use the reproducible instructions above if it has stopped.
