# Roadmap: PolisiGPT

## Overview

Three phases deliver the complete product. Phase 1 builds the raw document corpus — scraper infrastructure harvesting real government documents into storage, deployed on a DigitalOcean Droplet with automated scheduling. Phase 2 transforms that corpus into a searchable vector knowledge base via the indexing pipeline. Phase 3 delivers the full user-facing product: RAG API that answers questions with cited sources, and a Next.js chat interface where users log in, ask questions in BM or English, and read sourced answers. At the end of Phase 3, the core value proposition is demonstrable end-to-end.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Data Corpus** - Scraper infrastructure and government site adapters harvesting real documents into DO Spaces, deployed on a Droplet with automated cron scheduling *(completed 2026-02-28)*
- [ ] **Phase 2: Indexing Pipeline** - LlamaIndex pipeline parsing, embedding, and storing document chunks in Supabase pgvector
- [ ] **Phase 3: Product** - RAG API with citations and language detection plus Next.js chat UI with auth, citations, and conversation history

## Phase Details

### Phase 1: Data Corpus
**Goal**: Real government documents are being collected and stored automatically, ready for indexing
**Depends on**: Nothing (first phase)
**Requirements**: DB-01, SCRP-01, SCRP-02, SCRP-03, INFRA-01, INFRA-02
**Success Criteria** (what must be TRUE):
  1. Supabase schema (documents, conversations, messages, citations tables) is migrated and accessible
  2. Scraper runs and uploads raw files (HTML, PDF, DOCX, XLSX) to DO Spaces with SHA256 deduplication preventing re-upload of unchanged files
  3. At least 5 government site adapters produce real documents from their target sites
  4. Crawl state is tracked so a partial run can resume without re-fetching completed sites
  5. Scraper and indexer are runnable on the DigitalOcean Droplet with Python environment, dependencies, and credentials in place — a manual `python scraper.py` completes successfully
  6. A cron job on the Droplet triggers the scraper automatically at 9:00 AM MYT (UTC+8) every 3 days with no manual intervention required
**Plans**:
- [x] 01-01: Scaffold scraper package, config contracts, and Supabase schema migration
- [x] 01-02: Implement shared scraper core (HTTP/dedup/state/Spaces) and adapter framework
- [x] 01-03: Build 5 government site adapters with smoke crawl validation
- [x] 01-04: Provision droplet runtime, cron automation, and operations runbook

### Phase 2: Indexing Pipeline
**Goal**: All documents in DO Spaces are parsed, chunked, embedded, and searchable via vector similarity in Supabase
**Depends on**: Phase 1
**Requirements**: INDX-01, INDX-02, INDX-03, INDX-04
**Success Criteria** (what must be TRUE):
  1. Running the indexer against DO Spaces produces populated rows in the Supabase `documents` table with embeddings and source metadata (title, URL, agency, date)
  2. Embeddings are generated using OpenAI `text-embedding-3-large` and a vector similarity query in Supabase returns relevant chunks for a test BM or English query
  3. Re-running the indexer on unchanged files skips them; only new or changed files are processed
  4. All four document types (HTML, PDF, DOCX, XLSX) are parsed without errors
**Plans**:
- [x] 02-01: Scaffold indexer runtime, corpus manifest loading, and incremental state contracts
- [x] 02-02: Implement HTML/PDF/DOCX/XLSX parsing and chunk assembly
- [ ] 02-03: Wire embeddings, Supabase persistence, and retrieval smoke queries
- [ ] 02-04: Operationalize end-to-end indexing on the droplet

### Phase 3: Product
**Goal**: A user can open the app, log in, ask a policy question in BM or English, and receive a cited answer sourced from real government documents — with conversation history persisted
**Depends on**: Phase 2
**Requirements**: API-01, API-02, API-03, API-04, FE-01, FE-02, FE-03, FE-04
**Success Criteria** (what must be TRUE):
  1. User can sign up with email and password, log in, and remain logged in across browser refresh
  2. User can type a question in Bahasa Malaysia and receive an answer in Bahasa Malaysia; typing in English returns an English answer
  3. Every answer contains inline superscript citation numbers (e.g., [1]) and clicking one opens the original source document URL in a new browser tab
  4. User can view a sidebar list of past conversation sessions and click any to resume it with full message history
  5. A question with no matching documents returns a graceful "no information found" response rather than a hallucinated answer
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Data Corpus | 4/4 | Complete | 2026-02-28 |
| 2. Indexing Pipeline | 2/4 | In Progress |   |
| 3. Product | 0/TBD | Not started | - |
