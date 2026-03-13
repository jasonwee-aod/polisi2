# Quick Start (5 minutes)

## 1. Clone & Install

```bash
cd perpaduan-scraper
python -m pip install -e ".[dev]"
```

## 2. Test with Dry-Run

```bash
python -m src.main \
  --site-config configs/perpaduan.yaml \
  --max-pages 5 \
  --dry-run
```

Expected output:
```
============================================================
SCRAPE SUMMARY
============================================================
crawl_run_id        : 2026-03-09-perpaduan
discovered          : ~50
fetched             : ~50
uploaded            : 0
deduped             : 0
failed              : 0
records_written     : ~50
============================================================
```

Output files:
- `data/manifests/perpaduan/records.jsonl` — 50 records
- `data/manifests/perpaduan/crawl_runs.jsonl` — 1 run summary

## 3. Run Tests

```bash
pytest tests/ -v
```

## 4. Full Crawl (with Spaces)

Set environment variables first:

```bash
export DO_SPACES_BUCKET="your-bucket"
export DO_SPACES_KEY="your-key"
export DO_SPACES_SECRET="your-secret"
export DO_SPACES_REGION="sgp1"
```

Then run:

```bash
python -m src.main --site-config configs/perpaduan.yaml
```

## 5. Check Results

```bash
head -1 data/manifests/perpaduan/records.jsonl | jq .
tail -1 data/manifests/perpaduan/crawl_runs.jsonl | jq .
```

## Next Steps

- Read README.md for full documentation
- Read RUNBOOK.md for deployment to DigitalOcean Droplet
- Edit configs/perpaduan.yaml to adjust which sections to crawl
