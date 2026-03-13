# KPKT Scraper – Operator Runbook

Scrapes public documents (press releases, and extensible to circulars, speeches,
publications) from [kpkt.gov.my](https://www.kpkt.gov.my) and archives raw files
to Google Cloud Storage for downstream RAG pipelines.

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
# 1. Clone / enter the project directory
cd kpkt-scraper

# 2. Create a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Install the package and dependencies
pip install -e ".[dev]"

# 4. Configure credentials
cp .env.example .env
# Edit .env: set GOOGLE_APPLICATION_CREDENTIALS and GCS_BUCKET
source .env   # or use `direnv` / dotenv loader of your choice
```

---

## Commands

### Dry run (no GCS upload, no state DB write)

Useful for testing selectors and inspecting `records.jsonl` output before
committing to a live crawl.

```bash
kpkt-scraper --dry-run
```

### Full run

Requires `GCS_BUCKET` to be set in the environment.

```bash
export GCS_BUCKET=my-gov-rag-bucket
kpkt-scraper --site-config configs/kpkt.yaml
```

### Incremental crawl (skip old documents)

```bash
kpkt-scraper --since 2025-01-01
```

### Limit listing pages (quick smoke test)

```bash
kpkt-scraper --dry-run --max-pages 1 --log-level DEBUG
```

### All options

```
kpkt-scraper --help

Options:
  --site-config PATH        Site config YAML  [default: configs/kpkt.yaml]
  --since YYYY-MM-DD        Skip documents published before this date
  --max-pages INTEGER       Limit listing pages (0 = unlimited)  [default: 0]
  --dry-run                 No GCS upload, no state write
  --db-path PATH            SQLite state DB  [default: data/state.db]
  --manifest-dir PATH       Output directory  [default: data/manifests/kpkt]
  --log-level LEVEL         DEBUG|INFO|WARNING|ERROR  [default: INFO]
  --request-delay FLOAT     Seconds between requests  [default: 1.0]
  -h, --help                Show this message and exit.
```

---

## Output Files

```
data/
  state.db                          # SQLite dedup/state store
  manifests/kpkt/
    records.jsonl                   # One JSON object per scraped document
    crawl_runs.jsonl                # One JSON object per crawl run
```

### `records.jsonl` schema

```json
{
  "record_id":          "a1b2c3d4e5f6g7h8-abcd1234",
  "source_url":         "https://www.kpkt.gov.my/index.php/pages/view/3470?mid=764",
  "canonical_url":      "https://www.kpkt.gov.my/kpkt/resources/user_1/media_akhbar/2025/SM_EXAMPLE.pdf",
  "title":              "KPKT Serah Kunci Rumah Kepada 18 Mangsa Letupan Gas",
  "published_at":       "2025-12-04",
  "agency":             "Kementerian Perumahan dan Kerajaan Tempatan",
  "doc_type":           "press_release",
  "content_type":       "application/pdf",
  "language":           "ms",
  "sha256":             "abc123...",
  "gcs_bucket":         "my-gov-rag-bucket",
  "gcs_object":         "gov-docs/kpkt/raw/2025/12/04/abc123_SM_EXAMPLE.pdf",
  "gcs_uri":            "gs://my-gov-rag-bucket/gov-docs/kpkt/raw/2025/12/04/abc123_SM_EXAMPLE.pdf",
  "http_etag":          "\"etag-value\"",
  "http_last_modified": "Wed, 04 Dec 2025 07:00:00 GMT",
  "fetched_at":         "2025-12-04T10:34:56Z",
  "crawl_run_id":       "2025-12-04-kpkt",
  "parser_version":     "v1"
}
```

---

## Running Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=kpkt_scraper --cov-report=term-missing

# One file
pytest tests/test_extractor.py -v
```

---

## Adding New Sections (Circulars, Speeches, Publications)

1. Browse to the target section on kpkt.gov.my and copy the URL.
2. Open `configs/kpkt.yaml` and uncomment / add the section block:

   ```yaml
   - name: teks_ucapan
     doc_type: speech
     language: ms
     listing_pages:
       - url: "https://www.kpkt.gov.my/index.php/pages/view/<ID>?mid=<MID>"
         label: "Teks Ucapan"
   ```

3. If the new section uses the same jQuery UI Accordion structure as Siaran
   Media, `extract_siaran_media` will work out of the box.  If the HTML
   structure differs, add a new extractor function in `src/kpkt_scraper/extractor.py`
   and register it in `pipeline.py:_dispatch_extractor`.

4. Add a fixture HTML file and tests in `tests/`.

---

## Scheduling on Google Cloud

```bash
# Build and push the container
docker build -t gcr.io/<PROJECT>/kpkt-scraper:latest .
docker push gcr.io/<PROJECT>/kpkt-scraper:latest

# Create a Cloud Run Job
gcloud run jobs create kpkt-scraper \
  --image gcr.io/<PROJECT>/kpkt-scraper:latest \
  --region asia-southeast1 \
  --service-account kpkt-scraper@<PROJECT>.iam.gserviceaccount.com \
  --set-env-vars GCS_BUCKET=<BUCKET>

# Schedule with Cloud Scheduler (weekly on Monday 01:00 MYT = 17:00 UTC Sunday)
gcloud scheduler jobs create http kpkt-scraper-weekly \
  --schedule "0 17 * * 0" \
  --uri "https://run.googleapis.com/v1/namespaces/<PROJECT>/jobs/kpkt-scraper:run" \
  --http-method POST \
  --oauth-service-account-email kpkt-scraper@<PROJECT>.iam.gserviceaccount.com
```

Minimum IAM roles for the service account:
- `roles/storage.objectAdmin` on the target GCS bucket
- `roles/run.invoker` on the Cloud Run Job

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `ERROR: set GCS_BUCKET` | Env var missing | `export GCS_BUCKET=<bucket>` or use `--dry-run` |
| `ValueError: policy: host not in allowlist` | Link resolves to external domain | Check `allowed_hosts` in config; adjust if needed |
| `0 items extracted` | Accordion selector changed | Inspect live page HTML; update `accordion_` ID pattern in `extractor.py` |
| `date_parse_failure` in logs | New date format | Check raw date text; add mapping to `MALAY_MONTHS` dict |
| HTTP 403 on document download | Server-side access control | Document may be gated; mark `doc_type` appropriately and skip |
| Tenacity retries exhausted | Transient network issue | Increase `--request-delay`; check site availability |

---

## Policy Compliance

- No authentication, paywalls, or CAPTCHAs are bypassed.
- The crawler identifies itself via `User-Agent` with a contact address.
- A configurable delay (`--request-delay`, default 1 s) is applied between every request.
- Only public documents linked from public listing pages are downloaded.
