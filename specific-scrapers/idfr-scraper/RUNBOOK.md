# IDFR Scraper – Operator Runbook

Scraper for **https://www.idfr.gov.my/my/** – Institut Diplomasi dan Hubungan Luar Negeri (IDFR).
Archives press releases, speeches, and publications to Google Cloud Storage for RAG pipelines.

---

## Site Profile

| Property | Value |
|---|---|
| CMS | Joomla 4 + Helix Ultimate template + SP Page Builder |
| Sitemap | None (404) |
| RSS | None |
| Pagination | None – content on single pages, grouped by year |
| Main sections | Press Releases, Speeches, Publications |

---

## Quick Start

### 1. Install dependencies

```bash
cd idfr-scraper
pip install -e ".[dev]"
```

### 2. Configure credentials

```bash
cp .env.example .env
# Edit .env – set GOOGLE_APPLICATION_CREDENTIALS and GCS_BUCKET
source .env
```

### 3. Dry run (no GCS, no state DB writes)

```bash
idfr-scraper --dry-run
```

### 4. Full run

```bash
idfr-scraper
```

### 5. Incremental run (since a date)

```bash
idfr-scraper --since 2024-01-01
```

---

## CLI Reference

```
idfr-scraper [OPTIONS]

Options:
  --site-config PATH        Site config YAML  [default: configs/idfr.yaml]
  --since YYYY-MM-DD        Skip documents published before this date
  --max-pages INTEGER       Limit listing pages fetched (0 = unlimited)  [default: 0]
  --dry-run                 Fetch/parse only – no GCS upload, no DB write
  --db-path PATH            SQLite state DB path  [default: data/state.db]
  --manifest-dir PATH       Output directory  [default: data/manifests/idfr]
  --log-level LEVEL         DEBUG|INFO|WARNING|ERROR  [default: INFO]
  --request-delay FLOAT     Polite delay between requests (seconds)  [default: 1.0]
  -h, --help                Show this message and exit.
```

---

## Output Files

```
data/
  manifests/idfr/
    records.jsonl       # One JSON object per archived document
    crawl_runs.jsonl    # One JSON object per crawl run (appended)
  state.db              # SQLite dedup state
```

### records.jsonl schema

```json
{
  "record_id": "abc123...-a1b2c3d4",
  "source_url": "https://www.idfr.gov.my/my/media-1/press",
  "canonical_url": "https://www.idfr.gov.my/my/images/stories/press/test.pdf",
  "title": "Press Release: IDFR DISTINGUISHED LECTURE SERIES",
  "published_at": "2025-01-01",
  "agency": "Institut Diplomasi dan Hubungan Luar Negeri (IDFR)",
  "doc_type": "press_release",
  "content_type": "application/pdf",
  "language": "ms",
  "sha256": "...",
  "gcs_bucket": "your-bucket",
  "gcs_object": "gov-docs/idfr/raw/2025/01/15/sha256_test.pdf",
  "gcs_uri": "gs://your-bucket/gov-docs/idfr/raw/2025/01/15/sha256_test.pdf",
  "http_etag": "\"abc123\"",
  "http_last_modified": "",
  "fetched_at": "2025-01-15T08:00:00Z",
  "crawl_run_id": "2025-01-15-idfr",
  "parser_version": "v1"
}
```

---

## Sections Scraped

### Press Releases (`press`)
- **URL**: `https://www.idfr.gov.my/my/media-1/press`
- **Structure**: Single page, year headings (`<p><strong>YYYY</strong></p>`), deeply nested `<li><a href="...pdf">` items
- **Date**: Year only → stored as `YYYY-01-01` (no day/month in source)
- **doc_type**: `press_release`

### Speeches (`speeches`)
- **URL**: `https://www.idfr.gov.my/my/media-1/speeches` (current year)
- **Structure**: HTML table, one row per speech
- **Date**: Extracted from parenthetical in title, `<strong>` tag, or H1 year fallback
- **Adding older years**: Add URLs to `listing_urls` in `configs/idfr.yaml` for archived years (e.g. `https://www.idfr.gov.my/my/media-1/speeches-2024`)
- **doc_type**: `speech`

### Publications (`publications`)
- **URL**: `https://www.idfr.gov.my/my/publications`
- **Structure**: SP Page Builder feature boxes
  - **Direct PDFs**: Prospectus, Annual Reports → archived directly
  - **Sub-listing pages**: Newsletter, JDFR, Other publications → fetched and PDFs extracted
- **doc_type**: `report`

---

## Deduplication

Three-layer dedup prevents duplicate storage:

1. **Pre-fetch by URL**: If `canonical_url` already in state DB → skip fetch
2. **Post-fetch by SHA-256**: If content hash already in DB → reuse existing GCS path, skip upload
3. **ETag/Last-Modified**: Future change detection (stored but not yet used for re-fetch)

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | Yes (live) | Path to GCS service account JSON |
| `GCS_BUCKET` | Yes (live) | GCS bucket name |
| `IDFR_DB_PATH` | No | Override SQLite DB path |
| `IDFR_MANIFEST_DIR` | No | Override manifest output directory |

---

## Running Tests

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run with coverage
python3 -m pytest tests/ -v --cov=src/idfr_scraper --cov-report=term-missing

# Run specific test class
python3 -m pytest tests/test_dates.py -v
```

All tests are offline (no network required). GCS is mocked via dry-run mode.

---

## Troubleshooting

### `ERROR: set GCS_BUCKET environment variable or use --dry-run.`
Add `export GCS_BUCKET=your-bucket-name` to your shell or `.env` file, or add `--dry-run`.

### No items discovered for a section
- The site may have changed HTML structure. Check the section URL manually.
- Run with `--log-level DEBUG` to see parsing details.
- Check `extract_press_listing`, `extract_speeches_listing`, or `extract_publications_hub` in `extractor.py`.

### Speeches older than the current year are missing
The speeches listing page only shows the current year. Add older year URLs to `listing_urls` in `configs/idfr.yaml`:
```yaml
  - name: speeches
    source_type: speeches_listing
    listing_urls:
      - "https://www.idfr.gov.my/my/media-1/speeches"
      - "https://www.idfr.gov.my/my/media-1/speeches-2024"
```
Confirm the actual URL pattern by checking the site directly.

### Publications sub-page not scraped
If a new sub-listing page appears under `/my/publications`, it should be automatically discovered via the publications hub. If it's an external link (e.g. `cas.idfr.gov.my`), it will be skipped by the host allowlist. To add it as an explicit section, add a new `article_body_listing` entry in `configs/idfr.yaml`.

### `host not in allowlist` error
Only `www.idfr.gov.my` and `idfr.gov.my` are allowed by default. Add extra hosts to `allowed_hosts` in `configs/idfr.yaml` if IDFR hosts PDFs on another domain.

---

## DigitalOcean Droplet Scheduling

```ini
# /etc/systemd/system/idfr-scraper.service
[Unit]
Description=IDFR Scraper
After=network.target

[Service]
Type=oneshot
User=polisi
WorkingDirectory=/opt/polisigpt/idfr-scraper
EnvironmentFile=/opt/polisigpt/.env
ExecStart=idfr-scraper --site-config configs/idfr.yaml
StandardOutput=append:/opt/polisigpt/logs/idfr-scraper.log
StandardError=append:/opt/polisigpt/logs/idfr-scraper.log
TimeoutStartSec=600
TimeoutStopSec=60
```

```ini
# /etc/systemd/system/idfr-scraper.timer
[Unit]
Description=Run IDFR scraper every 3 days

[Timer]
OnCalendar=*-*-01,04,07,10,13,16,19,22,25,28 01:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl enable --now idfr-scraper.timer
journalctl -u idfr-scraper.service -f
```
