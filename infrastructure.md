# PolisiGPT Infrastructure Overview

## What We're Building

An AI-powered chatbot for Malaysian government data. Users ask questions in plain language and get answers sourced directly from official government documents, with citations linking back to the original source.

---

## Architecture at a Glance

```
Government Websites
        ↓
    [Scraper Layer]
    DO Droplet + Cron
        ↓
    [Raw File Storage]
    DigitalOcean Spaces
        ↓
    [Indexing Layer]
    LlamaIndex (parsing + chunking + embeddings)
        ↓
    [Vector + User Database]
    Supabase (pgvector + auth + chat history)
        ↓
    [API Layer]
    FastAPI + LlamaIndex + Claude API
        ↓
    [Frontend]
    Next.js on Vercel
        ↓
    [End User]
    Public web app with login, chat, citations
```

---

## Layer by Layer

### Layer 1 — Scraper

**What it does:** Crawls 30-40 Malaysian government websites on a schedule, downloads raw files (HTML, PDF, DOCX, XLSX), deduplicates by SHA256 hash, and writes a metadata manifest.

**Where it runs:** DigitalOcean Droplet (entry ~$6/month). Python cron jobs scheduled at 9:00 AM MYT (UTC+8) every 3 days. One Droplet runs all scrapers sequentially.

**Key design:** Each site has its own adapter file (`adapters/<site_slug>.py`) with site-specific parsing logic. Shared infrastructure (HTTP client, dedup, state, storage) lives in the core and is inherited by all adapters.

**Output:** Raw files uploaded to DO Spaces, metadata written to `records.jsonl`.

**Tech:** Python, `requests`, `BeautifulSoup`, `Playwright` (JS-heavy sites), `boto3` (Spaces upload), SQLite (crawl state).

---

### Layer 2 — Raw File Storage

**What it does:** Stores original source files exactly as downloaded, organised by site and date.

**Service:** DigitalOcean Spaces (~$5/month flat for 250GB).

**Path convention:**
```
gov-docs/<site_slug>/raw/<YYYY>/<MM>/<DD>/<sha256>_<filename>
```

**Why not GCS/S3:** Spaces is S3-compatible (same `boto3` client), cheaper at this scale, and keeps everything in one cloud provider.

---

### Layer 3 — Indexing

**What it does:** Reads raw files from Spaces, extracts text, splits into chunks, generates embeddings, and writes them into Supabase's vector store.

**Where it runs:** Same DO Droplet as the scraper, triggered after each crawl run.

**Tech:** LlamaIndex handles the full pipeline — document loading, chunking, embedding via OpenAI `text-embedding-3-large`, and writing to pgvector.

**Embedding model:** OpenAI `text-embedding-3-large`. Chosen for strong multilingual performance including Bahasa Malaysia, and reliability at scale. Higher quality than `text-embedding-3-small` with better retrieval accuracy for policy and legal text.

**Output:** Vector embeddings stored in Supabase, ready to be queried at runtime.

---

### Layer 4 — Database (Supabase)

**What it does:** Single database that serves two purposes — vector search for the RAG pipeline, and relational storage for user data.

**Service:** Supabase (free tier to start, ~$25/month Pro when needed).

**Tables:**

| Table | Purpose |
|---|---|
| `documents` | Chunk text, embeddings, source metadata (title, URL, agency, date) |
| `users` | Managed by Supabase Auth automatically |
| `conversations` | One row per chat session |
| `messages` | One row per message, linked to conversation and user |
| `citations` | Source documents referenced in each assistant response |

**Why Supabase over standalone Postgres:** Built-in auth (login, sessions, SSO), native pgvector support, realtime subscriptions for streaming chat, and good Next.js integration libraries.

---

### Layer 5 — API Backend

**What it does:** Receives a user question, retrieves relevant document chunks from Supabase, passes them to Claude as context, returns Claude's answer with citations.

**Where it runs:** Same DO Droplet, or a separate small Droplet if load justifies it.

**Tech:** FastAPI + LlamaIndex + Anthropic Claude API.

**Response schema** (every response includes inline citations):
```json
{
  "answer": "The policy states that education subsidies apply to all public institutions[1], including technical colleges[2].",
  "citations": [
    {
      "index": 1,
      "title": "Surat Siaran KPM 2025",
      "agency": "Kementerian Pendidikan Malaysia",
      "url": "https://www.moe.gov.my/...",
      "excerpt": "...the relevant passage from the document...",
      "published_at": "2025-03-12"
    },
    {
      "index": 2,
      "title": "Pekeliling KPM Bil. 3/2024",
      "agency": "Kementerian Pendidikan Malaysia",
      "url": "https://www.moe.gov.my/...",
      "excerpt": "...the relevant passage...",
      "published_at": "2024-08-01"
    }
  ],
  "language": "ms",
  "conversation_id": "uuid",
  "message_id": "uuid"
}
```

**Citation behaviour:** Inline superscript numbers appear at the end of each sentence (e.g. `[1]`). Clicking opens the source document URL in a new browser tab. The frontend maps each number to its corresponding entry in the `citations` array.

**Language handling:** Claude detects the language of the user's question and responds in the same language. If the user asks in BM, the answer is in BM. If in English, the answer is in English. Mixed-language questions default to the dominant language detected.
```

---

### Layer 6 — Frontend

**What it does:** Public-facing web app where users sign up, log in, ask questions, and read answers with inline source citations.

**Service:** Vercel (free tier to start).

**Tech:** Next.js (React framework).

**Key screens:**
- Login / signup
- Chat interface with inline superscript citations — clicking `[1]` opens the source URL in a new tab
- Conversation history sidebar
- Source document viewer (opens original PDF/page in new tab)

**Citation UX:** Inline numbers appear inside the answer text at sentence level. Each number is a clickable link. No expandable cards or footnotes — the source opens directly.

**Why Next.js on Vercel:** Best vibe-coding support across all AI coding tools, zero-config deployment, Supabase has official Next.js integration libraries.

---

## Cost Summary (Early Stage)

| Service | Purpose | Est. Monthly Cost |
|---|---|---|
| DigitalOcean Droplet | Scraper + API backend | ~$12 |
| DigitalOcean Spaces | Raw file storage | ~$5 |
| Supabase | Database, auth, vectors | Free → $25 |
| Vercel | Frontend hosting | Free |
| OpenAI API | Embeddings (`text-embedding-3-large`) | ~$0.13/million tokens |
| Anthropic Claude API | LLM queries | Pay per use |
| **Total** | | **~$17–42/month** |

Embedding costs at initial indexing are a one-time batch cost. Re-indexing only runs on new or changed documents every 3 days, so ongoing embedding costs are minimal.

---

## Decisions Log

| Decision | Choice | Rationale |
|---|---|---|
| Embedding model | OpenAI `text-embedding-3-large` | Best multilingual quality including BM, reliable API |
| Crawl schedule | Every 3 days at 9:00 AM MYT | Balances freshness with server load |
| Citation display | Inline superscript `[1]`, opens source in new tab | Clean UX, direct access to original document |
| Language handling | Responds in language of the user's question | BM in → BM out, EN in → EN out |
| Language model | Claude (Anthropic) | Citation reliability, policy text handling |
| Compute | DigitalOcean Droplet | Simple, cost-effective, full Linux control |
| Object storage | DigitalOcean Spaces | S3-compatible, cheap, same provider as compute |
| Database | Supabase (pgvector) | Auth + vectors + chat history in one service |
| Frontend | Next.js on Vercel | Best vibe-coding support, zero-config deploy |

---

## What Gets Built in What Order

1. **Scraper layer** — already mostly built, needs storage swap from GCS to DO Spaces
2. **Indexing layer** — LlamaIndex pipeline reading from Spaces, writing to Supabase
3. **API backend** — FastAPI wrapper around LlamaIndex + Claude, with citation response schema
4. **Frontend** — Next.js app with Supabase auth and chat UI

---

## Retrieval Quality Roadmap

Improvements to make the chatbot smarter, listed from highest-impact/lowest-effort to most ambitious.

### Phase 1 — Hybrid Search + Metadata Filtering (DONE)

**Status:** Implemented via migration `20260314_01_hybrid_search.sql`

Added full-text search (PostgreSQL tsvector with GIN index) alongside vector similarity, fused with Reciprocal Rank Fusion (RRF). Also added agency-based metadata filtering extracted from user questions.

**What changed:**
- `documents.fts` tsvector column populated on insert via trigger
- `hybrid_match_documents()` SQL function: runs both vector + FTS, merges via RRF, supports agency/date filters
- `HybridPostgresRetriever` in the API — now the default retriever
- `extract_agency()` in `detector.py` — detects agency mentions and passes filter to retrieval
- `RetrievedChunk.effective_similarity` — normalises FTS-only matches so they aren't discarded

**Key parameters:**
- `RETRIEVAL_RRF_K` (default 60) — RRF smoothing constant
- `RETRIEVAL_FTS_MIN_SIMILARITY` (default 0.50) — similarity floor for FTS-only matches

### Phase 2 — Cross-Encoder Reranking (Future)

**Goal:** After hybrid retrieval returns top-N candidates, run a cross-encoder to rerank by actual relevance to the question. This eliminates irrelevant chunks that happen to share vocabulary but aren't answering the right question.

**Approach:**
- Retrieve top 20 candidates via hybrid search
- Score each with a cross-encoder (e.g., `ms-marco-MiniLM-L-12-v2`) or a lightweight Claude Haiku call
- Return top 5 reranked results to the prompt

**Estimated effort:** 2 days. Main work is adding the reranker step to `HybridPostgresRetriever.retrieve()` and a new `Reranker` protocol.

**Tradeoff:** Adds ~200ms latency per query (cross-encoder) or ~1s + cost (Claude call). Worth it if irrelevant chunk dilution is a frequent problem.

### Phase 3 — Agentic RAG: Query Planning + Conversation Context (Future)

**Goal:** Handle complex multi-part questions and follow-up questions that the current single-shot retrieval can't answer well.

**Approach:**
- **Query planner:** Before retrieval, make a fast Claude Haiku call that decomposes the question into sub-queries and detects metadata filters (agency, date range, topic). Example: "Compare education subsidies between 2023 and 2024" → two sub-queries with date filters.
- **Multi-retrieval:** Run each sub-query independently through hybrid search, merge results.
- **Conversation-aware:** Pass the last 3-5 messages as context to the query planner so follow-up questions like "what about eligibility?" understand what "it" refers to.

**Estimated effort:** 3-4 days. Requires a new `QueryPlanner` class, changes to `ChatService.generate_reply()` to pass conversation history, and updates to the streaming route.

**Tradeoff:** Adds 1-2 extra LLM calls per query. Use Haiku for the planner to keep cost/latency low. The conversation history loading requires changes to `handle_chat()`.

### Phase 4 — Knowledge Graph Layer (Future)

**Goal:** Enable navigational and relational queries that neither vector nor keyword search can handle. "What policies does MOE manage?", "What programs are related to BR1M?", "Show me all housing-related benefits."

**Approach (Postgres-native, no new infra):**
- **Entity extraction during indexing:** Use Claude or a NER model to extract structured entities from each document: policy names, programs, agencies, monetary amounts, dates, eligibility criteria.
- **Schema:**
  ```sql
  policy_entities (id, entity_type, name, canonical_name, metadata)
  entity_relationships (source_id, target_id, relationship_type, confidence)
  document_entities (document_id, entity_id, chunk_index, mention_text)
  ```
- **Query-time flow:** Extract entities from the user's question → query the graph for related entities/documents → merge graph-retrieved documents with hybrid search results → pass to LLM.
- **Incremental build:** Run entity extraction as a post-indexing step; can backfill existing documents.

**Estimated effort:** 1-2 weeks. The entity extraction pipeline is the bulk of the work. Graph traversal via recursive CTEs in Postgres is straightforward.

**Alternative:** Use Neo4j for richer graph traversal. Only justified if the Postgres approach hits performance limits at scale.

**Tradeoff:** Significant upfront investment in entity extraction quality. Valuable if users frequently ask relational/navigational questions rather than factual lookups.
