---
phase: 02-indexing-pipeline
plan: 03
subsystem: database
tags: [indexing, embeddings, supabase, pgvector, openai]
requires:
  - phase: 02-01
    provides: "PendingIndexItem and version-token contracts"
  - phase: 02-02
    provides: "ParsedDocument output and chunk metadata locators"
provides:
  - "Supabase migration for chunk-row document persistence"
  - "OpenAI embedding client and in-memory/Postgres documents store"
  - "Runnable indexer pipeline, CLI entrypoint, and retrieval smoke helper"
affects: [phase-02-ops, retrieval, citations, api]
tech-stack:
  added: [openai, psycopg, pgvector]
  patterns: ["documents-table-as-fingerprint-store", "fakeable-indexer-boundaries", "runner-dry-run-before-live-run"]
key-files:
  created:
    - supabase/migrations/20260228_02_phase2_documents_chunks.sql
    - scraper/src/polisi_scraper/indexer/embeddings.py
    - scraper/src/polisi_scraper/indexer/store.py
    - scraper/src/polisi_scraper/indexer/pipeline.py
    - scraper/src/polisi_scraper/indexer/runner.py
    - scraper/scripts/query_smoke.py
    - scraper/tests/test_indexer_pipeline.py
    - .planning/phases/02-indexing-pipeline/02-03-USER-SETUP.md
  modified:
    - scraper/README.md
key-decisions:
  - "Chunk rows themselves act as the successful-index fingerprint by keying on storage_path + version_token + chunk_index."
  - "DocumentsStore supports both in-memory and Postgres backends so tests stay deterministic while production still writes to Supabase."
  - "The embedding client is hard-pinned to text-embedding-3-large to match the multilingual retrieval decision."
patterns-established:
  - "Runner dry runs should validate config before live indexing or smoke queries."
  - "Smoke queries should call one helper path that embeds the query and then uses store.match_documents."
requirements-completed: [INDX-01, INDX-02, INDX-03, INDX-04]
duration: 7min
completed: 2026-02-28
---

# Phase 2 / Plan 03 Summary

**Phase 2 now has a runnable parse-to-embed-to-persist pipeline, chunk-row Supabase schema support, and BM/EN smoke-query coverage for stored vectors.**

## Performance
- **Duration:** 7 min
- **Started:** 2026-02-28T21:29:00+08:00
- **Completed:** 2026-02-28T21:35:35+08:00
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments
- Added a migration that supports multiple chunk rows per document version and exposes `public.match_documents`.
- Added the OpenAI embeddings client, chunk persistence store, in-memory/Postgres retrieval layer, and indexer pipeline orchestration.
- Added a runnable `polisi-indexer` CLI path, BM/EN retrieval smoke helper, and deterministic pipeline tests.

## Task Commits
1. **Task 1: Fix the documents schema for chunk-row storage and retrieval** - `36ffed1`
2. **Task 2: Implement embedding, persistence, and indexer runner wiring** - `54f950c`
3. **Task 3: Add BM/EN retrieval smoke tooling and pipeline regression tests** - `ed68ea2`

## Files Created/Modified
- `supabase/migrations/20260228_02_phase2_documents_chunks.sql` - removes one-row uniqueness and adds the chunk-row retrieval function.
- `scraper/src/polisi_scraper/indexer/embeddings.py` - wraps OpenAI embeddings with the required model pin.
- `scraper/src/polisi_scraper/indexer/store.py` - persists chunk rows and supports retrieval smoke checks in memory or Postgres.
- `scraper/src/polisi_scraper/indexer/pipeline.py` - orchestrates pending item fetch, parse, chunk, embed, and persist flow.
- `scraper/src/polisi_scraper/indexer/runner.py` - exposes the runnable `polisi-indexer` CLI and dry-run path.
- `scraper/scripts/query_smoke.py` - executes BM/EN retrieval smoke checks against stored vectors.
- `scraper/tests/test_indexer_pipeline.py` - covers schema assumptions, persistence flow, model pinning, and smoke-query behavior.
- `scraper/README.md` - documents bounded indexer runs and smoke query commands.
- `.planning/phases/02-indexing-pipeline/02-03-USER-SETUP.md` - captures the manual OpenAI and Supabase DB setup steps.

## Decisions Made
- Reused `public.documents` as both the retrieval corpus and the source of incremental fingerprint truth instead of adding a second state table.
- Kept the production path directly on Postgres while exposing in-memory behavior for tests so no live external services are needed during verification.

## Deviations from Plan
- None - plan executed exactly as written.

## Issues Encountered
- None.

## User Setup Required
**External services require manual configuration.** See `02-03-USER-SETUP.md` for:
- OpenAI API key setup
- Supabase direct Postgres connection string retrieval
- Post-setup dry-run and smoke-query verification commands

## Next Phase Readiness
- The final phase-2 wave only needs droplet runtime wiring, service handoff, and operator documentation.
- Once credentials are present, the pipeline can be exercised end-to-end with the shipped runner and smoke query path.

---
*Phase: 02-indexing-pipeline*
*Completed: 2026-02-28*
