# Common Commands

## Installation & Setup

```bash
# Install with dev dependencies
python3 -m pip install -e ".[dev]"

# Upgrade dependencies
python3 -m pip install -e . --upgrade
```

## Testing

```bash
# Run all tests
pytest tests/ -v --cov=src

# Run with coverage report
pytest tests/ -v --cov=src --cov-report=html

# Run specific test file
pytest tests/test_url_utils.py -v

# Run single test
pytest tests/test_url_utils.py::TestCanonicalizeUrl::test_http_to_https -v
```

## Scraping

```bash
# Dry-run (no uploads)
python3 -m src.main \
  --site-config configs/perpaduan.yaml \
  --dry-run \
  --max-pages 10 \
  --log-level INFO

# Full crawl with uploads
python3 -m src.main \
  --site-config configs/perpaduan.yaml \
  --log-level INFO

# Crawl specific pages, custom output
python3 -m src.main \
  --site-config configs/perpaduan.yaml \
  --max-pages 50 \
  --output-dir /custom/output \
  --dry-run

# Debug logging
python3 -m src.main \
  --site-config configs/perpaduan.yaml \
  --log-level DEBUG \
  --max-pages 2
```

## Database Operations

```bash
# Check number of URLs processed
sqlite3 .cache/scraper_state.sqlite3 \
  "SELECT COUNT(*) as active_urls FROM urls WHERE status='active';"

# View recent crawl runs
sqlite3 .cache/scraper_state.sqlite3 \
  "SELECT crawl_run_id, discovered, fetched, failed FROM crawl_runs ORDER BY started_at DESC LIMIT 5;"

# Check content hashes stored
sqlite3 .cache/scraper_state.sqlite3 \
  "SELECT COUNT(*) as unique_hashes FROM content_hashes;"

# Export URLs to CSV
sqlite3 .cache/scraper_state.sqlite3 -csv \
  "SELECT canonical_url, status, last_checked_at FROM urls;" > urls_export.csv

# Reset database (full rescan)
rm .cache/scraper_state.sqlite3
```

## Output Inspection

```bash
# Count records
wc -l data/manifests/perpaduan/records.jsonl

# View first record
head -1 data/manifests/perpaduan/records.jsonl | jq .

# View last 5 records
tail -5 data/manifests/perpaduan/records.jsonl | jq .

# Count records per doc_type
jq -r '.doc_type' data/manifests/perpaduan/records.jsonl | sort | uniq -c

# View all crawl run summaries
jq . data/manifests/perpaduan/crawl_runs.jsonl

# Find records by date
jq 'select(.published_at == "2026-03-09")' data/manifests/perpaduan/records.jsonl
```

## Environment & Configuration

```bash
# Copy example env file
cp .env.example .env

# Set Spaces credentials
export DO_SPACES_BUCKET="gov-my-spaces"
export DO_SPACES_KEY="your-key"
export DO_SPACES_SECRET="your-secret"
export DO_SPACES_REGION="sgp1"

# Verify YAML config syntax
python3 -c "import yaml; yaml.safe_load(open('configs/perpaduan.yaml'))"
```

## Production (on Droplet)

```bash
# Manual trigger
sudo systemctl start polisi-perpaduan-scraper.service

# View recent logs
journalctl -u polisi-perpaduan-scraper -n 100 -f

# Check timer schedule
systemctl status polisi-perpaduan-scraper.timer
systemctl list-timers polisi-perpaduan-scraper.timer

# View next scheduled run
systemctl list-timers --all | grep perpaduan

# Stop service (graceful)
sudo systemctl stop polisi-perpaduan-scraper.service

# View all logs for a date
journalctl -u polisi-perpaduan-scraper --since "2026-03-09"

# Export logs
journalctl -u polisi-perpaduan-scraper -o json > scraper_logs.jsonl
```

## Backup & Maintenance

```bash
# Backup state database
cp .cache/scraper_state.sqlite3 backup/scraper_state.$(date +%Y%m%d_%H%M%S).sqlite3

# Backup output files
tar -czf backup/perpaduan_records_$(date +%Y%m%d).tar.gz data/manifests/perpaduan/

# Clean old output (keep last 3 months)
find data/manifests/perpaduan/ -name "records.jsonl.*.gz" -mtime +90 -delete

# Reset specific section (delete its URLs from state)
sqlite3 .cache/scraper_state.sqlite3 \
  "UPDATE urls SET status='inactive' WHERE canonical_url LIKE '%tender%';"
```

## Development

```bash
# Install in editable mode with dev dependencies
python3 -m pip install -e ".[dev]"

# Run linter (black)
black src/ tests/

# Run type checker (mypy) - optional
mypy src/ --ignore-missing-imports

# Generate test coverage report
pytest tests/ --cov=src --cov-report=html
# Open htmlcov/index.html
```

---

**Quick reference:** Always use `--dry-run` when testing selector changes!
