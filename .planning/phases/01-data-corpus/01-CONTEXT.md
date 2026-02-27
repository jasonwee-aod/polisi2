# Phase 1: Data Corpus - Context

**Gathered:** 2026-02-28
**Status:** Ready for planning

<domain>
## Phase Boundary

Scraper infrastructure harvesting real Malaysian government documents (HTML, PDF, DOCX, XLSX) into DO Spaces, with site-specific adapters, SHA256 deduplication, crawl state tracking for resumability, and automated cron scheduling on a DigitalOcean Droplet. Indexing and search are Phase 2.

</domain>

<decisions>
## Implementation Decisions

### Storage structure
- Organize files in DO Spaces by site/agency hierarchy: `gov-my/{agency}/{year-month}/filename.ext`
- Use original filename from URL (not hash-based names)
- When a file at the same URL changes, add a date suffix to the new version (e.g., `report_2026-02-28.pdf`) — old version is preserved
- Document metadata (source URL, scrape date, agency, file type) stored in Supabase only — no sidecar JSON files in DO Spaces

### Claude's Discretion
- Target site priority order and exact adapter selection (5+ sites required by success criteria)
- Rate limiting and politeness delays per site
- Crawl depth and pagination handling
- Error handling and retry behavior
- Crawl state storage mechanism (per-URL tracking)
- Exact DO Spaces path sanitization for edge cases (long filenames, special characters)

</decisions>

<specifics>
## Specific Ideas

No specific requirements beyond what was captured — open to standard approaches for areas under Claude's Discretion.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-data-corpus*
*Context gathered: 2026-02-28*
