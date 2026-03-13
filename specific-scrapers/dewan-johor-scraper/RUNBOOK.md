# Dewan Negeri Johor Scraper – Operator Runbook

## Overview

Scrapes public documents from **dewannegeri.johor.gov.my** and archives raw
originals to Google Cloud Storage. Two content types are collected:

| Section | Source | doc_type |
|---|---|---|
| Pengumuman (Announcements) | WP native sitemap → post pages | `press_release` |
| Penyata Rasmi (Session Documents) | WP native sitemap → wpdmpro package pages → WPDM file redirects | `report` |

Documents are deduplicated by canonical URL and sha256. Run state is stored in
a local SQLite database.

---

## Prerequisites

- Python 3.11+
- `pip install -e ".[dev]"` (or `pip install -e .` for non-dev install)
- Google Cloud credentials set via `GOOGLE_APPLICATION_CREDENTIALS`
- A GCS bucket with write access set in `GCS_BUCKET`

```bash
cd dewan-johor-scraper
pip install -e ".[dev]"
```

> **Python 3.9 workaround:** The package targets 3.11+ but works on 3.9 system Python.
> Run `pip3 install requests beautifulsoup4 lxml python-dateutil google-cloud-storage tenacity pyyaml click` directly if `pip install -e .` fails on an old pip.

---

## Quick Start

### Dry run (no GCS upload, inspect output only)

```bash
dewan-johor-scraper --dry-run --log-level DEBUG
```

### Smoke test (first 2 listing pages per section)

```bash
dewan-johor-scraper --dry-run --max-pages 2
```

### Incremental run (new documents since a date)

```bash
export GCS_BUCKET=my-gov-rag-bucket
dewan-johor-scraper --since 2024-01-01
```

### Full run

```bash
export GCS_BUCKET=my-gov-rag-bucket
dewan-johor-scraper
```

---

## CLI Reference

```
Usage: dewan-johor-scraper [OPTIONS]

  Dewan Negeri Johor Government Site Scraper – archives public documents to GCS.

Options:
  --site-config TEXT          Path to site config YAML.  [default: configs/dewan_johor.yaml]
  --since YYYY-MM-DD          Skip articles published before this date.
  --max-pages INTEGER         Limit listing pages fetched per section (0=unlimited).  [default: 0]
  --dry-run                   Fetch and parse, no GCS upload, no state write.
  --db-path TEXT              SQLite state database path.  [default: data/state.db]
  --manifest-dir TEXT         Output directory for records.jsonl and crawl_runs.jsonl.
                              [default: data/manifests/dewan-johor]
  --log-level [DEBUG|INFO|WARNING|ERROR]  [default: INFO]
  --request-delay FLOAT       Seconds between HTTP requests.  [default: 1.0]
  -h, --help                  Show this message and exit.
```

Environment variables:
- `GCS_BUCKET` – required for live runs
- `GOOGLE_APPLICATION_CREDENTIALS` – path to service account JSON
- `DEWAN_JOHOR_DB_PATH` – override `--db-path`
- `DEWAN_JOHOR_MANIFEST_DIR` – override `--manifest-dir`

---

## Output Files

```
data/
  state.db                          ← SQLite dedup state
  manifests/dewan-johor/
    records.jsonl                   ← one JSON object per archived document
    crawl_runs.jsonl                ← one JSON object per crawl run
```

### `records.jsonl` schema

```json
{
  "record_id": "abc123-uuid",
  "source_url": "https://dewannegeri.johor.gov.my/wp-sitemap-posts-wpdmpro-1.xml",
  "canonical_url": "https://dewannegeri.johor.gov.my/download/28-jun-2018/",
  "title": "28 Jun 2018",
  "published_at": "2019-11-11",
  "agency": "Dewan Negeri Johor",
  "doc_type": "report",
  "content_type": "text/html",
  "language": "ms",
  "sha256": "deadbeef...",
  "gcs_bucket": "my-gov-rag-bucket",
  "gcs_object": "gov-docs/dewan-johor/raw/2026/03/01/deadbeef_28-jun-2018.html",
  "gcs_uri": "gs://my-gov-rag-bucket/gov-docs/dewan-johor/raw/2026/03/01/deadbeef_28-jun-2018.html",
  "http_etag": "\"abc123\"",
  "http_last_modified": "Wed, 14 May 2020 05:48:42 GMT",
  "fetched_at": "2026-03-01T10:00:00Z",
  "crawl_run_id": "2026-03-01-dewan-johor",
  "parser_version": "v1"
}
```

---

## How WPDM Downloads Are Handled

The site uses **WP Download Manager Pro** (wpdmpro post type) for session documents.

Each package page (`/download/{slug}/`) contains one or more files listed in a
`table.wpdm-filelist`. Each row has a download button:

```html
<a class="inddl" href="/download/28-jun-2018/?wpdmdl=3910&ind=1573438553673">
  Download
</a>
```

This link is a **redirect URL** – the server responds with a 302 redirect to the
actual file (e.g. `/wp-content/uploads/2019/11/PR-Jun-2018.pdf`). The scraper:

1. Archives the wpdmpro HTML page itself as a `text/html` record.
2. Extracts all `a.inddl[href*=wpdmdl]` links from the page.
3. For each link, fetches it with `requests` (which follows redirects automatically).
4. Uses the final URL (`resp.url`) as the canonical URL for deduplication.
5. Archives the resolved file (PDF) as a separate record with the final URL.

---

## Site Config

Edit `configs/dewan_johor.yaml` to add or disable sections. To scrape static
pages as well, uncomment the `static_pages` section.

---

## Running Tests

```bash
python3 -m pytest tests/ -v
```

Expected output: all tests pass (~30 tests across 4 test files).

---

## Scheduling (Cloud Run Jobs)

Build and push the container:

```bash
docker build -t gcr.io/my-project/dewan-johor-scraper .
docker push gcr.io/my-project/dewan-johor-scraper
```

Create a Cloud Run Job:

```bash
gcloud run jobs create dewan-johor-scraper \
  --image gcr.io/my-project/dewan-johor-scraper \
  --set-env-vars GCS_BUCKET=my-gov-rag-bucket \
  --set-secrets GOOGLE_APPLICATION_CREDENTIALS=sa-key:latest \
  --region asia-southeast1
```

Schedule with Cloud Scheduler (weekly on Mondays):

```bash
gcloud scheduler jobs create http dewan-johor-weekly \
  --schedule "0 2 * * 1" \
  --uri "https://run.googleapis.com/v1/namespaces/my-project/jobs/dewan-johor-scraper:run" \
  --http-method POST \
  --oauth-service-account-email scraper-sa@my-project.iam.gserviceaccount.com
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `policy: host not in allowlist` | URL resolves to unexpected host | Check `allowed_hosts` in YAML |
| `ERROR: set GCS_BUCKET` | Missing env var | Export `GCS_BUCKET` or use `--dry-run` |
| `wpdm_file_links_extracted … count=0` | WPDM markup changed | Update `extract_wpdm_file_links` selector |
| Empty `published_at` on wpdmpro page | WPDM metadata labels changed | Check `li.list-group-item` text against live site |
| `sitemap_parse_empty` | Sitemap URL path changed | Re-check `/wp-sitemap.xml` for current child sitemaps |
| `429` rate-limit responses | Crawling too fast | Increase `--request-delay` (e.g. `--request-delay 2.0`) |
