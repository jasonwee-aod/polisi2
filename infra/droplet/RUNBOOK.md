# PolisiGPT Droplet Runbook (Phase 2)

This runbook covers setup, scraper-to-indexer handoff, first full indexing, BM/EN retrieval smoke checks, and incremental rerun validation on a DigitalOcean Droplet.

## 1. Prerequisites

- Ubuntu Droplet with sudo access
- Project repository cloned to `/opt/polisigpt/repo`
- DigitalOcean Spaces bucket created
- Supabase project created and schema migration access available
- OpenAI API key created for embeddings

Required secrets in `/opt/polisigpt/.env`:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_DB_URL`
- `DO_SPACES_KEY`
- `DO_SPACES_SECRET`
- `DO_SPACES_BUCKET`
- `DO_SPACES_REGION`
- `DO_SPACES_ENDPOINT`
- `OPENAI_API_KEY`

## 2. Bootstrap Runtime

```bash
cd /opt/polisigpt/repo
bash infra/droplet/setup_runtime.sh
bash infra/droplet/install_playwright.sh
```

Install services:

```bash
sudo cp infra/droplet/systemd/polisi-scraper.service /etc/systemd/system/
sudo cp infra/droplet/systemd/polisi-indexer-placeholder.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable polisi-scraper.service polisi-indexer-placeholder.service
```

## 3. Database Migration

Run the Phase 1 and Phase 2 schema migrations in Supabase SQL editor or CI migration pipeline:

- `supabase/migrations/20260228_01_phase1_schema.sql`
- `supabase/migrations/20260228_02_phase2_documents_chunks.sql`

## 4. Preflight Validation

```bash
cd /opt/polisigpt/repo
/opt/polisigpt/.venv/bin/python scraper/scripts/preflight_check.py --components all
```

For indexer-only checks before a live run:

```bash
/opt/polisigpt/.venv/bin/python scraper/scripts/preflight_check.py --components indexer --dry-run
```

## 5. Manual Scraper and Indexer Runs

Dry smoke validation:

```bash
cd /opt/polisigpt/repo
/opt/polisigpt/.venv/bin/python scraper/scripts/smoke_crawl.py --sites mof,moe,jpa,moh,dosm --max-docs 1 --dry-run
```

Manual production-equivalent run:

```bash
cd /opt/polisigpt/repo
PYTHONPATH=scraper/src /opt/polisigpt/.venv/bin/python -m polisi_scraper.runner --sites mof,moe,jpa,moh,dosm --max-docs 200
```

First full index (**Phase 2**):

```bash
cd /opt/polisigpt/repo
/opt/polisigpt/.venv/bin/python -m polisi_scraper.indexer.runner --mode full --max-items 200
```

Incremental rerun after a later scrape:

```bash
cd /opt/polisigpt/repo
/opt/polisigpt/.venv/bin/python -m polisi_scraper.indexer.runner --mode incremental --max-items 200
```

BM smoke query:

```bash
cd /opt/polisigpt/repo/scraper
/opt/polisigpt/.venv/bin/python scripts/query_smoke.py --language bm --limit 3
```

English smoke query:

```bash
cd /opt/polisigpt/repo/scraper
/opt/polisigpt/.venv/bin/python scripts/query_smoke.py --language en --limit 3
```

## 6. Schedule Every 3 Days

Install cron schedule (runs at `0 1 */3 * *` = **9:00 AM MYT** every 3 days):

```bash
crontab infra/droplet/cron/scraper_every_3_days.cron
crontab -l
```

Timezone note:

- Cron expression uses UTC on droplet by default (`01:00 UTC`).
- `01:00 UTC` equals **9:00 AM MYT (UTC+8)**.

## 7. Service and Log Operations

Run once via systemd:

```bash
sudo systemctl start polisi-scraper.service
sudo systemctl status polisi-scraper.service
sudo systemctl status polisi-indexer-placeholder.service
```

View logs:

```bash
tail -n 200 /opt/polisigpt/logs/scraper.log
tail -n 200 /opt/polisigpt/logs/indexer.log
```

Service handoff:

- `polisi-scraper.service` runs preflight, smoke crawl, then the full scraper.
- `ExecStartPost` triggers `polisi-indexer-placeholder.service`.
- `polisi-indexer-placeholder.service` now runs the real `polisi_scraper.indexer.runner` entrypoint in incremental mode.

## 8. Rollback / Recovery

- Disable schedule temporarily: `crontab -r` (or edit and remove scraper line only)
- Stop manual service runs: `sudo systemctl stop polisi-scraper.service`
- Stop or rerun indexer service manually: `sudo systemctl stop polisi-indexer-placeholder.service`
- Re-run setup after dependency drift: `bash infra/droplet/setup_runtime.sh`
- Validate environment quickly: `python scraper/scripts/preflight_check.py --components indexer --dry-run`

## 9. Acceptance Checklist

### Phase 2

- [ ] Runtime scripts complete without errors (`setup_runtime.sh`, `install_playwright.sh`)
- [ ] Preflight passes with real secrets for scraper and indexer (`--components all`)
- [ ] First full index runs with `text-embedding-3-large` and writes chunk rows into `public.documents`
- [ ] Bahasa Malaysia query smoke returns indexed chunk metadata from `scripts/query_smoke.py --language bm`
- [ ] English query smoke returns indexed chunk metadata from `scripts/query_smoke.py --language en`
- [ ] Incremental rerun processes only new or changed files while unchanged versions are skipped
- [ ] Cron installed from `infra/droplet/cron/scraper_every_3_days.cron`
- [ ] Cron expression is `0 1 */3 * *`
- [ ] Schedule is documented as **9:00 AM MYT**
- [ ] Logs confirm scraper completion triggers the indexer service without manual intervention
