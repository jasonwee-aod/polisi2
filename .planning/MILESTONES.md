# Milestones

## v1.0 PolisiGPT (Shipped: 2026-03-01)

**Phases completed:** 5 phases, 16 plans
**Timeline:** 2026-02-28 → 2026-03-01 (2 days)
**Requirements:** 18/18 v1 requirements satisfied

**Key accomplishments:**
1. Built scraper infrastructure with 5 government site adapters (MOF, MOE, JPA, MOH, DOSM), SHA256 dedup, DO Spaces upload, and automated 3-day cron schedule on DigitalOcean Droplet
2. LlamaIndex indexing pipeline parsing HTML/PDF/DOCX/XLSX with `text-embedding-3-large` embeddings stored in Supabase pgvector (incremental skip on unchanged files)
3. FastAPI RAG backend with NDJSON streaming, Claude-powered answers, language detection (BM/EN), inline citation schema, and conversation persistence
4. Next.js chat UI with Supabase Auth, inline citation superscripts, citation inspection panel, and recent-first conversation history sidebar
5. Fixed source_url propagation chain (S3 metadata → manifest → Supabase), added 429 rate-limit fallbacks for Anthropic and OpenAI, and empty-embedding guard
6. Full VERIFICATION.md coverage for all 5 phases; all 4 E2E user flows complete at code-wiring level

**Tech debt carried forward:**
- Schema divergence: `documents.source_url` and `citations.source_url` have NOT NULL constraints in DB while Python models treat them as nullable — fix: add `ALTER TABLE ... DROP NOT NULL` migration
- Human verification pending: live end-to-end run with real credentials (DO Spaces + Supabase + OpenAI + Anthropic) not yet performed

**Git tag:** v1.0
**Archive:** .planning/milestones/v1.0-ROADMAP.md

---
