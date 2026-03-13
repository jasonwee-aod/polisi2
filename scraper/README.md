# Polisi Scraper

Core ingestion and indexing pipeline for PolisiGPT. The scraper crawls Malaysian government sources, deduplicates by SHA256, and stores files in DigitalOcean Spaces under the key pattern `gov-my/{agency}/{year-month}/{filename}` (or `polisi/gov-my/{agency}/{year-month}/{filename}` when a `polisi/` bucket prefix is configured). The indexer reads those raw objects, parses them into chunks, embeds them with OpenAI `text-embedding-3-large`, and writes searchable rows into Supabase. Both the scraper and indexer run on a DigitalOcean Droplet via systemd services and a cron schedule — see `infra/droplet/RUNBOOK.md` for full deployment steps.

## Quick Start

1. Create a Python 3.11+ virtual environment.
2. Install dependencies:
   ```bash
   pip install -e .
   ```
3. Copy environment template and fill credentials:
   ```bash
   cp .env.example .env
   ```
4. Run tests:
   ```bash
   python -m pytest
   ```

## Required Environment Variables

- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `DO_SPACES_KEY`
- `DO_SPACES_SECRET`
- `DO_SPACES_BUCKET`
- `DO_SPACES_REGION`
- `DO_SPACES_ENDPOINT`

## Indexer Environment Variables

- `OPENAI_API_KEY`
- `SUPABASE_DB_URL`

## Optional Environment Variables

- `LLAMA_CLOUD_API_KEY` — enables LlamaParse for higher-quality PDF text extraction; falls back to `pypdf` if unset or if the API call fails.

## Optional Runtime Knobs

- `INDEXER_SPACES_PREFIX` — object key prefix to list from Spaces (default: `gov-my/`)
- `INDEXER_BATCH_SIZE`
- `INDEXER_MAX_ITEMS_PER_RUN`
- `INDEXER_CHUNK_SIZE`
- `INDEXER_CHUNK_OVERLAP`
- `INDEXER_SIMILARITY_LIMIT`

See `.env.example` for the full runtime contract. Indexer startup should use `ScraperSettings.from_env(..., require_indexer=True)` so missing embedding or database credentials fail fast.

## Scraper Commands

Run a smoke crawl (dry-run, no writes):

```bash
python scripts/smoke_crawl.py --sites mof,moe,jpa,moh,dosm --max-docs 1 --dry-run
```

Run the scraper directly:

```bash
polisi-scraper --sites mof,moe,jpa,moh,dosm --max-docs 200
```

## Indexer Commands

Run a bounded indexer pass:

```bash
polisi-indexer --mode incremental --max-items 10
```

Inspect the configured runtime without embedding or persistence work:

```bash
polisi-indexer --mode incremental --dry-run --max-items 2
polisi-indexer --mode full --dry-run --max-items 2
```

Run a BM or English retrieval smoke query after indexing:

```bash
python scripts/query_smoke.py --language bm
python scripts/query_smoke.py --language en
```

Validate the indexer runtime before a droplet run:

```bash
python scripts/preflight_check.py --components indexer --dry-run
```

## Deployment on DO Droplet

The scraper and indexer are deployed on a DigitalOcean Droplet as systemd services:

- `polisi-scraper.service` — runs preflight, smoke crawl, then the full scraper.
- `polisi-indexer-placeholder.service` — triggered via `ExecStartPost` after the scraper completes; runs the indexer in incremental mode.

A cron job at `0 1 */3 * *` (01:00 UTC = **9:00 AM MYT**) triggers the full scraper-to-indexer pipeline every three days.

See `infra/droplet/RUNBOOK.md` for full provisioning, migration, and operational procedures.
