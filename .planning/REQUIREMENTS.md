# Requirements: PolisiGPT

**Defined:** 2026-02-28
**Core Value:** A user asks a question about Malaysian government policy and gets a direct, sourced answer — in their language — without having to search across 30+ fragmented government websites.

## v1 Requirements

### Scraper

- [ ] **SCRP-01**: Core scraper infrastructure is in place — shared HTTP client, SHA256-based deduplication, crawl state tracking, and DO Spaces upload
- [ ] **SCRP-02**: Site adapter framework exists — `adapters/<site_slug>.py` pattern with a base class providing shared logic (HTTP, dedup, state, upload)
- [ ] **SCRP-03**: At least 5 government site adapters are implemented and producing real documents (HTML, PDF, DOCX, or XLSX)

### Indexer

- [ ] **INDX-01**: LlamaIndex pipeline reads raw files from DO Spaces, parses documents (HTML, PDF, DOCX, XLSX), chunks them, and generates embeddings
- [ ] **INDX-02**: Embeddings are generated using OpenAI `text-embedding-3-large` for multilingual BM/EN support
- [ ] **INDX-03**: Chunks with embeddings and source metadata (title, URL, agency, date) are written to Supabase pgvector (`documents` table)
- [ ] **INDX-04**: Indexer is incremental — already-indexed documents are skipped, only new or changed files are processed

### API Backend

- [ ] **API-01**: User can send a question and receive a Claude-generated answer grounded in retrieved document chunks via vector similarity search
- [ ] **API-02**: Every API response includes an inline citation schema — answer text with `[N]` references and a `citations` array with title, agency, URL, excerpt, and published date
- [ ] **API-03**: System detects the language of the user's question and Claude responds in the same language (Bahasa Malaysia or English)
- [ ] **API-04**: User's conversation messages are stored and retrievable from Supabase (`conversations` and `messages` tables)

### Frontend

- [ ] **FE-01**: User can sign up with email and password and log in — session persists across browser refresh (Supabase Auth)
- [ ] **FE-02**: User can type a question in the chat interface and receive an answer with inline superscript citation numbers
- [ ] **FE-03**: Clicking an inline citation number opens the original source document URL in a new browser tab
- [ ] **FE-04**: User can view a sidebar list of their past conversation sessions and click to resume any conversation

### Database Schema

- [ ] **DB-01**: Supabase schema includes: `documents` (chunks + embeddings + metadata), `conversations`, `messages`, `citations` tables correctly defined and migrated

## v2 Requirements

### Scraper Expansion

- **SCRP-04**: Additional site adapters beyond the initial 5 (expand to all 30-40 target government websites)
- **SCRP-05**: Cron job scheduling runs automatically every 3 days at 9:00 AM MYT with no manual intervention

### User Experience

- **FE-05**: User can search or filter across their conversation history
- **FE-06**: User can rate or flag an answer as unhelpful

### Administration

- **ADMIN-01**: Admin interface to view scraper run logs and adapter status
- **ADMIN-02**: Admin can trigger a manual re-crawl for a specific site

### Auth

- **AUTH-01**: OAuth login (Google) as alternative to email/password

## Out of Scope

| Feature | Reason |
|---------|--------|
| Mobile native app | Web-first; mobile deferred post-validation |
| Real-time collaborative chat | Not relevant to single-user RAG use case |
| SSO / OAuth for v1 | Email/password sufficient for demo validation |
| Admin moderation panel | No user-generated content; not needed for v1 |
| Video or audio content types | Government docs are text-based; not in scope |
| Analytics dashboard | Ship first, measure later |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| SCRP-01 | Phase ? | Pending |
| SCRP-02 | Phase ? | Pending |
| SCRP-03 | Phase ? | Pending |
| INDX-01 | Phase ? | Pending |
| INDX-02 | Phase ? | Pending |
| INDX-03 | Phase ? | Pending |
| INDX-04 | Phase ? | Pending |
| API-01 | Phase ? | Pending |
| API-02 | Phase ? | Pending |
| API-03 | Phase ? | Pending |
| API-04 | Phase ? | Pending |
| FE-01 | Phase ? | Pending |
| FE-02 | Phase ? | Pending |
| FE-03 | Phase ? | Pending |
| FE-04 | Phase ? | Pending |
| DB-01 | Phase ? | Pending |

**Coverage:**
- v1 requirements: 16 total
- Mapped to phases: 0 (pending roadmap)
- Unmapped: 16 ⚠️

---
*Requirements defined: 2026-02-28*
*Last updated: 2026-02-28 after initial definition*
