#!/usr/bin/env bash
# Deploy nudge to the VPS: rsync the working copy, sync deps, restart the service.
#
# Usage:  VPS_HOST=root@1.2.3.4 ./scripts/deploy.sh
# Assumes: SSH key access, uv installed on the server, .env already present there.
set -euo pipefail

VPS_HOST="${VPS_HOST:?set VPS_HOST, e.g. root@1.2.3.4}"
REMOTE_DIR="${REMOTE_DIR:-/root/code/personal/nudge}"

SRC_DIR="$(cd "$(dirname "$0")/.." && pwd)/"

echo "==> rsync -> ${VPS_HOST}:${REMOTE_DIR}"
rsync -az --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.env' \
  --exclude 'data/' \
  --exclude 'backups/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  "${SRC_DIR}" "${VPS_HOST}:${REMOTE_DIR}/"

echo "==> uv sync + restart on remote"
ssh "${VPS_HOST}" bash -s <<REMOTE
set -euo pipefail
cd "${REMOTE_DIR}"
/root/.local/bin/uv sync --frozen
# Install/refresh the unit if it changed, then restart.
install -m 644 scripts/nudge.service /etc/systemd/system/nudge.service
systemctl daemon-reload
systemctl enable --now nudge
systemctl restart nudge
systemctl --no-pager --lines=5 status nudge || true
REMOTE

echo "==> done"
