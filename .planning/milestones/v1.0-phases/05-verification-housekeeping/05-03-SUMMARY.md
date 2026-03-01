---
phase: 05-verification-housekeeping
plan: "03"
subsystem: api

tags: [python, psycopg, openai, embeddings, retrieval, testing, degradation]

# Dependency graph
requires:
  - phase: 05-verification-housekeeping
    provides: "05-02 added 429 fallbacks; 05-VERIFICATION.md identified missing empty-embedding guard in PostgresRetriever.retrieve()"
provides:
  - "Empty-embedding guard 'if not embedding: return []' in PostgresRetriever.retrieve() before psycopg.connect block"
  - "Unit test confirming OpenAI-429 degradation chain: embed() returns [] → retrieve() returns [] → no DB connection"
  - "8/8 must-haves verified in 05-VERIFICATION.md — all Phase 5 gaps closed"
affects: ["future phases using PostgresRetriever", "api reliability"]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Guard pattern: early return on empty embedding before DB call to prevent invalid pgvector literal"]

key-files:
  created: []
  modified:
    - api/src/polisi_api/chat/retrieval.py
    - api/tests/test_chat_service.py
    - .planning/phases/05-verification-housekeeping/05-VERIFICATION.md

key-decisions:
  - "PostgresRetriever.retrieve() guards against empty embedding with 'if not embedding: return []' before the psycopg.connect block, closing the OpenAI-429 degradation chain"

patterns-established:
  - "Embedding guard pattern: always check 'if not embedding: return []' before passing to _vector_literal() / DB query"

requirements-completed: []

# Metrics
duration: 3min
completed: 2026-03-01
---

# Phase 05 Plan 03: Gap Closure — Empty-Embedding Guard Summary

**Two-line guard 'if not embedding: return []' added to PostgresRetriever.retrieve() before psycopg.connect, closing the OpenAI-429 degradation chain and raising verification score from 7/8 to 8/8**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-01T03:10:22Z
- **Completed:** 2026-03-01T03:13:28Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments
- Added `if not embedding: return []` guard in `PostgresRetriever.retrieve()` at line 71, immediately after `embed()` and before `psycopg.connect` block — preventing invalid `"[]"` pgvector literal from reaching the DB
- Added `test_retrieve_returns_empty_list_when_embed_returns_empty` unit test with `EmptyEmbeddingClient` stub confirming the early return fires with no DB connection needed
- Updated `05-VERIFICATION.md` status from `gaps_found` (7/8) to `verified` (8/8); gap entry changed from `partial` to `closed`; full degradation chain now verified end-to-end

## Task Commits

Each task was committed atomically:

1. **Task 1: Add empty-embedding guard to PostgresRetriever.retrieve() and add unit test** - `74f9435` (fix)

**Plan metadata:** (included in final docs commit)

## Files Created/Modified
- `api/src/polisi_api/chat/retrieval.py` - Added `if not embedding: return []` guard at line 71 in `PostgresRetriever.retrieve()`
- `api/tests/test_chat_service.py` - Added `EmptyEmbeddingClient` dataclass and `test_retrieve_returns_empty_list_when_embed_returns_empty` test; imported `PostgresRetriever`
- `.planning/phases/05-verification-housekeeping/05-VERIFICATION.md` - Updated status to `verified`, score to `8/8`, Truth 6 to `VERIFIED`, gap to `closed`, artifact table entry to `VERIFIED`, key link entry to `VERIFIED`, gaps summary section updated

## Decisions Made
- Guard positioned as first operation after `embed()` call — this is the minimal change that restores the intended degradation chain without touching any other logic in the method
- `EmptyEmbeddingClient` is a plain `@dataclass` (not subclassing `OpenAIEmbeddingClient`) because `PostgresRetriever.__init__` accepts any structural embedding client; no inheritance needed

## Deviations from Plan

None — plan executed exactly as written. The two edits (retrieval.py guard + test_chat_service.py additions) matched the plan specifications line-for-line.

## Issues Encountered

None. The new test passed on the first run. The pre-existing `test_current_user_dependency_rejects_missing_or_invalid_tokens` failure (missing `public.conversations` table in test environment) remained unchanged, confirming no regressions.

**Test suite results:**
- Pre-05-03: 5/6 passed
- Post-05-03: 6/7 passed (new test added, new test passes, pre-existing failure unchanged)

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

All Phase 5 gaps closed. All 8/8 must-haves verified. v1.0 milestone housekeeping complete:
- REQUIREMENTS.md has all 18 v1 requirement checkboxes ticked
- Phase 2 and Phase 3 VERIFICATION.md files written
- Anthropic 429 fallback verified
- OpenAI 429 degradation chain fully closed
- Both .env.example files restored

No blockers. Project is in full verified state for v1.0 milestone.

## Self-Check: PASSED

| Check | Result |
|-------|--------|
| `api/src/polisi_api/chat/retrieval.py` exists | FOUND |
| `api/tests/test_chat_service.py` exists | FOUND |
| `.planning/phases/05-verification-housekeeping/05-03-SUMMARY.md` exists | FOUND |
| `.planning/phases/05-verification-housekeeping/05-VERIFICATION.md` exists | FOUND |
| Commit `74f9435` exists in git log | FOUND |
| Guard `if not embedding:` at line 71 in retrieval.py | FOUND |
| Test function `test_retrieve_returns_empty_list_when_embed_returns_empty` at line 167 in test_chat_service.py | FOUND |

---
*Phase: 05-verification-housekeeping*
*Completed: 2026-03-01*
