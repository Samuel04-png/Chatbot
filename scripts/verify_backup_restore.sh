#!/bin/bash
# Wrapper: see scripts/verify_backup_restore.py. Needs RUDO_BACKUP_PASSPHRASE (exported in this shell, or in
# backups/backup.env with mode 600; only that one variable is read, and it is never printed) and the local stack on :54422.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -z "${RUDO_BACKUP_PASSPHRASE:-}" && -f backups/backup.env ]]; then
  [[ "$(stat -f %Lp backups/backup.env)" == "600" ]] || { echo 'backups/backup.env must be mode 600' >&2; exit 2; }
  RUDO_BACKUP_PASSPHRASE=$(sed -n 's/^RUDO_BACKUP_PASSPHRASE=//p' backups/backup.env | head -1)
  export RUDO_BACKUP_PASSPHRASE
fi
exec .venv/bin/python -I scripts/verify_backup_restore.py "$@"
