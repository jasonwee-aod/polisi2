---
phase: 03-product
plan: 03
subsystem: api
tags: [rag, anthropic, retrieval, streaming, conversations]
requires:
  - phase: 03-01
    provides: "FastAPI app scaffold, server auth boundary, and typed chat/history DTOs"
provides:
  - "Grounded chat service with BM/EN detection and clarification/weak-support fallbacks"
  - "Authenticated streaming chat endpoint with conversation/message/citation persistence"
  - "Recent-first conversation list and exact-thread detail endpoints"
affects: [phase-03-product, frontend-chat, citations]
tech-stack:
  added: [anthropic-sdk, httpx, psycopg]
  patterns: ["repository-backed-chat-persistence", "ndjson-chat-stream", "retrieval-first-answer-modes"]
key-files:
  created:
    - api/src/polisi_api/chat/detector.py
    - api/src/polisi_api/chat/prompting.py
    - api/src/polisi_api/chat/retrieval.py
    - api/src/polisi_api/chat/repository.py
    - api/src/polisi_api/chat/service.py
    - api/src/polisi_api/dependencies.py
    - api/src/polisi_api/routes/chat.py
    - api/src/polisi_api/routes/conversations.py
    - api/tests/test_chat_service.py
    - api/tests/test_conversation_routes.py
  modified:
    - api/pyproject.toml
    - api/src/polisi_api/main.py
key-decisions:
  - "Chat streaming is delivered as NDJSON event envelopes so the Next.js client can consume progressive updates without a websocket."
  - "The chat service chooses among answer, clarification, limited-support, and no-information modes before persistence."
  - "Conversation history reuses the same repository layer as chat writes to keep sidebar resume behavior consistent."
patterns-established:
  - "Persist the user message before generation, then store the final assistant message and citations before emitting the authoritative completion event."
  - "Recent-first conversation listing should be driven by conversation updated_at, not creation order."
requirements-completed: [API-01, API-02, API-03, API-04]
duration: 4min
completed: 2026-02-28
---

# Phase 3 / Plan 03 Summary

**Retrieval-grounded chat backend with streamed NDJSON responses, persisted citations, and recent-first conversation history routes.**

## Performance
- **Duration:** 4 min
- **Started:** 2026-02-28T22:48:56+08:00
- **Completed:** 2026-02-28T22:52:29+08:00
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments
- Implemented the retrieval-first chat service that detects BM vs English and branches into clarification, weak-support, no-information, or cited-answer flows.
- Added the authenticated `/api/chat` streaming route backed by a repository that persists conversations, user messages, assistant messages, and citations.
- Exposed recent-first conversation list/detail endpoints for exact-thread resume behavior.

## Task Commits
1. **Task 1: Implement retrieval, language selection, and grounded answer prompting** - `eb043c8`
2. **Task 2: Add the streaming chat endpoint and message/citation persistence** - `bfb2661`
3. **Task 3: Expose conversation history routes for sidebar resume behavior** - `67da76f`

## Files Created/Modified
- `api/src/polisi_api/chat/detector.py` - identifies BM vs English and broad prompts that require clarification first.
- `api/src/polisi_api/chat/prompting.py` - builds grounded prompt packages plus clarification, weak-support, and no-information copy.
- `api/src/polisi_api/chat/retrieval.py` - embeds queries and calls `public.match_documents`.
- `api/src/polisi_api/chat/repository.py` - persists and hydrates conversations, messages, and citations.
- `api/src/polisi_api/chat/service.py` - orchestrates retrieval, prompting, answer mode selection, and persistence handoff.
- `api/src/polisi_api/dependencies.py` - wires repository, retriever, and generator dependencies for the routes.
- `api/src/polisi_api/routes/chat.py` - streams NDJSON chat events from the authenticated chat endpoint.
- `api/src/polisi_api/routes/conversations.py` - returns recent-first conversation summaries and thread detail.
- `api/src/polisi_api/main.py` - includes the concrete chat and conversation routers.
- `api/tests/test_chat_service.py` - covers answer modes plus streaming persistence.
- `api/tests/test_conversation_routes.py` - verifies recent-first ordering and thread hydration.

## Decisions Made
- Chose NDJSON envelopes instead of SSE for the chat stream so the frontend can parse incremental events with simple fetch-stream code and reuse the existing `StreamingEventEnvelope` schema.
- Kept the generator/retriever/repository seams explicit so tests can validate behavior without live Anthropic or Supabase traffic.

## Deviations from Plan
- None - plan executed exactly as written.

## Issues Encountered
- None.

## User Setup Required
External services still require manual configuration:
- Provide `OPENAI_API_KEY` for embeddings.
- Provide `ANTHROPIC_API_KEY` for answer generation.
- Provide `SUPABASE_DB_URL`, `SUPABASE_URL`, and signing material so persistence and auth can run outside tests.

## Next Phase Readiness
- The frontend can now consume one authenticated chat stream, render citation arrays, and list/reload same-thread conversation history.
- Plan `03-04` can focus on UI integration without redefining backend payloads or history behavior.

---
*Phase: 03-product*
*Completed: 2026-02-28*
