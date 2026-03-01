# Phase 4: Fix source_url Chain + Commit Smoke Fixes - Context

**Gathered:** 2026-03-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix the broken `source_url` data chain so that the original government document URL flows intact from the scraper (adapter-level) through the manifest, SpacesUploader, and runner.py into Supabase chunk rows, and renders as working citation links in the frontend. Additionally, commit all existing uncommitted smoke-fix changes (CORS fixes, async-Supabase fixes) that were written but not yet committed.

This phase does NOT add new features — it closes integration gaps identified in the v1.0 audit.

</domain>

<decisions>
## Implementation Decisions

### source_url value
- `source_url` must store the **original government document URL** (the URL from which the document was scraped) — not the DO Spaces CDN URL
- This is what citation links in the frontend must open, per Phase 3 success criteria (clicking a citation opens the original source document URL in a new browser tab)
- The Spaces CDN URL (where the file is stored) is a separate concern and does not replace source_url

### Citation fallback behavior
- When `source_url` is null for a chunk (pre-fix legacy data), citations should render as **unlinked text** (e.g., `[1]` with no anchor tag) — non-breaking degradation
- Do not hide the citation number entirely; that would lose attribution context
- No tooltip or "source unavailable" message needed — keep it simple

### Smoke-fix commit strategy
- Each logical fix should be its own commit with a clear message (CORS fix, async-Supabase fix, etc.)
- Do not bundle unrelated fixes into a single commit
- If a fix is already staged or in a working tree, commit it separately

### Re-indexing scope
- After fixing source_url propagation in the pipeline code, re-index a **sample set** of existing documents (not full re-index) to validate the fix produces correct source_url values in Supabase
- Full re-indexing of all documents is NOT required in this phase — that can be done operationally
- The code fix is the deliverable; sample validation confirms it works

### Claude's Discretion
- Exact location in code where source_url is lost (researcher will identify this)
- Whether the fix is in SpacesUploader, runner.py, manifest schema, or all three
- How to handle documents that have no source_url available (e.g., scraped from pagination without direct URL)
- Sample set size for validation testing

</decisions>

<specifics>
## Specific Ideas

- The chain starts at the adapter level where the original URL is known, and must be preserved all the way to the `source_url` column in Supabase document chunks
- The frontend citation renderer (Phase 3 work) already expects `source_url` — fixing the data pipeline should make citations work without frontend changes

</specifics>

<deferred>
## Deferred Ideas

- None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-fix-source-url-chain*
*Context gathered: 2026-03-01*
