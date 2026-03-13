# MOHE Scraper Operator Runbook

**Ministry of Higher Education Malaysia (MOHE) Document Scraper**

Version: 1.0.0
Last Updated: 2026-02-27

---

## Quick Start

### Prerequisites

- Python 3.11 or higher
- pip / poetry (for dependency management)
- Optional: Google Cloud credentials if using GCS storage

### Installation

1. **Clone or extract the scraper project:**
   ```bash
   cd mohe-scraper
   ```

2. **Create a Python virtual environment:**
   ```bash
   python3.11 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -e .
   # Or: pip install -e ".[dev]" if you want development tools (testing, linting)
   ```

4. **Configure environment (optional):**
   ```bash
   cp .env.example .env
   # Edit .env to set GCS_BUCKET, LOG_LEVEL, etc. if needed
   source .env
   ```

---

## Running the Scraper

### Basic Usage

```bash
mohe-scraper
```

This runs a full crawl of MOHE RSS feeds and saves results to `./data/manifests/mohe/`.

### Available Command-Line Options

```bash
mohe-scraper --help
```

**Key Options:**

- `--site-config PATH`: Path to site configuration YAML (default: `configs/mohe_site_config.yaml`)
- `--state-db PATH`: Path to SQLite state database (default: `./data/mohe_state.db`)
- `--output-dir PATH`: Output directory for records (default: `./data/manifests/mohe`)
- `--dry-run`: Run without writing files to storage
- `--log-level LEVEL`: Set logging verbosity (DEBUG, INFO, WARNING, ERROR; default: INFO)

### Example: Dry Run (Preview)

```bash
mohe-scraper --dry-run --log-level DEBUG
```

This shows what would be scraped without downloading anything.

### Example: Custom Output Directory

```bash
mohe-scraper --output-dir ./my-output --state-db ./my-output/state.db
```

---

## Output Files

After a successful run, check:

```
data/manifests/mohe/
├── records.jsonl         # All discovered documents (one JSON object per line)
└── crawl_runs.jsonl      # Execution log and metadata
```

### records.jsonl Format

Each line is a JSON object:

```json
{
  "record_id": "abc123def456",
  "source_url": "https://www.mohe.gov.my/en/broadcast/announcements/...",
  "canonical_url": "https://mohe.gov.my/en/broadcast/announcements/...",
  "title": "Government Announcement",
  "published_at": "2026-02-27",
  "agency": "Ministry of Higher Education (MOHE)",
  "doc_type": "announcement",
  "content_type": "text/html",
  "language": "en",
  "sha256": "abc123...",
  "fetched_at": "2026-02-27T10:00:00Z",
  "http_etag": "\"abc123\"",
  "http_last_modified": "Thu, 27 Feb 2026 10:00:00 GMT",
  "gcs_uri": "gs://my-bucket/gov-docs/mohe/raw/2026/02/27/abc123_file.html",
  "gcs_bucket": "my-bucket",
  "gcs_object": "gov-docs/mohe/raw/2026/02/27/abc123_file.html",
  "crawl_run_id": "2026-02-27-mohe",
  "parser_version": "v1"
}
```

### crawl_runs.jsonl Format

```json
{
  "crawl_run_id": "2026-02-27-mohe",
  "site_slug": "mohe",
  "started_at": "2026-02-27T10:00:00Z",
  "completed_at": "2026-02-27T10:15:00Z",
  "status": "completed",
  "total_urls_discovered": 150,
  "total_items_fetched": 145,
  "total_items_uploaded": 50,
  "total_items_deduped": 95,
  "total_items_failed": 0,
  "dry_run": false
}
```

---

## Storage Configuration

### Option 1: Local Filesystem (Default)

Files are stored in `./data/documents/` by default.

```bash
mohe-scraper
```

No setup required.

### Option 2: Google Cloud Storage (GCS)

1. **Create a GCS bucket:**
   ```bash
   gsutil mb gs://my-gov-rag-bin
   ```

2. **Create a service account with GCS permissions:**
   ```bash
   gcloud iam service-accounts create mohe-scraper-svc
   gcloud projects add-iam-policy-binding PROJECT_ID \
     --member=serviceAccount:mohe-scraper-svc@PROJECT_ID.iam.gserviceaccount.com \
     --role=roles/storage.objectAdmin
   ```

3. **Create and download service account key:**
   ```bash
   gcloud iam service-accounts keys create mohe-scraper-key.json \
     --iam-account=mohe-scraper-svc@PROJECT_ID.iam.gserviceaccount.com
   ```

4. **Configure environment:**
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/mohe-scraper-key.json
   export GCS_BUCKET=my-gov-rag-bin
   mohe-scraper
   ```

Or add to `.env` and run `source .env && mohe-scraper`.

---

## Scheduling with Cron (Weekly)

Add to `crontab -e`:

```cron
# Run MOHE scraper every Sunday at 2 AM
0 2 * * 0 cd /path/to/mohe-scraper && ./venv/bin/mohe-scraper >> /var/log/mohe-scraper.log 2>&1
```

### Using Cloud Scheduler (GCP)

1. Create a Cloud Run Job from the scraper container image
2. Configure schedule: `0 2 * * 0` (weekly Sunday 2 AM UTC)
3. Set environment: `GOOGLE_APPLICATION_CREDENTIALS`, `GCS_BUCKET`
4. Set memory/CPU limits and timeout as needed

---

## Troubleshooting

### Issue: "Failed to fetch RSS feed"

**Cause:** Network connectivity, MOHE website down, or rate limiting
**Solution:**
- Check internet connection
- Wait a few minutes and retry
- Check MOHE website status manually
- Increase `--log-level DEBUG` to see detailed errors

### Issue: "State database locked"

**Cause:** Another scraper instance is running
**Solution:**
- Stop the other process: `pkill -f mohe-scraper`
- Or use a different `--state-db` path if running in parallel

### Issue: "GCS authentication failed"

**Cause:** Invalid credentials or missing permissions
**Solution:**
- Check `GOOGLE_APPLICATION_CREDENTIALS` points to valid JSON key
- Run `gcloud auth list` to verify credentials
- Verify service account has `storage.objectAdmin` role
- Use `--dry-run` to skip GCS and test parsing locally

### Issue: "No records produced"

**Cause:** RSS feeds are empty or parsing failed
**Solution:**
- Run with `--log-level DEBUG` for detailed parsing info
- Check if MOHE website RSS endpoints are still available
- Review HTML layout changes (site redesigns require config updates)

### Issue: Duplicate records in manifests

**Cause:** Running scraper multiple times without clearing state database
**Solution:**
- Check state database statistics: `sqlite3 data/mohe_state.db "SELECT COUNT(*) FROM state_records;"`
- Delete state database to reset: `rm data/mohe_state.db`
- Deduplication is working correctly if you see `total_items_deduped > 0`

---

## Maintenance

### Periodic Tasks

**Weekly:**
- Review `data/manifests/mohe/crawl_runs.jsonl` for errors
- Confirm `total_items_fetched` is growing (new content)

**Monthly:**
- Archive old `records.jsonl` if file grows large
- Verify GCS storage usage if using cloud storage

**After MOHE Website Redesign:**
- Update `configs/mohe_site_config.yaml` selectors if HTML structure changes
- Test with `--dry-run` before re-running full crawl
- Check for broken RSS feeds (may be moved/renamed)

### Database Maintenance

```bash
# Vacuum and optimize state database
sqlite3 data/mohe_state.db "VACUUM;"

# Check database integrity
sqlite3 data/mohe_state.db "PRAGMA integrity_check;"

# Get statistics
sqlite3 data/mohe_state.db "SELECT COUNT(*), SUM(is_active) FROM state_records;"
```

---

## Performance Tuning

- **Request timeout:** Edit `configs/mohe_site_config.yaml` → `crawl.request_timeout` (default: 30s)
- **Max retries:** Edit `crawl.max_retries` (default: 3)
- **Backoff factor:** Edit `crawl.retry_backoff_factor` (default: 2x)
- **User-Agent:** Update `crawl.user_agent` if MOHE blocks requests

---

## Testing

Run automated tests to verify installation:

```bash
pytest tests/ -v
```

Or with coverage:

```bash
pytest tests/ --cov=mohe_scraper
```

Key test suites:
- `test_url_utils.py` - URL canonicalization and host validation
- `test_parsers.py` - RSS/HTML parsing and date parsing
- `test_state_manager.py` - Deduplication logic

---

## Monitoring & Logs

### Console Output

Standard run shows summary at end:

```
============================================================
CRAWL RUN SUMMARY
============================================================
crawl_run_id: 2026-02-27-mohe
site_slug: mohe
started_at: 2026-02-27T10:00:00Z
completed_at: 2026-02-27T10:15:00Z
status: completed
total_urls_discovered: 150
total_items_fetched: 145
total_items_uploaded: 50
total_items_deduped: 95
total_items_failed: 0
============================================================
```

### File Logs

Set `LOG_LEVEL=DEBUG` for structured JSON logs:

```bash
LOG_LEVEL=DEBUG mohe-scraper 2>&1 | tee scraper.log
```

---

## Recovery & Restart

### Resume Interrupted Crawl

The state database preserves progress:

```bash
# Just re-run — dedup will skip already-processed items
mohe-scraper
```

### Full Re-crawl (Clear State)

```bash
rm data/mohe_state.db
mohe-scraper
```

---

## Documentation

- **Site Configuration:** See `configs/mohe_site_config.yaml` for RSS feeds and HTML selectors
- **Data Models:** See `src/mohe_scraper/models.py` for record schemas
- **Source Code:** Full documentation in docstrings

---

## Support

For issues, check:
1. This runbook's Troubleshooting section
2. Scraper logs with `--log-level DEBUG`
3. Test suite: `pytest tests/ -v`
4. MOHE website directly to verify content availability

---

## License & Compliance

- Respects `robots.txt` and site crawling policies
- Does not bypass authentication or access controls
- Preserves source provenance and metadata
- Suitable for RAG pipelines and compliance archival
