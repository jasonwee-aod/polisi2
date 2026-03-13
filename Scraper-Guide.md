---
name: gov-site-scraper
description: Build and maintain compliant scrapers for government websites to collect public documents, press releases, statements, and notices for RAG pipelines. Use when the user asks to target a specific government site, define per-site extraction rules, run recurring incremental crawls, preserve source provenance, avoid duplicate downloads, and archive original files into DigitalOcean Spaces on a DigitalOcean Droplet.
---

# Objective

Create reliable, compliant, repeatable scraping workflows for government websites, then archive original source files and metadata for downstream RAG.

# Implementation Language

- Build scrapers in Python only.
- Target Python `3.11+`.
- Prefer standard libraries plus:
  - `requests`
  - `beautifulsoup4`
  - `lxml`
  - `python-dateutil`
  - `boto3` (DigitalOcean Spaces — S3-compatible)
  - `tenacity` (or equivalent retry helper)
  - `playwright` (always available; lazy-initialized for all adapters)

# Non-Negotiables

- Prefer official machine-readable endpoints first (`sitemap.xml`, RSS/Atom, open data APIs) before HTML scraping.
- Do not bypass authentication, paywalls, CAPTCHA, or access controls.
- Preserve provenance for every record: source URL, fetch timestamp, checksum, and parser version.
- Keep raw originals (`.pdf`, `.html`, `.docx`, `.xlsx`) in DigitalOcean Spaces.
- Prevent duplicate storage: never store the same document twice.

# Intake Checklist

Collect this before coding:

- Target site and section URLs (example: press room, circulars, publications, speeches).
- Document types to capture (PDF, HTML pages, DOC/DOCX, XLS/XLSX).
- Date policy (all history vs last N years vs incremental from today).
- Language requirements (single language or multilingual).
- Required metadata fields (title, publication date, agency, topic tags).
- Refresh schedule (daily, weekly, monthly).
- Stop conditions (max pages, date cut-off, domain limits).

# Build Workflow

## 1) Discover Structure

- Fetch and parse:
  - `https://<domain>/sitemap.xml` (and nested sitemaps)
  - RSS/Atom feeds if available
- If `sitemap.xml` is missing or returns `404`, fall back to:
  - `Sitemap:` entries in `robots.txt`
  - Common alternates (`/sitemap_index.xml`, `/sitemap-index.xml`, `/sitemap1.xml`)
  - Seeded section URLs provided during intake
- Identify page archetypes:
  - Listing pages (many links)
  - Detail pages (single item with metadata)
  - File links (PDF/DOC/etc.)
- Save selectors/rules per archetype in a site config file.
- Keep selectors/config separate from crawler logic (config-driven per site).

## 2) Implement Crawler

- Start with deterministic parsing (`requests` + `BeautifulSoup` or equivalent).
- Playwright is always available via a lazy-initialized browser pool; adapters opt in with `requires_browser: true` in their YAML config.
- Default browser automation to Playwright (headless).
- Prefer static parsing where possible for speed, but do not skip Playwright for pages that need it — missing a "Muat Turun" button is worse than a slower crawl.
- Normalize links to absolute URLs.
- Enforce same-domain rules unless explicitly allowed.
- Define host allowlist explicitly:
  - Primary host (for example, `example.gov`)
  - Approved aliases (for example, `www.example.gov`)
  - Optional approved subdomains only when required by business scope
- Canonicalize host variants (`http` to `https`, `www` and non-`www`) before dedup checks.
- Add retry with backoff for transient errors (`429`, `5xx`, timeouts).

## 2.1) Playwright Browser Pool

Playwright is always installed and available on the Droplet. A shared `BrowserPool` manages a single headless Chromium instance, lazy-initialized on first use and closed at shutdown.

- Every adapter can request a Playwright page via `self.browser_pool.get_page()`.
- Adapters that need JS rendering declare `requires_browser: true` in their YAML config.
- Adapters that only use `requests` never trigger browser launch (zero overhead).
- Best practices:
  - Reuse one browser context per adapter.
  - Block non-essential assets when safe (images/fonts/media).
  - Wait for specific selectors instead of fixed sleep delays.
  - Close pages promptly after extraction.
- Keep extraction output identical to non-JS pipeline (same metadata and dedup flow).

# Automation on DigitalOcean Droplet

- Run scheduled crawls on a DigitalOcean Droplet using systemd services and cron.
- Adapters run in parallel (default 3 concurrent threads). Each adapter has its own HTTP session, state DB, and manifest file, so no contention. Playwright access is serialized via a lock so only one adapter renders at a time.
- Register the scraper and indexer as systemd services under `/etc/systemd/system/`:
  - `polisi-scraper.service` — runs preflight, smoke crawl, then the full scraper.
  - The indexer service is triggered via `ExecStartPost` after the scraper completes.
- Use a dedicated system user with least privilege:
  - Write access to the Spaces bucket only.
  - Read access to secrets in `/opt/polisigpt/.env` only.
- Store state outside ephemeral memory (per-adapter SQLite DBs at stable paths, e.g. `data/state/<slug>.sqlite3`).
- Pass runtime settings via env vars and CLI flags:
  - `--sites` (comma-separated adapter slugs, e.g. `bheuu,moh,mcmc`; omit to run all)
  - `--site-config` (path to configs directory; defaults to `configs/`)
  - `--workers` (number of concurrent adapter threads; default 3, set to 1 for sequential)
  - `--since`, `--max-pages`, `--dry-run`
- Configure operational safety:
  - systemd `TimeoutStartSec` / `TimeoutStopSec`
  - cron expression for desired schedule (example: `0 1 */3 * *` = 01:00 UTC every 3 days)
- Log to files under `/opt/polisigpt/logs/` so `tail` and `journalctl` both capture run diagnostics.
- See `infra/droplet/RUNBOOK.md` for full provisioning, migration, and operational procedures.

## 3) Extract and Archive Originals

- For each collected item, store:
  - `source_url`
  - `canonical_url`
  - `title`
  - `published_at` (ISO 8601 where possible)
  - `agency` / `publisher`
  - `doc_type`
  - `content_type`
  - `language`
  - `spaces_bucket`
  - `spaces_path`
  - `spaces_url`
  - `sha256`
  - `http_etag` (if available)
  - `http_last_modified` (if available)
  - `fetched_at` (UTC timestamp)
- Keep a canonical URL function to reduce duplicates.
- Save only original file payloads (no normalization/indexing in this skill).

## 4) Incremental Updates

- Maintain a state store (SQLite preferred) with unique constraints on:
  - `canonical_url`
  - `sha256`
- Deduplicate before download:
  - If `canonical_url` already exists and `etag`/`last-modified` is unchanged, skip fetch.
- Deduplicate after download:
  - Compute `sha256`; if hash already exists, do not upload to Spaces again.
- Reuse existing `spaces_path` for duplicate content records.
- Treat different URLs with identical `sha256` as the same document payload.
- Mark removed URLs as `inactive` instead of deleting immediately.
- Produce run summaries: new, changed, skipped, failed.

## 5) QA Gates

- Validate minimum metadata completeness (example: title/date/url present).
- Spot-check at least 20 records per new site.
- Confirm publication dates are parsed correctly.
- Confirm duplicates are below agreed threshold.
- Confirm host-alias rules are working (no unintended external hosts).
- Confirm sitemap fallback discovery works when the default sitemap path is absent.
- Confirm broken file downloads are retried and logged.

# Output Contract (Required)

Use this structure:

```text
data/
  manifests/<site_slug>/
    records.jsonl
    crawl_runs.jsonl
```

`records.jsonl` schema (one JSON object per record):

```json
{
  "record_id": "stable-id",
  "source_url": "https://...",
  "canonical_url": "https://...",
  "title": "Document title",
  "published_at": "2025-10-18",
  "agency": "Agency name",
  "doc_type": "press_release|statement|report|notice|speech|other",
  "content_type": "text/html|application/pdf|...",
  "language": "en",
  "sha256": "hex",
  "spaces_bucket": "my-gov-spaces-bucket",
  "spaces_path": "gov-docs/site-slug/raw/2026/02/26/sha256_filename.pdf",
  "spaces_url": "https://my-gov-spaces-bucket.sgp1.digitaloceanspaces.com/gov-docs/site-slug/raw/2026/02/26/sha256_filename.pdf",
  "http_etag": "\"abc123\"",
  "http_last_modified": "Wed, 21 Oct 2015 07:28:00 GMT",
  "fetched_at": "2026-02-26T12:34:56Z",
  "crawl_run_id": "2026-02-26-site-slug",
  "parser_version": "v1"
}
```

# DigitalOcean Spaces Integration

Archive originals directly into a DigitalOcean Spaces bucket using the S3-compatible API via `boto3`.

Minimum setup:

- Set `DO_SPACES_KEY=<access-key>`.
- Set `DO_SPACES_SECRET=<secret-key>`.
- Set `DO_SPACES_BUCKET=<your-space-name>`.
- Set `DO_SPACES_REGION=<region>` (example: `sgp1`).
- Set `DO_SPACES_ENDPOINT=https://<region>.digitaloceanspaces.com`.
- Upload object path convention:
  - `gov-docs/<site_slug>/raw/<YYYY>/<MM>/<DD>/<sha256>_<original_filename>`
  - Example: `gov-docs/bheuu/raw/2026/03/13/abc123_annual-report.pdf`

Upload rules:

- If `sha256` already exists in state, skip upload and reuse existing `spaces_path`.
- Keep original extension and MIME type metadata.
- Store upload timestamp when available.

# Engineering Style Guide

- Structure:
  - `src/` application code, `tests/` automated tests, `configs/` per-site rules, `data/manifests/` outputs.
- Packaging and dependencies:
  - Use `pyproject.toml` with pinned dependency ranges.
  - Keep environment variables in `.env.example` only (no secrets in repo).
- Code style:
  - Use type hints for public functions.
  - Keep modules focused (single responsibility).
  - Use descriptive names, avoid one-letter variables except loop counters.
- Logging:
  - Use structured logs (JSON preferred) with `crawl_run_id`, `url`, `status`, `reason`.
  - Log retries and terminal failures clearly.
- Error handling:
  - Fail gracefully per URL; continue crawl unless fatal startup/config issue.
  - Emit explicit error categories (`network`, `parse`, `policy`, `storage`).
- Testing:
  - Unit tests for URL canonicalization, host allowlist checks, date parsing, dedup state logic.
  - Integration test with saved HTML fixtures for at least one listing page and one detail page.
  - Mock Spaces (`boto3`) in tests; do not require live cloud access in CI.
- CLI and operations:
  - Provide one command for full run and one for dry-run.
  - Include `--sites`, `--site-config`, `--since`, `--max-pages`, and `--dry-run` flags.
  - Print a run summary at end: discovered, fetched, uploaded, deduped, failed.
- Documentation:
  - Keep a short operator runbook with setup, command examples, and troubleshooting.

# Prompt Templates For Non-Technical Staff

Use these with your coding assistant.

## A) Build New Site Scraper

```text
Build a production-ready scraper for this government site: <SITE_URL>.
Target sections: <SECTION_URLS>.
Collect: press releases, statements, reports, notices.

Requirements:
1) Save original files only to DigitalOcean Spaces.
2) Emit records.jsonl using the schema in Scraper-Guide.md.
3) Add incremental crawling with dedup by canonical URL, etag/last-modified, and sha256.
4) Add logs and a run summary (new/changed/skipped/failed).
5) Use Playwright only as fallback for JavaScript-rendered pages.
6) Add tests for URL normalization, date parsing, and dedup logic.
7) Do not add normalization/indexing steps.

Return:
- project structure
- exact commands to run
- sample output files
```

## B) Fix Broken Scraper After Site Redesign

```text
Update this scraper for <SITE_URL> because selectors changed.
Keep the existing output contract and incremental state.
Add a regression test covering the new HTML layout.
Show only changed files and explain why each change is safe.
```

## C) Add New Content Type

```text
Extend the existing scraper for <SITE_URL> to include <NEW_CONTENT_TYPE>.
Do not break existing extraction.
Update the doc_type mapping, tests, and run summary metrics.
```

# Definition of Done

- Runs end-to-end from a single command.
- Produces valid `records.jsonl` and `crawl_runs.jsonl`.
- Preserves raw source files in DigitalOcean Spaces with stable object paths.
- Avoids storing the same document twice.
- Includes basic automated tests and a short operator runbook.
