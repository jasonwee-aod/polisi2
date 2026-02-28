---
phase: 04-fix-source-url-chain
plan: 01
subsystem: scraper, api, ui
tags: [boto3, pydantic, supabase, nextjs, s3-metadata, source-url, citations]

# Dependency graph
requires:
  - phase: 03-product
    provides: citation rendering pipeline, frontend chat components, API models
  - phase: 02-indexing-pipeline
    provides: SpacesUploader, runner.py, manifest reading S3 object metadata

provides:
  - SpacesUploader.upload_bytes with metadata parameter forwarded to S3 put_object
  - runner.py passes source_url as Spaces object metadata during upload
  - CitationRecord.source_url nullable (str | None) in API models and TypeScript types
  - CitationPanel renders anchor when source_url non-null; plain [N] span when null
  - Three committed smoke-fix commits (CORS NoDecode, async Supabase client, await call sites)

affects: [05-ops, future phases using citation links, live indexing runs]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "S3 object metadata used to propagate scraper-level source_url through pipeline"
    - "Nullable fields in Pydantic models and TypeScript types for graceful degradation"
    - "Conditional JSX rendering on nullable props without fallback message strings"

key-files:
  created: []
  modified:
    - scraper/src/polisi_scraper/core/spaces.py
    - scraper/src/polisi_scraper/runner.py
    - scraper/tests/test_dedup_and_state.py
    - api/src/polisi_api/models.py
    - api/src/polisi_api/chat/retrieval.py
    - web/lib/api/client.ts
    - web/components/chat/citation-panel.tsx
    - api/src/polisi_api/config.py
    - web/lib/supabase/server.ts
    - web/app/(app)/chat/[conversationId]/page.tsx
    - web/app/(app)/chat/page.tsx
    - web/app/(app)/layout.tsx
    - web/app/auth/page.tsx
    - web/app/page.tsx

key-decisions:
  - "source_url stored as S3 object Metadata dict key so manifest can read it back via obj.metadata.get('source_url')"
  - "runner.py passes metadata=None (not empty dict) when record.source_url is falsy — S3 Metadata values must be strings"
  - "CitationRecord.source_url = None by default (str | None = None) to avoid Pydantic validation errors on legacy rows"
  - "Citation fallback is plain [N] span with no anchor — no 'Source unavailable' message per user decision"
  - "Pre-existing test_current_user_dependency_rejects_missing_or_invalid_tokens failure is a known infrastructure issue (requires live Postgres at localhost:5432) not caused by this phase"

patterns-established:
  - "S3 metadata pattern: upload_bytes(data, key, content_type=None, metadata=None) with kwargs dict and conditional Metadata key"
  - "Nullable API field pattern: source_url: str | None = None in Pydantic, string | null in TypeScript"

requirements-completed: [INDX-03, API-02, FE-03]

# Metrics
duration: 2min
completed: 2026-03-01
---

# Phase 04 Plan 01: Fix source_url Chain Summary

**source_url data chain fixed end-to-end: SpacesUploader now stores original government document URL as S3 object metadata, runner.py passes it on upload, API models handle null gracefully, and CitationPanel renders plain [N] text instead of a broken link when source_url is null**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-28T17:50:44Z
- **Completed:** 2026-02-28T17:52:45Z
- **Tasks:** 3
- **Files modified:** 14 (3 smoke-fix files + 7 source-url chain files + 4 async call sites)

## Accomplishments

- Committed 3 pending smoke-fix commits (CORS NoDecode, async createServerSupabaseClient, await call sites)
- Fixed SpacesUploader.upload_bytes to accept and forward metadata dict to S3 put_object
- Fixed runner.py to pass {"source_url": record.source_url} when uploading documents
- Made CitationRecord.source_url and RetrievedChunk.source_url nullable in all API models
- Made CitationRecord.source_url nullable in TypeScript client type
- Added conditional render in CitationPanel: anchor when non-null, plain [index] span when null
- 18/18 scraper tests pass with updated FakeUploader signature

## Task Commits

Each task was committed atomically:

1. **Task 1a: CORS NoDecode fix** - `78303e0` (fix)
2. **Task 1b: async Supabase server client** - `4c9919b` (fix)
3. **Task 1c: await call sites** - `97c3836` (fix)
4. **Task 2: SpacesUploader metadata + runner.py source_url** - `ba2afc7` (fix)
5. **Task 3: nullable source_url in API models + CitationPanel fallback** - `df6d730` (fix)

## Files Created/Modified

- `scraper/src/polisi_scraper/core/spaces.py` - upload_bytes now accepts metadata param, passes to S3 put_object
- `scraper/src/polisi_scraper/runner.py` - passes {"source_url": record.source_url} metadata on upload
- `scraper/tests/test_dedup_and_state.py` - FakeUploader.upload_bytes updated with metadata keyword arg
- `api/src/polisi_api/models.py` - CitationRecord.source_url: str | None = None
- `api/src/polisi_api/chat/retrieval.py` - RetrievedChunk.source_url: str | None
- `web/lib/api/client.ts` - CitationRecord.source_url: string | null
- `web/components/chat/citation-panel.tsx` - conditional render on citation.source_url
- `api/src/polisi_api/config.py` - NoDecode annotation on api_allowed_origins (smoke fix)
- `web/lib/supabase/server.ts` - async createServerSupabaseClient with await cookies() (smoke fix)
- `web/app/(app)/chat/[conversationId]/page.tsx` - await createServerSupabaseClient() (smoke fix)
- `web/app/(app)/chat/page.tsx` - await createServerSupabaseClient() (smoke fix)
- `web/app/(app)/layout.tsx` - await createServerSupabaseClient() (smoke fix)
- `web/app/auth/page.tsx` - await createServerSupabaseClient() (smoke fix)
- `web/app/page.tsx` - await createServerSupabaseClient() (smoke fix)

## Decisions Made

- source_url stored as S3 Metadata dict so manifest can read it back via `obj.metadata.get("source_url")`
- runner.py passes `metadata=None` (not empty dict) when record.source_url is falsy — avoids empty string S3 metadata values
- CitationRecord.source_url defaults to `None` in Pydantic to prevent validation errors on legacy rows without source_url
- Citation fallback renders plain `[N]` span with no anchor — no "Source unavailable" message per explicit user decision
- `.env.example` deletions were not staged per plan instructions (intentional deletions left in working tree)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

One pre-existing test failure was observed but is unrelated to this phase: `test_current_user_dependency_rejects_missing_or_invalid_tokens` fails because it requires a live Postgres database at `localhost:5432/postgres` which is not available in this environment. The test was failing before this phase and is not caused by any changes here. The other 2 API contract tests pass correctly.

## User Setup Required

None - no external service configuration required. Live environment validation (sample re-index to confirm source_url non-null in Supabase rows) requires live DO Spaces + Supabase credentials in `scraper/.env` and must be done operationally.

## Next Phase Readiness

- Source URL data chain is fully fixed: new indexing runs will populate source_url in Supabase chunk rows
- Citation links will work for newly-indexed documents; legacy rows with null source_url degrade gracefully to plain [N] text
- A sample re-index of 2-3 documents with live credentials is recommended to validate end-to-end before full re-index
- CORS and Next.js 15 async issues are resolved, API and web app should be functional in a live deployment

---
*Phase: 04-fix-source-url-chain*
*Completed: 2026-03-01*

## Self-Check: PASSED

All required files exist and all task commits are verified in git history.
