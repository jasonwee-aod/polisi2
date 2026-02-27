# PolisiGPT

## What This Is

An AI-powered chatbot that lets Malaysians ask questions in plain language about government policies and official documents, and receive cited answers sourced directly from real government publications. Users ask in Bahasa Malaysia or English and get answers in the same language, with inline clickable citations linking back to the original source document.

## Core Value

A user asks a question about Malaysian government policy and gets a direct, sourced answer — in their language — without having to search across 30+ fragmented government websites.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Scraper collects raw documents (HTML, PDF, DOCX, XLSX) from government websites into DO Spaces
- [ ] Indexing pipeline parses, chunks, embeds, and stores documents in Supabase pgvector
- [ ] API backend receives a user question, retrieves relevant chunks via vector search, and returns a Claude-generated answer with inline citations
- [ ] Frontend provides a chat interface where users can ask questions and see cited answers
- [ ] Citations appear as inline superscript numbers that open the source document in a new tab
- [ ] System responds in the language of the user's question (BM or English)
- [ ] Conversation history is persisted per user session

### Out of Scope

- Mobile native app — web-first, mobile later
- Real-time chat/messaging features — RAG chatbot only, not social
- Admin moderation panel — not needed for v1 demo
- Advanced user analytics dashboard — ship first, measure later
- OAuth / SSO login — defer to post-validation

## Context

- Core problem: Malaysian government information is fragmented across 30+ websites, official documents (PDFs, circulars) are hard for non-experts to parse, and existing AI tools handle Bahasa Malaysia poorly for policy/legal text.
- v1 is a demo with a curated set of seeded government documents to validate the UX and core value proposition before scaling up the scraper.
- Existing work: Core scraper infrastructure (shared HTTP client, dedup, state, DO Spaces upload) exists. Most site-specific adapters not yet built.
- Build order from infrastructure.md: Scraper → Indexer → API → Frontend.
- Embedding: OpenAI `text-embedding-3-large` chosen for strong multilingual BM performance.
- LLM: Anthropic Claude API — chosen for citation reliability and policy/legal text handling.

## Constraints

- **Solo developer**: One person building — simplicity and maintainability matter. Avoid over-engineering.
- **Budget**: Keep monthly infrastructure costs within ~$50/month at early stage.
- **Language**: Bahasa Malaysia support is non-negotiable. The system must handle BM queries and return BM responses accurately for official policy language.
- **Tech stack**: Python (scraper/indexer/API), Next.js (frontend), Supabase (DB/auth/vectors), DigitalOcean (compute/storage), LlamaIndex (RAG pipeline), Vercel (frontend hosting).

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Embedding model: OpenAI `text-embedding-3-large` | Best multilingual quality including BM, reliable API | — Pending |
| Crawl schedule: every 3 days at 9:00 AM MYT | Balances freshness with server load | — Pending |
| Citation display: inline superscript `[1]`, opens source in new tab | Clean UX, direct access to original document | — Pending |
| Language handling: respond in user's query language | BM in → BM out, EN in → EN out | — Pending |
| LLM: Claude (Anthropic) | Citation reliability, policy text handling | — Pending |
| Compute: DigitalOcean Droplet | Simple, cost-effective, full Linux control | — Pending |
| Storage: DigitalOcean Spaces (S3-compatible) | Cheap, same provider as compute, same boto3 client | — Pending |
| Database: Supabase (pgvector) | Auth + vectors + chat history in one service | — Pending |
| Frontend: Next.js on Vercel | Best AI coding tool support, zero-config deploy | — Pending |

---
*Last updated: 2026-02-28 after initialization*
