# PolisiGPT Droplet Runbook (Phase 1)

This runbook covers setup, manual execution, and scheduled operations for the scraper runtime on a DigitalOcean Droplet.

## 1. Prerequisites

- Ubuntu Droplet with sudo access
- Project repository cloned to `/opt/polisigpt/repo`
- DigitalOcean Spaces bucket created
- Supabase project created and schema migration access available

Required secrets in `/opt/polisigpt/.env`:

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `DO_SPACES_KEY`
- `DO_SPACES_SECRET`
- `DO_SPACES_BUCKET`
- `DO_SPACES_REGION`
- `DO_SPACES_ENDPOINT`

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
```

## 3. Database Migration

Run the Phase 1 schema migration in Supabase SQL editor or CI migration pipeline:

- `supabase/migrations/20260228_01_phase1_schema.sql`

## 4. Preflight Validation

```bash
cd /opt/polisigpt/repo
/opt/polisigpt/.venv/bin/python scraper/scripts/preflight_check.py
```

For partial checks before secrets are in place:

```bash
/opt/polisigpt/.venv/bin/python scraper/scripts/preflight_check.py --dry-run
```

## 5. Manual Scraper Run

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
```

View logs:

```bash
tail -n 200 /opt/polisigpt/logs/scraper.log
tail -n 200 /opt/polisigpt/logs/preflight.log
```

## 8. Rollback / Recovery

- Disable schedule temporarily: `crontab -r` (or edit and remove scraper line only)
- Stop manual service runs: `sudo systemctl stop polisi-scraper.service`
- Re-run setup after dependency drift: `bash infra/droplet/setup_runtime.sh`
- Validate environment quickly: `python scraper/scripts/preflight_check.py --dry-run`

## 9. Acceptance Checklist

### INFRA-01

- [ ] Runtime scripts complete without errors (`setup_runtime.sh`, `install_playwright.sh`)
- [ ] Preflight passes with real secrets
- [ ] Manual run command executes runner successfully

### INFRA-02

- [ ] Cron installed from `infra/droplet/cron/scraper_every_3_days.cron`
- [ ] Cron expression is `0 1 */3 * *`
- [ ] Schedule is documented as **9:00 AM MYT**
- [ ] Logs confirm automated runs without manual intervention
