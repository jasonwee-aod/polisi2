#!/usr/bin/env bash
set -euo pipefail

APP_USER="${APP_USER:-polisi}"
APP_GROUP="${APP_GROUP:-polisi}"
APP_ROOT="${APP_ROOT:-/opt/polisigpt}"
REPO_DIR="${REPO_DIR:-$APP_ROOT/repo}"
VENV_DIR="${VENV_DIR:-$APP_ROOT/.venv}"

sudo apt-get update
sudo apt-get install -y \
  ca-certificates \
  curl \
  git \
  python3 \
  python3-venv \
  python3-pip \
  build-essential \
  libxml2-dev \
  libxslt1-dev \
  libjpeg-dev \
  zlib1g-dev \
  sqlite3

if ! id -u "$APP_USER" >/dev/null 2>&1; then
  sudo useradd --system --create-home --shell /bin/bash "$APP_USER"
fi

sudo mkdir -p "$APP_ROOT" "$APP_ROOT/logs" "$APP_ROOT/run"
sudo chown -R "$APP_USER":"$APP_GROUP" "$APP_ROOT"

if [[ ! -d "$REPO_DIR" ]]; then
  echo "Repository not found at $REPO_DIR"
  echo "Clone the project into $REPO_DIR before continuing."
  exit 1
fi

python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -e "$REPO_DIR/scraper"

cat <<RUNTIME_OK
Runtime provisioned:
- app root: $APP_ROOT
- repo dir: $REPO_DIR
- venv: $VENV_DIR
RUNTIME_OK
