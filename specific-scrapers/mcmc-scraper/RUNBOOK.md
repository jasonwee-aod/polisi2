# MCMC Scraper – Operator Runbook

Scraper for **mcmc.gov.my** (Malaysian Communications and Multimedia Commission).

Collects: Press Releases, Announcements, Publications, Reports, Guidelines,
Statistics, Annual Reports, Research Reports.

Archives raw HTML and PDF originals to **DigitalOcean Spaces**.

---

## Setup

### 1. Install dependencies

```bash
cd mcmc-scraper
pip3 install -e ".[dev]"
```

> If `pip install -e .` fails on older pip, install manually:
> ```bash
> pip3 install requests beautifulsoup4 lxml python-dateutil boto3 tenacity pyyaml click
> pip3 install pytest pytest-cov   # for tests
> ```

### 2. Configure credentials

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

```dotenv
DO_SPACES_KEY=your-access-key
DO_SPACES_SECRET=your-secret-key
DO_SPACES_BUCKET=your-space-name
DO_SPACES_REGION=sgp1
DO_SPACES_ENDPOINT=https://sgp1.digitaloceanspaces.com
```

Load into your shell session:
```bash
export $(grep -v '^#' .env | xargs)
```

---

## Running the scraper

### Dry run (no upload, no state write)
```bash
python3 -m mcmc_scraper.cli --dry-run --max-pages 2
```

### Full run
```bash
python3 -m mcmc_scraper.cli --site-config configs/mcmc.yaml
```

Or if installed as a CLI entry point:
```bash
mcmc-scraper --site-config configs/mcmc.yaml
```

### Incremental run (since date)
```bash
mcmc-scraper --since 2025-01-01
```

### Limit pages for smoke test
```bash
mcmc-scraper --dry-run --max-pages 3
```

### Debug logging
```bash
mcmc-scraper --dry-run --log-level DEBUG --max-pages 1
```

---

## CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--site-config` | `configs/mcmc.yaml` | Path to site config YAML |
| `--since YYYY-MM-DD` | — | Skip articles before this date |
| `--max-pages N` | 0 (unlimited) | Max listing pages per section |
| `--dry-run` | off | No upload, no state write |
| `--db-path` | `data/state.db` | SQLite state file path |
| `--manifest-dir` | `data/manifests/mcmc` | Output directory |
| `--log-level` | `INFO` | DEBUG / INFO / WARNING / ERROR |
| `--request-delay` | `1.5` | Seconds between HTTP requests |

---

## Output files

```
data/
  state.db                          SQLite dedup state
  manifests/mcmc/
    records.jsonl                   One JSON record per scraped document
    crawl_runs.jsonl                One JSON object per crawl run
```

### records.jsonl schema

```json
{
  "record_id": "abc123-uuid",
  "source_url": "https://mcmc.gov.my/en/media/press-releases?page=1",
  "canonical_url": "https://mcmc.gov.my/en/media/press-releases/spectrum-2026",
  "title": "MCMC Statement on Spectrum Allocation 2026",
  "published_at": "2026-03-03",
  "agency": "Malaysian Communications and Multimedia Commission",
  "doc_type": "press_release",
  "content_type": "text/html",
  "language": "en",
  "sha256": "hexdigest",
  "spaces_bucket": "your-space-name",
  "spaces_path": "gov-docs/mcmc/raw/2026/03/04/abc123_spectrum-2026.html",
  "spaces_url": "https://your-space-name.sgp1.digitaloceanspaces.com/gov-docs/mcmc/raw/2026/03/04/abc123_spectrum-2026.html",
  "http_etag": "\"abc\"",
  "http_last_modified": "Mon, 03 Mar 2026 09:00:00 GMT",
  "fetched_at": "2026-03-04T00:00:00Z",
  "crawl_run_id": "2026-03-04-mcmc",
  "parser_version": "v1"
}
```

---

## Running tests

```bash
python3 -m pytest tests/ -v
```

Expected output: all tests pass (no live network calls in tests).

---

## Site structure reference

| Section | URL | Archetype | Pagination |
|---------|-----|-----------|------------|
| Press Releases | `/en/media/press-releases` | article_list | `?page=N` |
| Announcements | `/en/media/announcements` | article_list | `?page=N` |
| Press Clippings | `/en/media/press-clippings` | article_list | `?page=N` |
| Publications | `/en/resources/publications` | media_box | `?page=N` |
| Reports | `/en/resources/reports` | media_box | `?page=N` |
| Guidelines | `/en/resources/guidelines` | media_box | `?page=N` |
| Statistics | `/en/resources/statistics` | media_box | `?page=N` |
| Annual Reports | `/en/about-us/annual-reports` | media_box | `?page=N` |
| Research Reports | `/en/resources/research` | media_box | `?page=N` |

- **No sitemap.xml available** on mcmc.gov.my.
- CMS: **Kentico** (ASP.NET), static HTML (no JavaScript required).
- PDF assets are hosted at `www.mcmc.gov.my` – included in the host allowlist.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `policy: host not in allowlist` | PDF URL on external domain | Add host to `allowed_hosts` in `configs/mcmc.yaml` |
| `0 items extracted` on listing | Selector changed after site redesign | Inspect live HTML and update `extractor.py` |
| Records all skipped | URL already in state.db | Delete `data/state.db` to reset, or use `--since` to refetch |
| Upload fails (ClientError) | Invalid Spaces credentials | Check `DO_SPACES_*` env vars |
| Cloudflare 403 | WAF challenge | Increase `--request-delay`; check User-Agent |

---

## Systemd deployment (DigitalOcean Droplet)

Create `/etc/systemd/system/mcmc-scraper.service`:

```ini
[Unit]
Description=MCMC scraper – archives gov docs to Spaces
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=polisigpt
EnvironmentFile=/opt/polisigpt/.env
WorkingDirectory=/opt/polisigpt/mcmc-scraper
ExecStart=/opt/polisigpt/venv/bin/mcmc-scraper \
    --site-config configs/mcmc.yaml \
    --db-path /opt/polisigpt/data/mcmc_state.db \
    --manifest-dir /opt/polisigpt/data/manifests/mcmc \
    --log-level INFO
StandardOutput=append:/opt/polisigpt/logs/mcmc-scraper.log
StandardError=append:/opt/polisigpt/logs/mcmc-scraper.log
TimeoutStartSec=3600
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target
```

Schedule with cron (every 3 days at 02:00 UTC):
```
0 2 */3 * * systemctl start mcmc-scraper.service
```
