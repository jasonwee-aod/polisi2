---
phase: 05-verification-housekeeping
plan: 02
subsystem: api
tags: [anthropic, openai, rate-limit, error-handling, env, developer-onboarding]

# Dependency graph
requires:
  - phase: 03-chat-ux
    provides: AnthropicTextGenerator.generate() and OpenAIEmbeddingClient.embed() implementations
  - phase: 04-fix-source-url-chain
    provides: ChatService, AssistantResponse, CitationRecord with source_url chain
provides:
  - 429 rate-limit fallback in AnthropicTextGenerator.generate() returning graceful string
  - 429 rate-limit fallback in OpenAIEmbeddingClient.embed() returning [] for graceful degradation
  - api/.env.example with all required API env var keys and placeholder values
  - web/.env.example with all required web env var keys and placeholder values
affects: [deployment, developer-onboarding]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Catch-specific-then-reraise: only catch the exact HTTP status (429) and reraise all others to preserve normal error surfaces"
    - "Protocol-level graceful degradation: embed() returning [] causes retrieve() to return [] which causes generate_reply() to use build_no_information_text() — no special code needed at the caller level"

key-files:
  created:
    - api/.env.example
    - web/.env.example
  modified:
    - api/src/polisi_api/chat/service.py
    - api/src/polisi_api/chat/retrieval.py

key-decisions:
  - "Anthropic 429 is caught at the generator level and converted to a fallback string so ChatService.generate_reply() produces a normal AssistantResponse — no HTTP 500 raised"
  - "OpenAI 429 in embed() returns [] so the existing retrieval path handles it as 'no results' — no new code path needed in PostgresRetriever or ChatService"
  - "Only status_code == 429 is caught in embed(); all other HTTPStatusError codes re-raise to surface as real errors"

patterns-established:
  - "Rate limit handling: catch at the lowest feasible layer, return a safe neutral value or message, let the caller's normal flow handle it"

requirements-completed: []

# Metrics
duration: 2min
completed: 2026-03-01
---

# Phase 05 Plan 02: Graceful 429 Fallbacks and .env.example Restoration Summary

**429 rate-limit handling added to Anthropic text generation and OpenAI embedding layers; api/.env.example and web/.env.example restored for developer onboarding**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-01T02:33:36Z
- **Completed:** 2026-03-01T02:35:18Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- `AnthropicTextGenerator.generate()` now catches `RateLimitError` and returns a graceful fallback string instead of propagating as HTTP 500
- `OpenAIEmbeddingClient.embed()` now catches `httpx.HTTPStatusError` with status_code 429 and returns `[]`, allowing `generate_reply()` to degrade via `build_no_information_text()` with no crash
- `api/.env.example` recreated with all required env vars: API runtime, Supabase, Anthropic, OpenAI, and retrieval tuning vars
- `web/.env.example` recreated with NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, NEXT_PUBLIC_API_BASE_URL
- All 5 existing API tests continue to pass after changes

## Task Commits

Each task was committed atomically:

1. **Task 1: Add 429 fallbacks in AnthropicTextGenerator and OpenAIEmbeddingClient** - `1e8fd9f` (fix)
2. **Task 2: Recreate api/.env.example and web/.env.example** - `15720e4` (chore)

## Files Created/Modified
- `api/src/polisi_api/chat/service.py` - Added `RateLimitError` import; wrapped `messages.create()` in try/except to return fallback string on Anthropic 429
- `api/src/polisi_api/chat/retrieval.py` - Wrapped `embed()` HTTP call in try/except; catches `httpx.HTTPStatusError` with status 429 and returns `[]`; all other HTTP errors still re-raise
- `api/.env.example` - Recreated with API_ENV, API_HOST, API_PORT, API_ALLOWED_ORIGINS, SUPABASE_URL, SUPABASE_DB_URL, SUPABASE_JWT_SECRET, ANTHROPIC_API_KEY, ANTHROPIC_MODEL, OPENAI_API_KEY, RETRIEVAL_LIMIT, RETRIEVAL_MIN_SIMILARITY, RETRIEVAL_WEAK_SIMILARITY
- `web/.env.example` - Recreated with NEXT_PUBLIC_SUPABASE_URL, NEXT_PUBLIC_SUPABASE_ANON_KEY, NEXT_PUBLIC_API_BASE_URL

## Decisions Made
- Only `RateLimitError` is caught in `generate()` — APIConnectionError, APITimeoutError, and other Anthropic errors still surface normally
- Only `status_code == 429` is caught in `embed()` — 401, 500, and other HTTP errors still re-raise so they are not silently swallowed
- The embed() degradation path does not require any new caller code: `[]` embedding propagates through PostgresRetriever.retrieve() returning `[]`, and ChatService.generate_reply() already handles empty retrieval via `build_no_information_text()`

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required beyond what was already needed.

## Next Phase Readiness
- Both 429 paths now degrade gracefully with no HTTP 500
- .env.example files restored for developer onboarding
- Phase 05 housekeeping complete

## Self-Check: PASSED

All created files confirmed present on disk. All task commits (1e8fd9f, 15720e4) confirmed in git log.

---
*Phase: 05-verification-housekeeping*
*Completed: 2026-03-01*
