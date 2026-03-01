# Phase 2 / Plan 03: User Setup Required

**Generated:** 2026-02-28
**Phase:** 02-indexing-pipeline
**Status:** Incomplete

Complete these items for the embedding and Supabase persistence path to function. Claude automated everything possible; these items require dashboard access.

## Environment Variables

| Status | Variable | Source | Add to |
|--------|----------|--------|--------|
| [ ] | `OPENAI_API_KEY` | OpenAI dashboard → API keys → Create or copy project key | `scraper/.env` or droplet env file |
| [ ] | `SUPABASE_DB_URL` | Supabase dashboard → Project Settings → Database → Connection string | `scraper/.env` or droplet env file |

## Dashboard Configuration

- [ ] **Confirm pgvector-enabled database access**
  - Location: Supabase dashboard → Project Settings → Database
  - Set to: connection string must allow direct Postgres access from the droplet/runtime
  - Notes: the indexer runner writes chunk rows directly and query smoke calls `public.match_documents`

- [ ] **Create or confirm OpenAI API key for embeddings**
  - Location: OpenAI dashboard → API keys
  - Set to: a key authorized for `text-embedding-3-large`
  - Notes: store the key only in the runtime env file, not in source control

## Verification

After completing setup, verify with:

```bash
cd scraper
../.venv313/bin/python -m polisi_scraper.indexer.runner --dry-run --max-items 1
../.venv313/bin/python scripts/query_smoke.py --language bm --limit 1
```

Expected results:
- Dry run prints the indexer configuration without missing-env errors.
- Query smoke connects with the configured credentials and returns JSON rows once chunks have been indexed.

---

**Once all items complete:** Mark status as "Complete" at the top of this file.
