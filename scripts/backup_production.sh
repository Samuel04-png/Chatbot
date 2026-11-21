#!/bin/bash
# Encrypted logical backup of the Rudo Supabase database (roles, schema, data) BEFORE any production change.
# The project currently has NO physical backups and NO point-in-time recovery, so this is mandatory.
#
# Uses the local PostgreSQL 17 client tools through the Supabase session pooler (no Docker, no CLI prompts).
# Requires (environment only, never command-line arguments):
#   SUPABASE_DB_PASSWORD     database password (Dashboard -> Project Settings -> Database)
#   RUDO_BACKUP_PASSPHRASE   long random passphrase kept in the team password manager (20+ chars)
# Optional: RUDO_BACKUP_HOST/PORT/USER/DB/SSLMODE (defaults: the linked project's pooler, postgres.<ref>, require;
#           verify-full automatically when deploy/certs/prod-supabase.crt exists).
# Output: backups/rudo-<UTC timestamp>.tar.enc (+ .sha256). Plaintext exists only in a 0700 temp dir that is
# deleted on exit. The archive contains patient data: keep it encrypted, never in Git, never in chat.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${SUPABASE_DB_PASSWORD:?set SUPABASE_DB_PASSWORD (read -rs SUPABASE_DB_PASSWORD && export SUPABASE_DB_PASSWORD)}"
: "${RUDO_BACKUP_PASSPHRASE:?set RUDO_BACKUP_PASSPHRASE}"
[ "${#RUDO_BACKUP_PASSPHRASE}" -ge 20 ] || { echo 'RUDO_BACKUP_PASSPHRASE must be at least 20 characters'; exit 1; }
PGBIN=${RUDO_TEST_PGBIN:-/opt/homebrew/opt/postgresql@17/bin}
REF=$(cat supabase/.temp/project-ref)
DEFAULT_HOST=$(sed -E 's#^[^@]*@([^:/]+).*#\1#' supabase/.temp/pooler-url)
export PGHOST=${RUDO_BACKUP_HOST:-$DEFAULT_HOST} PGPORT=${RUDO_BACKUP_PORT:-5432} PGDATABASE=${RUDO_BACKUP_DB:-postgres}
export PGUSER=${RUDO_BACKUP_USER:-postgres.$REF} PGPASSWORD=$SUPABASE_DB_PASSWORD PGCONNECT_TIMEOUT=15
CERT=deploy/certs/prod-supabase.crt
if [ -n "${RUDO_BACKUP_SSLMODE:-}" ]; then export PGSSLMODE=$RUDO_BACKUP_SSLMODE
elif [ -f "$CERT" ]; then export PGSSLMODE=verify-full PGSSLROOTCERT=$PWD/$CERT
else export PGSSLMODE=require; fi
if [ -z "${RUDO_BACKUP_HOST:-}" ] && [ "$REF" != "${RUDO_EXPECTED_REF:-cktfbpnxpfbyroqzuibc}" ]; then
  echo 'Linked project is not the expected Rudo project'; exit 1
fi
echo "Target: $PGUSER @ $PGHOST:$PGPORT/$PGDATABASE (sslmode=$PGSSLMODE)"
# Fail fast (15 s) instead of hanging; prints the server version only.
"$PGBIN/psql" -XAtc "SELECT 'connected: PostgreSQL '||current_setting('server_version')" || { echo 'Connection failed (password, host or network)'; exit 1; }
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
WORK=$(mktemp -d); chmod 700 "$WORK"
trap 'rm -rf -- "$WORK"' EXIT
# Same exclusions the Supabase CLI uses: platform-managed schemas are recreated by Supabase itself.
SCHEMA_EXCLUDE='information_schema|pg_*|_analytics|_realtime|_supavisor|auth|etl|extensions|pgbouncer|realtime|storage|supabase_functions|supabase_migrations|cron|dbdev|graphql|graphql_public|net|pgmq|pgsodium|pgsodium_masks|pgtle|repack|tiger|tiger_data|timescaledb_*|_timescaledb_*|topology|vault'
DATA_EXCLUDE='information_schema|pg_*|graphql|graphql_public|pgsodium|pgsodium_masks|pgtle|repack|tiger|tiger_data|timescaledb_*|_timescaledb_*|topology|vault|etl|extensions|pgbouncer|realtime|supabase_migrations|_analytics|_realtime|_supavisor'
echo '1/3 roles';  "$PGBIN/pg_dumpall" --roles-only --no-role-passwords -f "$WORK/roles.sql"
echo '2/3 schema'; "$PGBIN/pg_dump" --schema-only --quote-all-identifiers --exclude-schema "$SCHEMA_EXCLUDE" -f "$WORK/schema.sql"
echo '3/3 data';   "$PGBIN/pg_dump" --data-only --quote-all-identifiers --exclude-schema "$DATA_EXCLUDE" \
  --exclude-table 'auth.schema_migrations' --exclude-table 'storage.migrations' --exclude-table 'supabase_functions.migrations' \
  -f "$WORK/data.sql"
for f in roles schema data; do [ -s "$WORK/$f.sql" ] || { echo "empty $f dump"; exit 1; }; done
grep -q 'CREATE TABLE "public"."messages"' "$WORK/schema.sql" || { echo 'schema dump lacks public.messages'; exit 1; }
COPYFILE_DISABLE=1 tar -C "$WORK" -cf "$WORK/rudo-$STAMP.tar" roles.sql schema.sql data.sql
mkdir -p backups && chmod 700 backups
openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -pass env:RUDO_BACKUP_PASSPHRASE -in "$WORK/rudo-$STAMP.tar" -out "backups/rudo-$STAMP.tar.enc"
chmod 600 "backups/rudo-$STAMP.tar.enc"
shasum -a 256 "backups/rudo-$STAMP.tar.enc" > "backups/rudo-$STAMP.tar.enc.sha256"
echo "Encrypted backup: backups/rudo-$STAMP.tar.enc ($(du -h "backups/rudo-$STAMP.tar.enc" | cut -f1))"
echo "Next: scripts/verify_backup_restore.sh backups/rudo-$STAMP.tar.enc"
