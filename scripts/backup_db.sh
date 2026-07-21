#!/usr/bin/env bash
# Consistent daily backup of the SQLite DB (safe with WAL), rotated.
#
# Usage:  ./scripts/backup_db.sh
# Cron:   0 4 * * *  /root/code/personal/nudge/scripts/backup_db.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DB_PATH="${DATABASE_PATH:-${APP_DIR}/data/nudge.db}"
BACKUP_DIR="${BACKUP_DIR:-/root/backups/nudge}"   # outside the repo on purpose
KEEP="${KEEP:-14}"                                 # how many copies to retain

if [ ! -f "${DB_PATH}" ]; then
  echo "no db at ${DB_PATH}, nothing to back up" >&2
  exit 0
fi

mkdir -p "${BACKUP_DIR}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${BACKUP_DIR}/nudge-${STAMP}.db"

# .backup produces a consistent snapshot even with a live WAL.
sqlite3 "${DB_PATH}" ".backup '${DEST}'"
gzip -f "${DEST}"
echo "backup -> ${DEST}.gz"

# Rotate: keep the newest ${KEEP}.
ls -1t "${BACKUP_DIR}"/nudge-*.db.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
