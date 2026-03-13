#!/usr/bin/env bash
# =============================================================================
# deploy.sh — One-command deploy of Polisi GPT to a DigitalOcean Droplet
#
# Usage:
#   ./deploy.sh <DROPLET_IP> [SSH_USER]
#
# Examples:
#   ./deploy.sh 128.199.123.45          # Uses root (default for new droplets)
#   ./deploy.sh 128.199.123.45 jason    # Uses a custom SSH user
#
# What it does:
#   1. Clones (or pulls) the repo on the droplet
#   2. Runs setup_runtime.sh (system deps, venv, pip install)
#   3. Installs Playwright for browser-based scrapers
#   4. Copies systemd services and enables them
#   5. Installs the cron schedule
#   6. Prompts you to fill in .env if missing
#   7. Starts the API service
#
# Prerequisites:
#   - SSH access to the droplet (key-based auth recommended)
#   - Ubuntu 22.04+ on the droplet
# =============================================================================
set -euo pipefail

DROPLET_IP="${1:-}"
SSH_USER="${2:-root}"
GITHUB_REPO="https://github.com/jasonwee-aod/polisi2.git"

APP_ROOT="/opt/polisigpt"
REPO_DIR="$APP_ROOT/repo"
VENV_DIR="$APP_ROOT/.venv"

if [[ -z "$DROPLET_IP" ]]; then
  echo "Usage: ./deploy.sh <DROPLET_IP> [SSH_USER]"
  echo ""
  echo "  DROPLET_IP   IP address of your DigitalOcean Droplet"
  echo "  SSH_USER     SSH user (default: root)"
  exit 1
fi

SSH_TARGET="$SSH_USER@$DROPLET_IP"

echo "========================================"
echo " Polisi GPT — Deploying to $SSH_TARGET"
echo "========================================"

# --- Helper: run a command on the droplet ---
remote() {
  ssh -o StrictHostKeyChecking=accept-new "$SSH_TARGET" "$@"
}

# --- Step 1: Clone or pull the repo ---
echo ""
echo "[1/7] Syncing repository..."
remote bash -s <<'REMOTE_CLONE'
set -euo pipefail
APP_ROOT="/opt/polisigpt"
REPO_DIR="$APP_ROOT/repo"
sudo mkdir -p "$APP_ROOT"
if [[ -d "$REPO_DIR/.git" ]]; then
  echo "  Repo exists — pulling latest..."
  cd "$REPO_DIR" && git pull --ff-only
else
  echo "  Cloning fresh..."
  sudo git clone https://github.com/jasonwee-aod/polisi2.git "$REPO_DIR"
fi
sudo chown -R root:root "$APP_ROOT"
REMOTE_CLONE

# --- Step 2: Run setup_runtime.sh ---
echo ""
echo "[2/7] Installing system dependencies & Python venv..."
remote bash -s <<'REMOTE_SETUP'
set -euo pipefail
cd /opt/polisigpt/repo
bash infra/droplet/setup_runtime.sh
REMOTE_SETUP

# --- Step 3: Install Playwright ---
echo ""
echo "[3/7] Installing Playwright (Chromium)..."
remote bash -s <<'REMOTE_PW'
set -euo pipefail
cd /opt/polisigpt/repo
bash infra/droplet/install_playwright.sh
REMOTE_PW

# --- Step 4: Copy systemd services ---
echo ""
echo "[4/7] Installing systemd services..."
remote bash -s <<'REMOTE_SYSTEMD'
set -euo pipefail
REPO="/opt/polisigpt/repo"
sudo cp "$REPO/infra/droplet/systemd/polisi-api.service"                  /etc/systemd/system/
sudo cp "$REPO/infra/droplet/systemd/polisi-scraper.service"              /etc/systemd/system/
sudo cp "$REPO/infra/droplet/systemd/polisi-indexer-placeholder.service"  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable polisi-api.service polisi-scraper.service polisi-indexer-placeholder.service
echo "  Services installed and enabled."
REMOTE_SYSTEMD

# --- Step 5: Install cron ---
echo ""
echo "[5/7] Installing cron schedule..."
remote bash -s <<'REMOTE_CRON'
set -euo pipefail
sudo crontab -u polisi /opt/polisigpt/repo/infra/droplet/cron/scraper_every_3_days.cron
echo "  Cron installed for user 'polisi'."
REMOTE_CRON

# --- Step 6: Check .env ---
echo ""
echo "[6/7] Checking .env configuration..."
remote bash -s <<'REMOTE_ENV'
set -euo pipefail
ENV_FILE="/opt/polisigpt/.env"
if [[ -f "$ENV_FILE" ]]; then
  echo "  .env exists at $ENV_FILE"
else
  echo "  WARNING: No .env found at $ENV_FILE"
  echo "  Copying template — you MUST fill in the secrets before starting services."
  sudo cp /opt/polisigpt/repo/infra/droplet/env.example "$ENV_FILE"
  sudo chown polisi:polisi "$ENV_FILE"
  sudo chmod 600 "$ENV_FILE"
  echo "  Template copied. Edit with: ssh $USER@$(hostname -I | awk '{print $1}') sudo nano $ENV_FILE"
fi
REMOTE_ENV

# --- Step 7: Start API ---
echo ""
echo "[7/7] Starting API service..."
remote bash -s <<'REMOTE_START'
set -euo pipefail
if grep -q "replace-with" /opt/polisigpt/.env 2>/dev/null; then
  echo "  .env still has placeholder values — skipping auto-start."
  echo "  Fill in /opt/polisigpt/.env, then run:"
  echo "    sudo systemctl start polisi-api"
else
  sudo systemctl restart polisi-api
  sleep 2
  sudo systemctl status polisi-api --no-pager || true
  echo ""
  echo "  API running at http://$(hostname -I | awk '{print $1}'):8000/healthz"
fi
REMOTE_START

echo ""
echo "========================================"
echo " Deploy complete!"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Fill in secrets:  ssh $SSH_TARGET 'sudo nano /opt/polisigpt/.env'"
echo "  2. Start API:        ssh $SSH_TARGET 'sudo systemctl start polisi-api'"
echo "  3. Test health:      curl http://$DROPLET_IP:8000/healthz"
echo "  4. Manual scrape:    ssh $SSH_TARGET 'sudo systemctl start polisi-scraper'"
echo "  5. View logs:        ssh $SSH_TARGET 'tail -f /opt/polisigpt/logs/api.log'"
echo ""
echo "Cron runs every 3 days at 01:00 UTC (09:00 MYT) automatically."
