#!/bin/bash
# Rudo SYNTHETIC DEMO for macOS: one command, no production access.
#   - Throwaway PostgreSQL 17 database on 127.0.0.1:55439 (deleted when you stop the demo).
#   - Made-up patients, conversations, orders, referrals and staff. No real data.
#   - No Supabase/Firebase login, no service keys, and no WhatsApp: "sending" a reply is a local stand-in.
#   - Runs with an EMPTY environment, so tokens or database URLs in your shell or .env are never used.
# Usage: scripts/demo_mac.sh        then open http://127.0.0.1:5051/observer.html     Stop: Ctrl+C
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n==> %s\n' "$1"; }
fail() { printf '\nERROR: %s\n' "$1" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || fail "This script is for macOS."
command -v brew >/dev/null || fail "Homebrew is not installed. See docs/TARI_LOCAL_TESTING.md step 1."

PGBIN="${RUDO_TEST_PGBIN:-$(brew --prefix postgresql@17 2>/dev/null)/bin}"
[[ -x "$PGBIN/initdb" ]] || fail "PostgreSQL 17 not found. Run: brew install postgresql@17"

PYTHON="${RUDO_PYTHON:-}"
if [[ -z "$PYTHON" ]]; then
  for candidate in "$(brew --prefix python@3.12 2>/dev/null)/bin/python3.12" python3.12; do
    if command -v "$candidate" >/dev/null 2>&1; then PYTHON="$candidate"; break; fi
  done
fi
[[ -n "$PYTHON" ]] || fail "Python 3.12 not found. Run: brew install python@3.12"

if [[ ! -x .venv/bin/python ]]; then
  say "Creating the Python environment (.venv) - first run only"
  "$PYTHON" -m venv .venv
fi
if [[ ! -f .venv/.rudo-deps-ok ]] || [[ requirements.txt -nt .venv/.rudo-deps-ok ]]; then
  say "Installing pinned dependencies (first run takes a minute)"
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet --require-hashes -r requirements.txt
  touch .venv/.rudo-deps-ok
fi

DB_DIR=""
cleanup() {
  if [[ -n "$DB_DIR" ]]; then
    say "Stopping and deleting the throwaway database"
    "$PGBIN/pg_ctl" -D "$DB_DIR" -m fast stop >/dev/null 2>&1 || true
    rm -rf -- "$DB_DIR" "$DB_DIR.init.log"
    DB_DIR=""
  fi
}
trap cleanup EXIT INT TERM

if "$PGBIN/pg_isready" -h 127.0.0.1 -p 55439 >/dev/null 2>&1; then
  say "Reusing the throwaway demo database already running on port 55439"
  env -i HOME="$HOME" PATH="$PATH" .venv/bin/python -c 'from rudo.synthetic import assert_disposable,LOCAL_DSN; assert_disposable(LOCAL_DSN)' \
    || fail "Something else is using port 55439. Stop it, then retry."
else
  say "Starting a throwaway database"
  DB_DIR=$(mktemp -d "${TMPDIR:-/tmp}/rudo-demo-db.XXXXXX")
  "$PGBIN/initdb" -D "$DB_DIR" -U rudo_test_owner -A trust --no-locale -E UTF8 >"$DB_DIR.init.log"
  "$PGBIN/pg_ctl" -D "$DB_DIR" -l "$DB_DIR/server.log" -w \
    -o "-h 127.0.0.1 -p 55439 -k $DB_DIR -c rudo.synthetic_test_cluster=synthetic-only" start >/dev/null
  "$PGBIN/createdb" -h 127.0.0.1 -p 55439 -U rudo_test_owner rudo_test
fi

say "Loading synthetic data"
env -i HOME="$HOME" PATH="$PATH" .venv/bin/python scripts/bootstrap_observer.py

say "Starting Rudo (synthetic demo)"
env -i HOME="$HOME" PATH="$PATH" .venv/bin/python scripts/run_observer_demo.py --open-reply-window
