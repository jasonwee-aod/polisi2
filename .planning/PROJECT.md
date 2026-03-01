# PolisiGPT

## What This Is

An AI-powered chatbot that lets Malaysians ask questions in plain language about government policies and official documents, and receive cited answers sourced directly from real government publications. Users ask in Bahasa Malaysia or English and get answers in the same language, with inline clickable citations linking back to the original source document.

v1.0 shipped: scraper harvesting 5 government sites → LlamaIndex pgvector indexing pipeline → FastAPI RAG backend with streaming and citations → Next.js chat UI with auth, citation panel, and conversation history.

## Core Value

A user asks a question about Malaysian government policy and gets a direct, sourced answer — in their language — without having to search across 30+ fragmented government websites.

## Requirements

### Validated

- ✓ Scraper collects raw documents (HTML, PDF, DOCX, XLSX) from government websites into DO Spaces — v1.0 (5 adapters: MOF, MOE, JPA, MOH, DOSM; SHA256 dedup; automated 3-day Droplet cron)
- ✓ Indexing pipeline parses, chunks, embeds, and stores documents in Supabase pgvector — v1.0 (LlamaIndex; text-embedding-3-large; incremental skip; HTML/PDF/DOCX/XLSX)
- ✓ API backend receives a user question, retrieves relevant chunks via vector search, and returns a Claude-generated answer with inline citations — v1.0 (FastAPI; NDJSON streaming; language detection BM/EN)
- ✓ Frontend provides a chat interface where users can ask questions and see cited answers — v1.0 (Next.js; Supabase Auth; conversation history sidebar)
- ✓ Citations appear as inline superscript numbers that open the source document in a new tab — v1.0 (fallback to plain [N] when source_url is null)
- ✓ System responds in the language of the user's question (BM or English) — v1.0
- ✓ Conversation history is persisted per user session — v1.0 (Supabase conversations + messages tables; resume thread)

### Active

- [ ] Expand scraper to cover all 30-40 target Malaysian government websites (SCRP-04)
- [ ] Drop NOT NULL constraints on `documents.source_url` and `citations.source_url` via SQL migration (schema/code alignment, tech debt from v1.0)
- [ ] Live end-to-end validation with real credentials (DO Spaces + Supabase + OpenAI + Anthropic)

### Out of Scope

- Mobile native app — web-first, mobile later
- Real-time chat/messaging features — RAG chatbot only, not social
- Admin moderation panel — not needed for v1 demo
- Advanced user analytics dashboard — ship first, measure later
- OAuth / SSO login — email/password sufficient for demo validation; deferred to post-validation (AUTH-01)
- Video or audio content types — government docs are text-based
- Offline mode — real-time retrieval is core value

## Context

- Core problem: Malaysian government information is fragmented across 30+ websites, official documents (PDFs, circulars) are hard for non-experts to parse, and existing AI tools handle Bahasa Malaysia poorly for policy/legal text.
- v1.0 shipped a fully wired product at code-inspection level. All 4 E2E flows complete. Live credential validation pending.
- Tech stack: Python (scraper/indexer/API), Next.js (frontend), Supabase (DB/auth/pgvector), DigitalOcean (compute/storage), LlamaIndex (RAG pipeline), Vercel (frontend hosting), Claude claude-sonnet-4-6 (LLM), OpenAI text-embedding-3-large (embeddings).
- ~1.3M lines across Python + TypeScript; 89 commits; 141 files changed in v1.0.
- Known tech debt: 2 schema/code divergences (NOT NULL on source_url columns), 3 human verifications pending.
- Pre-existing test failure: `test_current_user_dependency_rejects_missing_or_invalid_tokens` requires live Postgres; predates all milestone work.

## Constraints

- **Solo developer**: One person building — simplicity and maintainability matter. Avoid over-engineering.
- **Budget**: Keep monthly infrastructure costs within ~$50/month at early stage.
- **Language**: Bahasa Malaysia support is non-negotiable. The system must handle BM queries and return BM responses accurately for official policy language.
- **Tech stack**: Python (scraper/indexer/API), Next.js (frontend), Supabase (DB/auth/vectors), DigitalOcean (compute/storage), LlamaIndex (RAG pipeline), Vercel (frontend hosting).

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Embedding model: OpenAI `text-embedding-3-large` | Best multilingual quality including BM, reliable API | ✓ Good — 3072 dims; pgvector match_documents returns relevant BM/EN results |
| Crawl schedule: every 3 days at 9:00 AM MYT | Balances freshness with server load | ✓ Good — `0 1 */3 * *` UTC cron, preflight gate before run |
| Citation display: inline superscript `[1]`, opens source in new tab | Clean UX, direct access to original document | ✓ Good — fallback [N] span when source_url is null (no error state) |
| Language handling: respond in user's query language | BM in → BM out, EN in → EN out | ✓ Good — detected and passed to Claude system prompt |
| LLM: Claude (Anthropic) | Citation reliability, policy text handling | ✓ Good — formal government-brief tone, grounded to corpus |
| Compute: DigitalOcean Droplet | Simple, cost-effective, full Linux control | ✓ Good — systemd units, preflight script, cron operational |
| Storage: DigitalOcean Spaces (S3-compatible) | Cheap, same provider as compute, same boto3 client | ✓ Good — `gov-my/{agency}/{year-month}/filename.ext` path strategy |
| Database: Supabase (pgvector) | Auth + vectors + chat history in one service | ✓ Good — single service for auth, pgvector, conversations |
| Frontend: Next.js on Vercel | Best AI coding tool support, zero-config deploy | ✓ Good — Supabase Auth SSR, middleware auth-first routing |
| source_url as S3 object metadata dict | Manifest can read back source URL without extra DB queries | ✓ Good — `obj.metadata.get("source_url")` in manifest.py |
| CitationRecord.source_url: str \| None | Graceful degradation for docs with no source URL | ✓ Good — plain [N] fallback; no "unavailable" error message |
| 429 handling: return degraded response, not HTTP 500 | Never surface provider errors as app errors | ✓ Good — Anthropic 429 → fallback string; OpenAI 429 → [] → no-info response |
| Verification by static code inspection for v1.0 | Live credentials not available in dev environment | ⚠️ Revisit — live E2E validation still pending post-deploy |

---
*Last updated: 2026-03-01 after v1.0 milestone*
