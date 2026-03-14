#!/usr/bin/env bash
# =============================================================================
# run_full_pipeline.sh — Scrape all sites, then index (chunk + embed)
#
# Runs on the Droplet as: sudo -u polisi bash run_full_pipeline.sh
# Logs to /opt/polisigpt/logs/pipeline.log
# =============================================================================
set -euo pipefail

REPO="/opt/polisigpt/repo"
VENV="/opt/polisigpt/.venv"
LOG="/opt/polisigpt/logs/pipeline.log"

cd "$REPO"

echo "========================================" >> "$LOG"
echo "Pipeline started at $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
echo "========================================" >> "$LOG"

# --- Step 1: Scrape all sites ---
echo "[1/2] Starting scraper..." >> "$LOG"
"$VENV/bin/polisi-scraper" \
  --all \
  --max-pages 200 \
  --workers 3 \
  --site-config scraper/configs \
  --manifest-dir scraper/data/manifests \
  >> "$LOG" 2>&1 || echo "Scraper exited with errors (continuing to indexer)" >> "$LOG"

echo "" >> "$LOG"

# --- Step 2: Index (chunk + embed + push to Supabase) ---
echo "[2/2] Starting indexer..." >> "$LOG"
"$VENV/bin/polisi-indexer" \
  --mode incremental \
  >> "$LOG" 2>&1 || echo "Indexer exited with errors" >> "$LOG"

echo "" >> "$LOG"
echo "Pipeline finished at $(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
echo "========================================" >> "$LOG"
