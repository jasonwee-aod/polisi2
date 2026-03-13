# MOHE Scraper

**Production-ready web scraper for Malaysia Ministry of Higher Education (MOHE) documents and announcements.**

Build and maintain compliant scrapers for government websites to collect public documents, press releases, statements, and notices for RAG (Retrieval-Augmented Generation) pipelines.

---

## Features

✅ **RSS-First Approach** — Prefers machine-readable feeds over HTML parsing
✅ **Bilingual Support** — Collects both English and Bahasa Melayu content
✅ **Deduplication** — Avoids storing the same document twice (by URL, hash, and etag)
✅ **Incremental Crawling** — Only fetches new/updated content on subsequent runs
✅ **Source Provenance** — Preserves original URLs, timestamps, and metadata
✅ **Cloud Storage** — Archives files to Google Cloud Storage (or local filesystem)
✅ **Structured Logging** — Produces JSONL manifests for downstream processing
✅ **Automated Tests** — Comprehensive test suite for core logic
✅ **Operator Runbook** — Clear setup and troubleshooting documentation

---

## Supported Content Types

- **Announcements** (Pengumuman)
- **Press Releases** (Kenyataan Media)
- **Speeches** (Teks Ucapan)
- **Activities & Events** (Sorotan Aktiviti)
- **Media Coverage** (Liputan Media)
- **Infographics** (Infografik)
- **FAQs** (Soalan Lazim)
- **Job Tenders** (Tender Kerja)

---

## Quick Start

### Installation

```bash
# Install dependencies
pip install -e .

# Or for development
pip install -e ".[dev]"
```

### Run Scraper

```bash
# Full crawl (downloads documents, builds manifest)
mohe-scraper

# Preview without downloading
mohe-scraper --dry-run

# Debug mode
mohe-scraper --log-level DEBUG
```

### View Results

```bash
cat data/manifests/mohe/records.jsonl       # All documents
cat data/manifests/mohe/crawl_runs.jsonl    # Execution log
```

---

## Project Structure

```
mohe-scraper/
├── src/mohe_scraper/
│   ├── __init__.py
│   ├── cli.py              # Command-line interface
│   ├── crawler.py          # Main scraper logic
│   ├── models.py           # Data models (ScraperRecord, CrawlRun)
│   ├── parsers.py          # RSS and HTML parsing
│   ├── state_manager.py    # Deduplication state (SQLite)
│   ├── storage.py          # GCS and local file storage
│   └── url_utils.py        # URL canonicalization
├── configs/
│   └── mohe_site_config.yaml  # RSS feeds and selectors
├── tests/
│   ├── test_url_utils.py
│   ├── test_parsers.py
│   └── test_state_manager.py
├── data/
│   ├── mohe_state.db       # Dedup state database (generated)
│   └── manifests/mohe/     # Output records (generated)
├── pyproject.toml
├── .env.example
├── README.md               # This file
└── RUNBOOK.md              # Operator guide
```

---

## Output Format

### records.jsonl

One JSON object per line, each representing a document:

```json
{
  "record_id": "stable-id",
  "source_url": "https://www.mohe.gov.my/...",
  "canonical_url": "https://mohe.gov.my/...",
  "title": "Document Title",
  "published_at": "2026-02-27",
  "agency": "Ministry of Higher Education (MOHE)",
  "doc_type": "press_release|announcement|statement|report|speech|notice|other",
  "content_type": "text/html|application/pdf|...",
  "language": "en|ms",
  "sha256": "hex-hash",
  "fetched_at": "2026-02-27T12:34:56Z",
  "http_etag": "\"abc123\"",
  "http_last_modified": "Wed, 27 Feb 2026 10:00:00 GMT",
  "gcs_uri": "gs://bucket/gov-docs/mohe/raw/2026/02/27/sha256_file.pdf",
  "gcs_bucket": "my-bucket",
  "gcs_object": "gov-docs/mohe/raw/2026/02/27/sha256_file.pdf",
  "crawl_run_id": "2026-02-27-mohe",
  "parser_version": "v1"
}
```

### crawl_runs.jsonl

Metadata about each crawl execution:

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

## Configuration

### Site Config (mohe_site_config.yaml)

Defines RSS feeds and HTML selectors:

```yaml
site:
  name: "Ministry of Higher Education Malaysia"
  slug: "mohe"
  domain: "www.mohe.gov.my"
  base_url: "https://www.mohe.gov.my"
  allowed_hosts:
    - "www.mohe.gov.my"
    - "mohe.gov.my"

rss_feeds:
  - name: "announcements"
    url_en: "https://www.mohe.gov.my/en/broadcast/announcements?format=feed&type=rss"
    url_ms: "https://www.mohe.gov.my/ms/broadcast/announcements?format=feed&type=rss"
    doc_type: "announcement"
```

### Environment (.env)

```bash
# Optional GCS configuration
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json
GCS_BUCKET=my-gov-rag-bin

# Runtime settings
DATA_DIR=./data
STATE_DB_PATH=./data/mohe_state.db
LOG_LEVEL=INFO
```

---

## Storage Options

### Option 1: Local Filesystem (Default)

Documents saved to `./data/documents/`:

```bash
mohe-scraper
```

### Option 2: Google Cloud Storage

Set environment and run:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
export GCS_BUCKET=my-bucket
mohe-scraper
```

---

## Testing

Run automated tests:

```bash
pytest tests/ -v

# With coverage
pytest tests/ --cov=mohe_scraper
```

**Test Coverage:**
- URL normalization and deduplication logic
- RSS and HTML parsing
- Date parsing (English and Malay month names)
- State manager (SQLite operations)

---

## Scheduling

### Cron (Weekly)

```cron
0 2 * * 0 cd /path/to/mohe-scraper && mohe-scraper
```

### Cloud Scheduler (GCP)

Create a Cloud Run Job with schedule `0 2 * * 0` (Sunday 2 AM UTC)

---

## Troubleshooting

See **RUNBOOK.md** for detailed troubleshooting guide:
- Network/connectivity issues
- Database locks
- GCS authentication
- Content discovery problems
- Deduplication questions

---

## Design Principles

1. **Compliance First** — Respects robots.txt, doesn't bypass auth, preserves provenance
2. **Machine-Readable** — Prefers RSS feeds over HTML scraping
3. **Incremental** — Only fetches new/updated content after initial crawl
4. **Minimal Duplicates** — Deduplicates by canonical URL, ETag, and content hash
5. **Stateful** — Maintains SQLite state for reliable incremental crawls
6. **Transparent** — Structured logging and detailed manifests
7. **Testable** — Comprehensive unit tests for core logic

---

## Architecture

**RSS-First Crawl Flow:**

1. Load site config (RSS feeds, HTML selectors, metadata)
2. For each RSS feed (English + Malay):
   - Fetch and parse RSS feed
   - For each item in feed:
     - Check canonical URL (dedup by URL)
     - Fetch document content
     - Compute SHA256 hash
     - Check hash (dedup by content)
     - Store in GCS/local
     - Create ScraperRecord
     - Save to state database
3. Output records.jsonl and crawl_runs.jsonl

**Deduplication Strategy:**

- **By URL:** Skip if canonical URL already in state
- **By ETag/Last-Modified:** Skip if unchanged
- **By Content Hash:** Reuse existing storage if same content fetched from different URL
- **Incremental:** State persists across runs

---

## Security & Compliance

✅ No authentication bypass
✅ Respects robots.txt
✅ No payload manipulation
✅ HTTPS only
✅ Preserves source metadata
✅ No sensitive data in URLs
✅ Suitable for government/compliance archival

---

## Performance

- **Request timeout:** 30 seconds (configurable)
- **Retry strategy:** Exponential backoff (3 attempts)
- **Batch processing:** 50 items per batch
- **State database:** Indexed by canonical_url and sha256
- **Single session:** Reuses HTTP connection pool

---

## Python Requirements

- Python 3.11+
- Dependencies locked in `pyproject.toml`

---

## License

For use in government document archival, RAG pipelines, and compliance collections.

---

## Documentation

- **RUNBOOK.md** — Complete operator guide (setup, running, scheduling, troubleshooting)
- **src/mohe_scraper/** — Detailed docstrings in source code
- **tests/** — Examples of usage patterns

---

## Contributing

To extend the scraper for new government sites:

1. Copy `configs/mohe_site_config.yaml` → `configs/new_site_config.yaml`
2. Update RSS feeds, selectors, and metadata
3. Update `src/mohe_scraper/cli.py` to add new site option
4. Add integration test with sample HTML fixtures
5. Test with `--dry-run` before production

---

## Support

For issues:
1. Check **RUNBOOK.md** troubleshooting section
2. Run with `--log-level DEBUG` for detailed logs
3. Verify content availability directly on MOHE website
4. Review test suite: `pytest tests/ -v -s`

---

**Last Updated:** 2026-02-27
**Scraper Version:** 1.0.0
**Site:** https://www.mohe.gov.my
