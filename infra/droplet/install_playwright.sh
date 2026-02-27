#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/polisigpt}"
VENV_DIR="${VENV_DIR:-$APP_ROOT/.venv}"

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "Virtualenv not found at $VENV_DIR. Run setup_runtime.sh first."
  exit 1
fi

"$VENV_DIR/bin/pip" install playwright
"$VENV_DIR/bin/python" -m playwright install --with-deps chromium

echo "Playwright dependencies installed."
