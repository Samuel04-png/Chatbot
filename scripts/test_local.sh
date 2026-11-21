#!/bin/bash
# All schemas reset by this suite belong to a marked, disposable loopback cluster.
set -euo pipefail
cd "$(dirname "$0")/.."
PGBIN=${RUDO_TEST_PGBIN:-/opt/homebrew/opt/postgresql@17/bin}
TASK_DB_DIR=''
cleanup() {
  if [[ -n "$TASK_DB_DIR" ]]; then
    "$PGBIN/pg_ctl" -D "$TASK_DB_DIR" -m fast stop
    rm -rf -- "$TASK_DB_DIR"
  fi
}
trap cleanup EXIT
mkdir -p .local
if "$PGBIN/pg_isready" -h 127.0.0.1 -p 55439 -U rudo_test_owner -d rudo_test >/dev/null 2>&1; then
  # Refuse unrelated services, even if they use the same port/database name.
  .venv/bin/python -c 'from rudo.synthetic import assert_disposable,LOCAL_DSN; assert_disposable(LOCAL_DSN)'
else
  TASK_DB_DIR=$(mktemp -d "${TMPDIR:-/tmp}/rudo-suite.XXXXXX")
  "$PGBIN/initdb" -D "$TASK_DB_DIR" -U rudo_test_owner -A trust --no-locale -E UTF8 > .local/observer-initdb.txt
  "$PGBIN/pg_ctl" -D "$TASK_DB_DIR" -l "$TASK_DB_DIR/server.log" -o "-h 127.0.0.1 -p 55439 -k $TASK_DB_DIR -c rudo.synthetic_test_cluster=synthetic-only" start
  "$PGBIN/createdb" -h 127.0.0.1 -p 55439 -U rudo_test_owner rudo_test
fi
.venv/bin/python -m pytest --cov=rudo --cov=app --cov-report=term-missing \
  --cov-report=json:.local/observer-coverage.json --junitxml=.local/observer-all-tests.xml \
  -q --tb=short "$@" | tee .local/observer-all-tests.txt
