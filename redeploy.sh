#!/usr/bin/env bash
# =============================================================================
# redeploy.sh — Quick update: pull latest code and restart services
#
# Usage:
#   ./redeploy.sh <DROPLET_IP> [SSH_USER]
# =============================================================================
set -euo pipefail

DROPLET_IP="${1:-}"
SSH_USER="${2:-root}"

if [[ -z "$DROPLET_IP" ]]; then
  echo "Usage: ./redeploy.sh <DROPLET_IP> [SSH_USER]"
  exit 1
fi

SSH_TARGET="$SSH_USER@$DROPLET_IP"

echo "Redeploying to $SSH_TARGET..."

ssh -o StrictHostKeyChecking=accept-new "$SSH_TARGET" bash -s <<'REMOTE'
set -euo pipefail
APP_ROOT="/opt/polisigpt"
REPO="$APP_ROOT/repo"
VENV="$APP_ROOT/.venv"

echo "[1/4] Pulling latest code..."
cd "$REPO" && git pull --ff-only

echo "[2/4] Updating Python packages..."
"$VENV/bin/pip" install -q -e "$REPO/scraper" -e "$REPO/api"

echo "[3/4] Updating systemd services..."
sudo cp "$REPO/infra/droplet/systemd/"*.service /etc/systemd/system/
sudo systemctl daemon-reload

echo "[4/4] Restarting API..."
sudo systemctl restart polisi-api
sleep 2
sudo systemctl status polisi-api --no-pager || true

echo ""
echo "Done. API at http://$(hostname -I | awk '{print $1}'):8000/healthz"
REMOTE
