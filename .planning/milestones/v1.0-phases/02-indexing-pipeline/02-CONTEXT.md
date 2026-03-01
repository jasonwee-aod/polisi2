# Phase 2: Indexing Pipeline - Context

**Gathered:** 2026-02-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Transform raw government documents already stored in DO Spaces into a searchable vector corpus in Supabase. This phase covers parsing, chunking, embedding, metadata capture, and incremental re-indexing behavior for HTML, PDF, DOCX, and XLSX. User-facing answer generation, citation rendering, and chat behavior remain outside this phase.

</domain>

<decisions>
## Implementation Decisions

### Chunk structure and citation granularity
- Prefer larger chunks over very small passage slices.
- Later citations only need to point to the relevant section or page, not an exact sentence span.
- Chunk overlap should be used if it improves retrieval accuracy.
- Tables and list-heavy sections should be kept together or split apart based on what improves retrieval accuracy, not on a fixed formatting rule.

### Parsing expectations by file type
- If a document parses imperfectly but yields useful text, index the usable content instead of failing the whole document.
- For scanned PDFs or weak extractions, salvage whatever text is possible rather than skipping the document outright.
- LLM-assisted parsing or understanding is acceptable when it improves extraction quality for difficult documents.
- XLSX support can be basic in v1 as long as the pipeline stays stable and does not crash.
- For XLSX, preserve granularity where possible so policy-relevant rows or sections remain meaningfully searchable.

### Re-indexing and change handling
- Re-indexing should keep older indexed versions instead of replacing them destructively.
- When a document changes, reprocess the whole document rather than trying to patch only affected chunks.
- Change detection should be based on file content hash.
- If a newly fetched version becomes unreadable or parses worse, keep the older indexed version searchable.

### Search-ready metadata
- Every indexed chunk should carry core source metadata needed downstream: document title, source URL, agency, document type, publish date, language, and version identity.
- Chunk-level metadata should be included when available, especially section heading, page number, sheet name, and row-level label or equivalent locator.
- If publish date is missing or ambiguous, infer it from document context where possible.
- Mixed-language documents should allow chunk-level language tagging when sections differ, while still preserving a document-level primary language when useful.

### Claude's Discretion
- Exact chunk sizing, overlap window, and chunking heuristics.
- How full-document context is represented when using LLM assistance for difficult parses.
- The exact metadata schema beyond the required fields above.
- Confidence or fallback rules when inferred publish dates remain uncertain after contextual extraction.

</decisions>

<specifics>
## Specific Ideas

- Retrieval accuracy matters more than rigid chunk formatting rules.
- Preserve enough context that the later LLM can work with meaningful document sections instead of isolated fragments.
- Favor graceful salvage behavior on messy government files rather than dropping documents too aggressively.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 02-indexing-pipeline*
*Context gathered: 2026-02-28*
