# Dewan Selangor Scraper – Operator Runbook

Scrapes public documents (news, press releases, speeches, committee statements,
hansard, meeting proceedings) from [dewan.selangor.gov.my](https://dewan.selangor.gov.my)
and archives raw HTML pages and embedded PDFs to Google Cloud Storage for
downstream RAG pipelines.

---

## Site Overview

| Property | Value |
|----------|-------|
| Site | dewan.selangor.gov.my |
| Platform | WordPress |
| Discovery | Sitemap index + paginated archive listings |
| Sitemaps | `sitemap_index.xml` → child sitemaps per content type |
| Pagination | `/page/N/` on archive listing pages |
| JS required | No – static HTML is sufficient |
| Rate limit | No explicit limit; default 1 s delay per request |

Content types scraped:

| Section | Source type | doc_type |
|---------|-------------|----------|
| Berita Dewan | listing pages | `press_release` |
| Kenyataan Media | listing pages | `statement` |
| Media Perdana | listing pages | `press_release` |
| Ucapan | sitemap | `speech` |
| Penyata Jawatankuasa | sitemap | `statement` |
| Hansard | sitemap | `report` |
| Urusan Mesyuarat | sitemap | `notice` |
| Sidang | sitemap | `notice` |

---

## Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.11+ |
| pip / venv | any recent |
| Google Cloud SDK (`gcloud`) | any recent (for auth) |

---

## Setup

```bash
# 1. Enter the project directory
cd dewan-selangor-scraper

# 2. Create a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Install the package and dependencies
pip install -e ".[dev]"

# 4. Configure credentials
cp .env.example .env
# Edit .env: set GOOGLE_APPLICATION_CREDENTIALS and GCS_BUCKET
source .env   # or use direnv / dotenv loader of your choice
```

---

## Commands

### Dry run (no GCS upload, no state DB write)

Useful for testing selectors and inspecting `records.jsonl` output before
committing to a live crawl.

```bash
dewan-selangor-scraper --dry-run
```

### Full run

Requires `GCS_BUCKET` to be set in the environment.

```bash
export GCS_BUCKET=my-gov-rag-bucket
dewan-selangor-scraper --site-config configs/dewan_selangor.yaml
```

### Incremental crawl (skip old articles)

```bash
dewan-selangor-scraper --since 2025-01-01
```

### Limit listing pages (quick smoke test)

```bash
dewan-selangor-scraper --dry-run --max-pages 2 --log-level DEBUG
```

### All options

```
dewan-selangor-scraper --help

Options:
  --site-config PATH        Site config YAML  [default: configs/dewan_selangor.yaml]
  --since YYYY-MM-DD        Skip articles published before this date
  --max-pages INTEGER       Limit listing pages per section (0 = unlimited) [default: 0]
  --dry-run                 No GCS upload, no state write
  --db-path PATH            SQLite state DB  [default: data/state.db]
  --manifest-dir PATH       Output directory  [default: data/manifests/dewan-selangor]
  --log-level LEVEL         DEBUG|INFO|WARNING|ERROR  [default: INFO]
  --request-delay FLOAT     Seconds between requests  [default: 1.0]
  -h, --help                Show this message and exit.
```

---

## Output Files

```
data/
  state.db                              # SQLite dedup/state store
  manifests/dewan-selangor/
    records.jsonl                       # One JSON object per scraped document
    crawl_runs.jsonl                    # One JSON object per crawl run
```

### `records.jsonl` schema

```json
{
  "record_id":          "a1b2c3d4e5f6g7h8-abcd1234",
  "source_url":         "https://dewan.selangor.gov.my/berita-dewan/",
  "canonical_url":      "https://dewan.selangor.gov.my/awasi-tambah-baik-sekolah-tahfiz/",
  "title":              "Awasi Tambah Baik Sekolah Tahfiz Yang Tak Berdaftar",
  "published_at":       "2025-11-13",
  "agency":             "Dewan Negeri Selangor",
  "doc_type":           "press_release",
  "content_type":       "text/html",
  "language":           "ms",
  "sha256":             "abc123...",
  "gcs_bucket":         "my-gov-rag-bucket",
  "gcs_object":         "gov-docs/dewan-selangor/raw/2025/11/13/abc123_awasi-tambah-baik.html",
  "gcs_uri":            "gs://my-gov-rag-bucket/gov-docs/dewan-selangor/raw/2025/11/13/abc123_awasi-tambah-baik.html",
  "http_etag":          "\"etag-value\"",
  "http_last_modified": "Wed, 13 Nov 2025 01:30:00 GMT",
  "fetched_at":         "2025-11-13T10:34:56Z",
  "crawl_run_id":       "2025-11-13-dewan-selangor",
  "parser_version":     "v1"
}
```

Embedded PDFs found inside an article produce a second record with:
- `source_url` = the article page URL (where the PDF was embedded)
- `canonical_url` = the direct PDF URL
- `content_type` = `application/pdf`

---

## Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=dewan_selangor_scraper --cov-report=term-missing

# One file
pytest tests/test_extractor.py -v
```

---

## Adding or Enabling New Sections

1. Browse to the target section on dewan.selangor.gov.my and copy the URL.
2. Open `configs/dewan_selangor.yaml` and add a section block:

   **Listing page section** (standard WordPress archive with pagination):
   ```yaml
   - name: berita_cpa
     label: "Berita CPA"
     doc_type: press_release
     language: ms
     source_type: listing
     listing_pages:
       - url: "https://dewan.selangor.gov.my/berita-cpa/"
         label: "Berita CPA"
   ```

   **Sitemap section** (use the child sitemap URL from `sitemap_index.xml`):
   ```yaml
   - name: new_section
     label: "New Section"
     doc_type: notice
     language: ms
     source_type: sitemap
     sitemap_url: "https://dewan.selangor.gov.my/new-section-sitemap.xml"
   ```

3. If the HTML structure of the new section differs significantly from
   standard WordPress archive markup, add a new extractor in
   `src/dewan_selangor_scraper/extractor.py` and dispatch it from
   `pipeline.py:_discover_from_listing`.

4. Add a fixture HTML file and tests in `tests/`.

---

## Scheduling on Google Cloud

```bash
# Build and push the container
docker build -t gcr.io/<PROJECT>/dewan-selangor-scraper:latest .
docker push gcr.io/<PROJECT>/dewan-selangor-scraper:latest

# Create a Cloud Run Job
gcloud run jobs create dewan-selangor-scraper \
  --image gcr.io/<PROJECT>/dewan-selangor-scraper:latest \
  --region asia-southeast1 \
  --service-account dewan-selangor-scraper@<PROJECT>.iam.gserviceaccount.com \
  --set-env-vars GCS_BUCKET=<BUCKET>

# Schedule with Cloud Scheduler (weekly on Monday 02:00 MYT = 18:00 UTC Sunday)
gcloud scheduler jobs create http dewan-selangor-scraper-weekly \
  --schedule "0 18 * * 0" \
  --uri "https://run.googleapis.com/v1/namespaces/<PROJECT>/jobs/dewan-selangor-scraper:run" \
  --http-method POST \
  --oauth-service-account-email dewan-selangor-scraper@<PROJECT>.iam.gserviceaccount.com
```

Minimum IAM roles for the service account:
- `roles/storage.objectAdmin` on the target GCS bucket
- `roles/run.invoker` on the Cloud Run Job

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `ERROR: set GCS_BUCKET` | Env var missing | `export GCS_BUCKET=<bucket>` or use `--dry-run` |
| `ValueError: policy: host not in allowlist` | Link resolves to external domain | Check `allowed_hosts` in config |
| `0 items extracted` from listing | WordPress markup changed | Inspect live page HTML; update `<article>` selector in `extractor.py` |
| `0 items extracted` from sitemap | Sitemap URL changed or 404 | Check `sitemap_index.xml` for current child sitemap URLs |
| `wp_date_parse_failure` in logs | Unusual datetime format | Check `datetime` attribute on `<time>` tag; add handling to `parse_wp_datetime` |
| HTTP 403 on document download | Server-side access control | Document may be gated; skip and log |
| Tenacity retries exhausted | Transient network issue | Increase `--request-delay`; check site availability |
| Embedded PDFs not found | pdfjs viewer shortcode updated | Inspect `<iframe src>` in post HTML; update `_PDFJS_VIEWER_RE` pattern |

---

## Policy Compliance

- No authentication, paywalls, or CAPTCHAs are bypassed.
- The crawler identifies itself via `User-Agent` with a contact address.
- A configurable delay (`--request-delay`, default 1 s) is applied between every request.
- Only public documents linked from public listing pages or sitemaps are downloaded.
- The host allowlist (`allowed_hosts` in config) prevents accidental crawling of external domains.
