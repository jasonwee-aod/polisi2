# MOH Scraper – Operator Runbook

Scraper for **www.moh.gov.my** (Joomla 4 CMS).
Collects public documents (media statements, speeches, circulars, bulletins)
and archives originals to DigitalOcean Spaces.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.9+ | System Python 3.9.6 works |
| DigitalOcean Spaces | For full runs; not needed for `--dry-run` |
| pip3 | Or `pip` pointing to Python 3.9+ |

---

## Setup

```bash
cd moh-scraper

# Install dependencies
pip3 install -e ".[dev]"

# Copy and fill in credentials
cp .env.example .env
# Edit .env and set DO_SPACES_KEY, DO_SPACES_SECRET, DO_SPACES_BUCKET etc.
source .env
```

---

## Running

### Dry run (no uploads, no state written)

```bash
moh-scraper --dry-run
```

### Smoke test – 2 listing pages per section

```bash
moh-scraper --dry-run --max-pages 2
```

### Incremental – only articles from 2025 onwards

```bash
moh-scraper --since 2025-01-01
```

### Full run

```bash
moh-scraper --site-config configs/moh.yaml
```

### Full run with custom paths

```bash
moh-scraper \
  --site-config configs/moh.yaml \
  --db-path /opt/polisigpt/state/moh.db \
  --manifest-dir /opt/polisigpt/manifests/moh \
  --log-level INFO
```

---

## Output Files

| File | Description |
|---|---|
| `data/manifests/moh/records.jsonl` | One JSON record per archived document |
| `data/manifests/moh/crawl_runs.jsonl` | One JSON entry per crawl run with summary stats |
| `data/state.db` | SQLite dedup state (canonical URL + sha256) |

---

## Records Schema

See `Scraper-Guide.md` for the full schema. Key fields:

```json
{
  "record_id": "...",
  "source_url": "https://www.moh.gov.my/en/media-kkm/media-statement/2026?start=0",
  "canonical_url": "https://www.moh.gov.my/en/media-kkm/media-statement/2026/slug",
  "title": "Kenyataan Media ...",
  "published_at": "2026-02-23",
  "agency": "Ministry of Health Malaysia (Kementerian Kesihatan Malaysia)",
  "doc_type": "press_release",
  "content_type": "text/html",
  "language": "ms",
  "sha256": "...",
  "spaces_bucket": "your-bucket",
  "spaces_path": "gov-docs/moh/raw/2026/02/23/abc123_slug.html",
  "spaces_url": "https://your-bucket.sgp1.digitaloceanspaces.com/...",
  "fetched_at": "2026-02-23T10:00:00Z",
  "parser_version": "v1"
}
```

---

## Sections Scraped

| Section | URL pattern | `doc_type` | Notes |
|---|---|---|---|
| Media Statements | `/en/media-kkm/media-statement/{year}?start=N` | `press_release` | Years 2018–2026 |
| Speech Texts | `/en/media-kkm/speech-text?start=N` | `speech` | |
| Circulars | `/en/publications-and-reports/circulars?start=N` | `notice` | |
| Bulletins | `/en/publications-and-reports/bulletins-reference/bulletins?start=N` | `report` | |

### Sections not yet implemented

- **Annual Reports** – Uses SP Page Builder image-box layout, not standard Joomla table.
  Needs custom extractor or Playwright fallback.
- **Policies & Guidelines** – Multi-level hub structure. Needs mapping.

---

## Scheduling on DigitalOcean Droplet

### systemd service

```ini
# /etc/systemd/system/moh-scraper.service
[Unit]
Description=MOH Scraper
After=network-online.target

[Service]
Type=oneshot
User=polisi
WorkingDirectory=/opt/polisigpt/moh-scraper
EnvironmentFile=/opt/polisigpt/.env
ExecStart=/opt/polisigpt/.venv/bin/moh-scraper \
    --site-config configs/moh.yaml \
    --db-path /opt/polisigpt/state/moh.db \
    --manifest-dir /opt/polisigpt/manifests/moh \
    --since 2020-01-01
StandardOutput=append:/opt/polisigpt/logs/moh-scraper.log
StandardError=append:/opt/polisigpt/logs/moh-scraper.log
TimeoutStartSec=3600
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable moh-scraper
```

### cron (every 3 days at 02:00 UTC)

```cron
0 2 */3 * * systemctl start moh-scraper
```

---

## Tests

```bash
# Run all tests
python3 -m pytest tests/ -v

# Run with coverage
python3 -m pytest tests/ --cov=src/moh_scraper --cov-report=term-missing
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ValueError: policy: host not in allowlist` | URL from external domain | Add host to `allowed_hosts` in `configs/moh.yaml` if legitimate |
| Empty `records.jsonl` after dry run | Listing selectors not matching | Fetch page manually; check if Joomla table HTML changed |
| `ModuleNotFoundError: moh_scraper` | Package not installed | Run `pip3 install -e ".[dev]"` from `moh-scraper/` |
| 429 rate limiting | Too many requests | Increase `--request-delay` (default 1.5s) |
| `CloudFront` / `403` errors | Cloudflare WAF blocking | Wait and retry; if persistent, try Playwright fallback |
| Date parsing `""` for a section | Site changed date format | Update `parse_moh_date()` in `extractor.py` |

---

## Adding More Sections

1. Verify the URL structure manually (check if it uses standard Joomla category table).
2. Add a new entry to `configs/moh.yaml` with `listing_url`, `doc_type`, `language`.
3. Test with `--dry-run --max-pages 1`.
4. Add a regression fixture to `tests/fixtures/` and a test case.
