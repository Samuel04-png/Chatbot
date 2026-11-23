#!/bin/bash
# Wrapper: see scripts/verify_backup_restore.py. Needs RUDO_BACKUP_PASSPHRASE and the local stack on :54422.
set -euo pipefail
cd "$(dirname "$0")/.."
exec .venv/bin/python -I scripts/verify_backup_restore.py "$@"
