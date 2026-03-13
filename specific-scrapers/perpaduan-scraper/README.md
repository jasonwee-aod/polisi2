# Perpaduan Scraper

Production-ready scraper for Kementerian Perpaduan Negara (https://www.perpaduan.gov.my).

## Overview

This scraper collects press releases, news, statements, policies, and notices from the Perpaduan website and archives them to DigitalOcean Spaces for downstream RAG pipelines.

## Features

- **Canonical URL normalization** — prevents duplicate storage
- **SHA256 content hashing** — deduplicates identical documents
- **ETag/Last-Modified tracking** — incremental updates
- **Structured metadata** — records.jsonl with full provenance
- **Error resilience** — retries with exponential backoff
- **Compliance** — respects robots.txt, applies rate limiting

## Quick Start

### 1. Installation

```bash
cd perpaduan-scraper
python -m pip install -e ".[dev]"
```

### 2. Configure Spaces (Optional)

Set environment variables for DigitalOcean Spaces uploads:

```bash
export DO_SPACES_BUCKET="your-bucket"
export DO_SPACES_KEY="your-access-key"
export DO_SPACES_SECRET="your-secret-key"
export DO_SPACES_REGION="sgp1"
```

If not set, scraper will run in dry-run mode (no uploads).

### 3. Test Crawl

```bash
python -m src.main \
  --site-config configs/perpaduan.yaml \
  --max-pages 5 \
  --dry-run \
  --log-level INFO
```

### 4. Full Crawl

```bash
python -m src.main \
  --site-config configs/perpaduan.yaml \
  --log-level INFO
```

## Output

### records.jsonl

One JSON object per record:

```json
{
  "record_id": "uuid",
  "source_url": "https://...",
  "canonical_url": "https://...",
  "title": "Document title",
  "published_at": "2026-03-09",
  "agency": "Kementerian Perpaduan Negara",
  "doc_type": "news|press_release|report|notice|other",
  "content_type": "text/html",
  "language": "ms",
  "sha256": "hex",
  "spaces_bucket": "my-gov-spaces",
  "spaces_path": "gov-my/perpaduan/2026-03/abc123.html",
  "spaces_url": "https://...",
  "http_etag": "...",
  "http_last_modified": "...",
  "fetched_at": "2026-03-09T12:00:00Z",
  "crawl_run_id": "2026-03-09-perpaduan",
  "parser_version": "v1"
}
```

### crawl_runs.jsonl

Append-only log of crawl runs:

```json
{
  "crawl_run_id": "2026-03-09-perpaduan",
  "site_slug": "perpaduan",
  "started_at": "2026-03-09T12:00:00Z",
  "completed_at": "2026-03-09T13:30:00Z",
  "discovered": 150,
  "fetched": 145,
  "uploaded": 140,
  "deduped": 5,
  "failed": 0
}
```

## Configuration

Edit `configs/perpaduan.yaml` to:
- Add/remove sections to crawl
- Adjust CSS selectors for extraction
- Change HTTP client settings (timeout, delay)

## Testing

```bash
pytest tests/ -v --cov=src
```

## Project Structure

```
perpaduan-scraper/
├── src/
│   ├── main.py           # CLI entry
│   ├── scraper.py        # Orchestration
│   ├── crawler.py        # HTTP + parsing
│   ├── url_utils.py      # Canonicalization
│   ├── deduplication.py  # SQLite state
│   ├── spaces.py         # DO Spaces
│   ├── models.py         # Data classes
│   └── __init__.py
├── tests/                # Unit + integration tests
├── configs/
│   └── perpaduan.yaml    # Site config
├── data/
│   └── manifests/
│       └── perpaduan/    # Output directory
├── .cache/               # SQLite state
├── README.md
├── QUICKSTART.md
├── RUNBOOK.md
└── pyproject.toml
```

## CLI Flags

- `--site-config` (required): Path to YAML config file
- `--state-db`: SQLite database path (default: `.cache/scraper_state.sqlite3`)
- `--output-dir`: Output directory (default: `data/manifests/perpaduan`)
- `--max-pages`: Limit pages crawled per section (default: unlimited)
- `--dry-run`: Don't upload to Spaces
- `--log-level`: DEBUG|INFO|WARNING|ERROR (default: INFO)

## Deduplication Logic

1. **By canonical_url**: Skip if URL already in SQLite and status='active'
2. **By sha256**: Check if content hash exists; reuse spaces_path if found
3. **By ETag/Last-Modified**: Skip fetch if unchanged since last crawl

## Non-Negotiables

- ✅ Preserves provenance (source_url, fetch timestamp, checksum)
- ✅ Keeps raw originals in DigitalOcean Spaces
- ✅ No duplicate storage (dedup by URL + hash)
- ✅ Respects robots.txt (rate limits, delays)
- ✅ No CAPTCHA/auth bypass
- ✅ Produces valid records.jsonl and crawl_runs.jsonl

## Troubleshooting

### "No Spaces credentials"

Run with `--dry-run` if you don't have DigitalOcean Spaces set up yet.

### "HTML parse error"

Check that CSS selectors in config match actual page structure. May need to inspect page and adjust selectors.

### Empty records

Verify:
- Section URLs are correct and accessible
- CSS selectors match elements in page HTML
- No JavaScript rendering required (use Playwright fallback if needed)

## Future Enhancements

- Playwright fallback for JavaScript-rendered pages
- Multi-language support (currently Malay only)
- Incremental pagination detection
- PDF extraction and text indexing
