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
