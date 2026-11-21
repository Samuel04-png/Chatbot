#!/bin/sh
# Start only a NEW, temporary PostgreSQL cluster; never target an existing directory.
set -eu
PGBIN=${RUDO_TEST_PGBIN:-/opt/homebrew/opt/postgresql@17/bin}
TASK_DB_DIR=$(mktemp -d "${TMPDIR:-/tmp}/rudo-pg-test.XXXXXX")
"$PGBIN/initdb" -D "$TASK_DB_DIR" -U rudo_test_owner -A trust --no-locale -E UTF8 > "$TASK_DB_DIR.init.log"
"$PGBIN/pg_ctl" -D "$TASK_DB_DIR" -l "$TASK_DB_DIR/server.log" -o "-h 127.0.0.1 -p 55439 -k $TASK_DB_DIR -c rudo.synthetic_test_cluster=synthetic-only" start
"$PGBIN/createdb" -h 127.0.0.1 -p 55439 -U rudo_test_owner rudo_test
printf 'Temporary test cluster: %s\n' "$TASK_DB_DIR"
printf 'Stop this exact cluster with: %s/pg_ctl -D %s stop\n' "$PGBIN" "$TASK_DB_DIR"
