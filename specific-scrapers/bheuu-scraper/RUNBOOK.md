# BHEUU Scraper – Operator Runbook

## Overview

Scraper for **Bahagian Hal Ehwal Undang-undang (BHEUU)** at `https://www.bheuu.gov.my`.

### Architecture

| Layer | Detail |
|---|---|
| Frontend | Nuxt.js SSR (`www.bheuu.gov.my`) |
| CMS API | **Strapi v3** (`strapi.bheuu.gov.my`) – JSON, no auth required |
| Files | `strapi.bheuu.gov.my/uploads/` – PDFs served directly |
| Storage | DigitalOcean Spaces (S3-compatible via boto3) |
| State | SQLite (`data/state.db`) |

No HTML scraping is needed. All content is fetched from the public Strapi REST API.

---

## Setup

### 1. Install dependencies

```bash
cd bheuu-scraper
pip3 install python-dateutil pyyaml click requests tenacity boto3
# or with editable install:
pip3 install -e ".[dev]"
```

### 2. Configure credentials

```bash
cp .env.example .env
# Edit .env with your DigitalOcean Spaces credentials
```

Required environment variables:

```bash
export DO_SPACES_KEY=your-access-key
export DO_SPACES_SECRET=your-secret-key
export DO_SPACES_BUCKET=your-bucket-name
export DO_SPACES_REGION=sgp1
export DO_SPACES_ENDPOINT=https://sgp1.digitaloceanspaces.com
```

---

## Running the scraper

### Full run

```bash
source .env
python3 -m bheuu_scraper.cli --site-config configs/bheuu.yaml
```

### Dry run (no upload, no state write)

```bash
python3 -m bheuu_scraper.cli --dry-run
```

### Incremental run (only records on/after a date)

```bash
python3 -m bheuu_scraper.cli --since 2025-01-01
```

### Quick smoke test (2 pages per section)

```bash
python3 -m bheuu_scraper.cli --dry-run --max-pages 2
```

### Custom paths

```bash
python3 -m bheuu_scraper.cli \
  --site-config configs/bheuu.yaml \
  --db-path /opt/polisigpt/.cache/bheuu_state.db \
  --manifest-dir /opt/polisigpt/data/manifests/bheuu \
  --log-level DEBUG
```

---

## Output

```
data/manifests/bheuu/
  records.jsonl      – one JSON record per archived document
  crawl_runs.jsonl   – one JSON line per crawl run (summary stats)
```

### Run summary example

```
=== Crawl Summary ===
  Run ID   : 2026-03-09-bheuu
  New      : 243
  Changed  : 0
  Skipped  : 12
  Failed   : 0
  Started  : 2026-03-09T01:00:00Z
  Completed: 2026-03-09T01:04:32Z
```

---

## Sections collected

| Section | Endpoint | Type | Count (approx) | Key files |
|---|---|---|---|---|
| Media Statements | `/media-statements` | collection | 146+ | PDFs via `fileName.url` |
| Annual Reports | `/annual-reports` | collection | 6 | PDFs via `url` |
| eBuletin | `/ebuletins` | collection | 26+ | PDFs via `url` |
| Strategic Plans | `/strategic-plans` | collection | 4 | PDFs via `url` |
| FOI Publications | `/publication-fois` | collection | 17+ | PDFs via `url` |
| NAPBHR Publications | `/publication-nhraps` | collection | 1+ | PDFs via `url` |
| Other Publications | `/publication-others` | collection | 18+ | PDFs via `url` |
| Tender Quotations | `/tender-quotations` | collection | 15+ | PDFs via `advertisementInfo.url` |
| Tender Results | `/tender-holders` | metadata_only | 4+ | (no file) |
| Trustee Registrations | `/trustee-registrations` | collection | 10 | PDFs via `file.url` |
| Trustee Amendments | `/trustee-amendments` | collection | 1+ | PDFs via `file.url` |
| Trustee Liquidations | `/trustee-liquidations` | collection | 3+ | PDFs via `file.url` |
| Trustee Monitorings | `/trustee-monitorings` | collection | 1+ | PDFs via `file.url` |
| Incorporation Review | `/review-incorporation-statuses` | collection | 4+ | PDFs via `file.url` |
| Whistleblower Archives | `/act-protection-archives` | collection | 3+ | PDFs via `pdfFile.url` |
| Whistleblower Newspaper Clip | `/act-protection-newspaper-clip` | single_type | 1 | PDF via `pdfFile.url` |
| Whistleblower Guideline | `/act-protection-guideline` | single_type | 1 | PDF via `pdfFile.url` |
| Whistleblower Brief | `/act-protection-brief` | single_type | 1 | PDF via `pdfFile.url` |
| Whistleblower Act Copy | `/act-protection-copy` | single_type | 1 | PDF via `pdfFile.url` |
| Latest News | `/latest-news` | metadata_only | 5+ | (no file) |

---

## Deduplication

Two-stage dedup per Scraper-Guide.md:

1. **Pre-fetch**: if `canonical_url` already in state DB → skip.
2. **Post-fetch**: if `sha256` already in DB → reuse existing `spaces_url`, skip upload.

---

## Scheduling (DigitalOcean Droplet)

Example systemd service at `/etc/systemd/system/polisi-bheuu-scraper.service`:

```ini
[Unit]
Description=BHEUU Scraper
After=network.target

[Service]
Type=oneshot
User=polisi
WorkingDirectory=/opt/polisigpt/bheuu-scraper
EnvironmentFile=/opt/polisigpt/.env
ExecStart=/opt/polisigpt/venv/bin/python3 -m bheuu_scraper.cli \
    --site-config configs/bheuu.yaml \
    --db-path /opt/polisigpt/.cache/bheuu_state.db \
    --manifest-dir /opt/polisigpt/data/manifests/bheuu
StandardOutput=append:/opt/polisigpt/logs/bheuu-scraper.log
StandardError=append:/opt/polisigpt/logs/bheuu-scraper.log
TimeoutStartSec=600
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
```

Cron trigger (every 3 days at 01:00 UTC):

```
0 1 */3 * * systemctl start polisi-bheuu-scraper.service
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `failed_count > 0` | Strapi returned error / file download failed | Check logs for `file_fetch_error`; verify URL at strapi.bheuu.gov.my |
| `missing_file_url` warnings | Strapi record has no file attachment | Normal for new draft records; check if `isPublish=false` |
| `skip_disallowed_host` warnings | File URL on unexpected host | Update `allowed_hosts` in `bheuu.yaml` |
| All records skipped | `canonical_url` already in state DB | Expected on incremental runs; use `--since` to control |
| `boto3` not installed | Missing dependency | `pip3 install boto3` |
| Strapi returns 404 for endpoint | Endpoint name changed | Check JS bundles at `www.bheuu.gov.my/_nuxt/` for updated paths |

---

## Running tests

```bash
python3 -m pytest tests/ -v
```

84 tests cover: URL normalization, date parsing, Strapi field extraction,
SQLite state dedup, and full pipeline scenarios (collection, single_type,
metadata_only, --since filtering, sha256 dedup).
