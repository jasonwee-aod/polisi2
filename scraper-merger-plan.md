# Scraper Merger Plan

> **Goal**: Unify 11 standalone scrapers into a single `scraper/` codebase with one adapter per government site, running on one DigitalOcean Droplet.

---

## Decisions (Locked In)

| Decision | Choice |
|----------|--------|
| Storage backend | DO Spaces only (drop all GCS code) |
| Spaces path convention | `gov-docs/<slug>/raw/<YYYY>/<MM>/<DD>/<sha256>_<filename>` |
| Adapter interface | Rich hooks: `discover()` → `fetch()` → `extract_downloads()` |
| Browser automation | Playwright always available (lazy-init browser pool) |
| State database | Per-adapter SQLite DBs (`data/state/<slug>.sqlite3`) |
| Deployment | systemd service with `ExecStartPost` to chain indexer |
| CLI flags | `--sites` / `--site-config` / `--since` / `--max-pages` / `--dry-run` / `--workers` |
| Parallelism | 3 concurrent adapter threads (default); Playwright serialized via lock |
| Discovery priority | Prefer machine-readable endpoints (API, sitemap, RSS) before HTML scraping |

---

## Current State

### Existing Main Scraper (`scraper/`)
- 5 **stub adapters** (MOF, MOE, JPA, MOH, DOSM) — hardcoded URLs, no real scraping
- Core infra: HTTP client, SHA256 dedup, SQLite state, DO Spaces uploader
- Indexing pipeline: parse → chunk → embed → Supabase (already functional)
- Flat interface: `iter_document_candidates()` returns a list — too simple for real sites

### 11 Specific Scrapers (`specific-scrapers/`)
| Scraper | CMS | Discovery | Download Quirks | Tests |
|---------|-----|-----------|----------------|-------|
| bheuu | Strapi v3 API | JSON API pagination | Direct URLs from JSON | 84 |
| dewan-johor | WordPress + WPDM | Sitemaps + 4 hub pages | WPDM redirect tokens | 30+ |
| dewan-selangor | WordPress | Sitemaps + WP/Bootstrap pagination + 3-level hub | pdfjs-viewer iframes | 60+ |
| idfr | Joomla 4 + SP Page Builder | Static listing pages | Direct PDF links | Yes |
| kpkt | Custom PHP | Hardcoded listings + hub-and-spoke | **Hex-obfuscated `/dl/` links** | 40+ |
| mcmc | Kentico (ASP.NET) | Bootstrap pagination | ASP.NET GetAttachment redirects | 66 |
| moe | Unknown | DataTables listing | Standard links | **0** |
| moh | Joomla 4 | Joomla offset pagination | Embedded docs in article body | Yes |
| mohe | Joomla + DOCman | RSS feeds (bilingual) + DOCman tables | DOCman `/file` endpoints | 38+ |
| perpaduan | Unknown | CSS selector-driven | HTML only (no file downloads) | Basic |
| rmp | Sitefinity (ASP.NET) | Path-based pagination | RadGrid tables, sfdownloadLink | Yes |

---

## Architecture After Merge

```
scraper/
├── src/polisi_scraper/
│   ├── core/                          # Shared infrastructure
│   │   ├── http_client.py             # requests + tenacity retry
│   │   ├── browser.py                 # Playwright browser pool (NEW)
│   │   ├── dedup.py                   # SHA256 hashing
│   │   ├── state_store.py             # Per-adapter SQLite state
│   │   ├── spaces.py                  # DO Spaces uploader (unified)
│   │   ├── dates.py                   # Malay date parsing (NEW, shared)
│   │   ├── urls.py                    # URL canonicalization (NEW, shared)
│   │   └── models.py                  # DocumentCandidate, Record, CrawlRun
│   │
│   ├── adapters/                      # One file per government site
│   │   ├── base.py                    # BaseSiteAdapter ABC (rich hooks)
│   │   ├── registry.py                # Auto-discovery + registration
│   │   ├── bheuu.py
│   │   ├── dewan_johor.py
│   │   ├── dewan_selangor.py
│   │   ├── idfr.py
│   │   ├── kpkt.py
│   │   ├── mcmc.py
│   │   ├── moe.py
│   │   ├── moh.py
│   │   ├── mohe.py
│   │   ├── perpaduan.py
│   │   └── rmp.py
│   │
│   ├── runner.py                      # Orchestrator (calls adapters in sequence)
│   ├── cli.py                         # Click CLI entry point
│   └── config.py                      # ScraperSettings from env
│
├── configs/                           # YAML per adapter
│   ├── bheuu.yaml
│   ├── dewan_johor.yaml
│   ├── dewan_selangor.yaml
│   ├── idfr.yaml
│   ├── kpkt.yaml
│   ├── mcmc.yaml
│   ├── moe.yaml
│   ├── moh.yaml
│   ├── mohe.yaml
│   ├── perpaduan.yaml
│   └── rmp.yaml
│
├── tests/
│   ├── fixtures/                      # HTML/XML/JSON fixtures per adapter
│   │   ├── bheuu/
│   │   ├── dewan_johor/
│   │   ├── ... (one subdir per adapter)
│   │   └── rmp/
│   ├── core/                          # Tests for shared infra
│   │   ├── test_dates.py
│   │   ├── test_urls.py
│   │   ├── test_state_store.py
│   │   ├── test_spaces.py
│   │   └── test_browser.py
│   ├── adapters/                      # Tests per adapter
│   │   ├── test_bheuu.py
│   │   ├── test_dewan_johor.py
│   │   ├── ... (one file per adapter)
│   │   └── test_rmp.py
│   └── integration/                   # End-to-end pipeline tests
│       ├── test_dry_run.py
│       └── test_download_detection.py # The "Muat Turun" regression suite
│
├── data/
│   ├── state/                         # Per-adapter SQLite DBs
│   │   ├── bheuu.sqlite3
│   │   ├── dewan_johor.sqlite3
│   │   └── ...
│   └── manifests/                     # Per-adapter JSONL output
│       ├── bheuu/
│       └── ...
│
└── pyproject.toml
```

---

## Rich Adapter Interface

```python
class BaseSiteAdapter(ABC):
    """Every government site adapter implements these hooks."""

    slug: str                  # e.g. "bheuu"
    agency: str                # e.g. "Bahagian Hal Ehwal Undang-undang"
    requires_browser: bool     # If True, orchestrator provides Playwright page

    # --- HOOK 1: Discovery ---
    # Priority order (per Scraper-Guide.md):
    #   1. Machine-readable endpoints (API, sitemap.xml, RSS/Atom)
    #   2. HTML scraping (listing pages, hub pages)
    #   3. Playwright (JS-rendered pages) — only when static parsing misses content
    @abstractmethod
    def discover(self, since: date | None, max_pages: int) -> Iterable[DiscoveredItem]:
        """
        Yield pages/documents to process.
        DiscoveredItem = (source_url, title, published_at, doc_type, metadata)

        Adapters implement their own discovery logic:
        - API pagination (BHEUU)
        - Sitemap parsing (Dewan Johor/Selangor)
        - RSS feed parsing (MOHE)
        - HTML listing traversal (MOH, MCMC, RMP)
        - Hub-and-spoke crawling (KPKT, Dewan Selangor)
        """
        ...

    # --- HOOK 2: Fetch + Extract Downloads ---
    def fetch_and_extract(self, item: DiscoveredItem) -> Iterable[DocumentCandidate]:
        """
        Given a discovered item, fetch the page and extract all downloadable
        document URLs from it. Default implementation:
        1. GET the page HTML
        2. Call extract_downloads() to find PDF/DOCX/XLSX links
        3. Yield one candidate per download link + the page itself if configured

        Override for sites that need special handling (WPDM tokens, hex-encoded
        links, ASP.NET GetAttachment, etc.)
        """
        ...

    # --- HOOK 3: Download Link Extraction (the "Muat Turun" problem) ---
    def extract_downloads(self, html: str, base_url: str) -> list[DownloadLink]:
        """
        Parse an HTML page and return all downloadable document links.
        Default implementation scans for:
        - <a href="*.pdf|.docx|.xlsx|.doc|.xls|.ppt|.pptx|.zip">
        - <iframe> with pdfjs-viewer src

        Override for site-specific patterns:
        - KPKT: Decode hex-obfuscated /dl/ links
        - Dewan Johor: Follow WPDM ?wpdmdl= redirect tokens
        - MCMC: Resolve /getattachment/ ASP.NET links
        - MOHE: Handle DOCman /file endpoints
        - Dewan Selangor: Extract from pdfjs-viewer shortcode iframes
        """
        ...

    # --- Optional hooks ---
    def should_skip(self, item: DiscoveredItem, state: StateStore) -> bool:
        """Pre-fetch dedup check. Default: skip if canonical_url exists in state."""
        ...

    def post_process(self, record: Record) -> Record:
        """Transform record after download (e.g., normalize metadata)."""
        ...
```

### Orchestrator Flow (runner.py)

The orchestrator runs adapters in **parallel waves** using `concurrent.futures.ThreadPoolExecutor`.
Each adapter is fully independent (own state DB, own YAML config, own HTTP session), so they
can safely run concurrently. Playwright access is serialized via a lock.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

def run_scrape(adapters, since, max_pages, dry_run, max_workers=3):
    """Run adapters in parallel waves. Default 3 concurrent workers."""
    browser_pool = BrowserPool()              # Shared, thread-safe via lock
    browser_lock = threading.Lock()
    uploader = SpacesUploader(dry_run=dry_run)
    results = {}

    def run_adapter(adapter):
        state = StateStore(f"data/state/{adapter.slug}.sqlite3")
        http = HttpClient(delay=adapter.config.get("request_delay", 1.5))
        records = []

        for item in adapter.discover(since, max_pages):
            if adapter.should_skip(item, state):
                continue

            # Playwright access serialized — only one adapter renders at a time
            if adapter.requires_browser:
                with browser_lock:
                    candidates = list(adapter.fetch_and_extract(item))
            else:
                candidates = list(adapter.fetch_and_extract(item))

            for candidate in candidates:
                raw_bytes = http.get_bytes(candidate.url)
                sha256 = compute_sha256(raw_bytes)

                if state.sha256_exists(sha256):
                    state.reuse_existing(candidate, sha256)
                    continue

                spaces_url = uploader.upload(raw_bytes, candidate)
                state.mark_processed(candidate, sha256, spaces_url)
                records.append(emit_record(candidate, sha256, spaces_url))

        return adapter.slug, records

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(run_adapter, a): a.slug for a in adapters}
        for future in as_completed(futures):
            slug = futures[future]
            try:
                slug, records = future.result()
                results[slug] = {"status": "ok", "count": len(records)}
            except Exception as exc:
                results[slug] = {"status": "error", "error": str(exc)}
                log.error(f"Adapter {slug} failed: {exc}")

    browser_pool.close()
    return results
```

### Parallelism Design

**Why threads (not processes):**
- Adapters are I/O-bound (network requests + Spaces uploads), not CPU-bound
- Threads share the Playwright browser process (one Chromium, multiple contexts)
- Per-adapter SQLite DBs eliminate DB contention — no shared write locks
- `ThreadPoolExecutor` is simpler than `multiprocessing` and sufficient for I/O workloads

**Concurrency controls:**

| Resource | Strategy | Rationale |
|----------|----------|-----------|
| HTTP requests | Per-adapter `HttpClient` with own delay | No cross-adapter rate conflict; each site gets its own polite delay |
| SQLite state | Per-adapter DB file | Zero contention — each thread owns its DB |
| DO Spaces uploads | Shared `SpacesUploader` (boto3 sessions are thread-safe) | S3 API handles concurrent PUTs natively |
| Playwright browser | Shared `BrowserPool` + `threading.Lock` | Only one adapter renders at a time; others continue with `requests` |
| JSONL output | Per-adapter manifest file (`data/manifests/<slug>/records.jsonl`) | No file contention |

**Default workers: 3**
- Fits comfortably in 1GB Droplet (~200MB base + 100MB Chromium + 3 threads × ~50MB each)
- Configurable via `--workers N` CLI flag
- Set to 1 for sequential execution (debugging) or up to 5 for faster runs on larger Droplets

**Estimated runtime improvement:**

| Scenario | Workers | Est. Runtime | Notes |
|----------|---------|-------------|-------|
| Sequential | 1 | ~90-120 min | Current approach; safe baseline |
| Parallel (default) | 3 | ~35-50 min | 3 adapters run simultaneously |
| Parallel (aggressive) | 5 | ~25-35 min | Needs 2GB Droplet if Playwright active |

**Adapter grouping for optimal parallelism:**

The orchestrator sorts adapters into waves to maximize throughput:
- Wave scheduling is automatic — `ThreadPoolExecutor` handles it — but adapters that
  `requires_browser=True` effectively serialize their Playwright sections while their
  `requests`-based sections run freely in parallel.
- Heaviest adapters (dewan-selangor ~4900 pages, moh ~8 years of statements) start first
  so they don't become tail bottlenecks.

```python
# Sort: heaviest adapters first (estimated page count descending)
adapters.sort(key=lambda a: a.config.get("estimated_pages", 0), reverse=True)
```

---

## Shared Utilities to Extract

These patterns appear in nearly every scraper and should be consolidated:

### 1. Malay Date Parser (`core/dates.py`)
All 11 scrapers implement their own Malay month translation. Consolidate into one:
```python
MALAY_MONTHS = {
    "januari": "January", "februari": "February", "mac": "March",
    "april": "April", "mei": "May", "jun": "June",
    "julai": "July", "ogos": "August", "september": "September",
    "oktober": "October", "november": "November", "disember": "December",
}
# + abbreviated forms, day names (isnin, selasa, etc.)
```

### 2. URL Canonicalizer (`core/urls.py`)
All scrapers do: force HTTPS, lowercase host, strip fragments, host allowlist. One module.

### 3. Content-Type Guesser (`core/models.py`)
Map file extensions → MIME types. Currently duplicated 11 times.

### 4. Document Link Scanner (`core/extractors.py`)
Default `<a href>` scanner for `.pdf`, `.docx`, `.xlsx`, etc. Adapters override for special patterns.

### 5. Browser Pool (`core/browser.py`)
Manages a single Playwright browser instance shared across adapters that need it. Provides `new_context()` per adapter, handles lifecycle (launch on first use, close on shutdown).

---

## Migration Phases

### Phase 0: Scaffold & Shared Core (Week 1)
**Goal**: Set up the unified adapter interface and shared utilities without breaking existing code.

- [ ] Create `BaseSiteAdapter` with rich hooks (discover, fetch_and_extract, extract_downloads)
- [ ] Extract `core/dates.py` (Malay date parser) from existing scrapers
- [ ] Extract `core/urls.py` (URL canonicalization + host allowlist)
- [ ] Unify `core/state_store.py` to support per-adapter DB paths
- [ ] Ensure `core/spaces.py` works as the sole storage backend (drop GCS references)
- [ ] Add `core/browser.py` Playwright pool with lifecycle management
- [ ] Add `core/extractors.py` default document link scanner
- [ ] Write tests for all shared utilities
- [ ] Delete the 5 stub adapters (MOF, MOE, JPA, MOH, DOSM)

**Tests required**:
- `test_dates.py`: Malay months (all 12), abbreviations, day-of-week stripping, year-only, partial dates, edge cases (empty, whitespace, invalid)
- `test_urls.py`: HTTPS forcing, host lowercasing, fragment stripping, query preservation, allowlist enforcement, make_absolute, canonicalization idempotence
- `test_state_store.py`: CRUD, URL dedup, SHA256 dedup, crawl_run tracking, mark_inactive, per-adapter isolation
- `test_spaces.py`: Path convention, upload mock, dry-run mode
- `test_browser.py`: Pool lifecycle, context creation, cleanup on failure

### Phase 1: Migrate "Simple" Adapters (Week 2)
**Goal**: Port the 4 simplest scrapers — those with straightforward discovery and no download tricks.

Order (easiest first):
1. **bheuu** — Pure API, no HTML parsing at all
2. **perpaduan** — CSS selector listing, HTML-only archival
3. **idfr** — Static listing pages, direct PDF links
4. **moe** — DataTables listing (also: **write tests for the first time**)

For each adapter:
- [ ] Create `adapters/<slug>.py` implementing the 3 hooks
- [ ] Copy YAML config to `configs/<slug>.yaml`
- [ ] Migrate test fixtures to `tests/fixtures/<slug>/`
- [ ] Migrate and adapt tests to `tests/adapters/test_<slug>.py`
- [ ] Verify: `pytest tests/adapters/test_<slug>.py -v` passes
- [ ] Dry-run: `polisi-scraper --sites <slug> --dry-run` produces correct `records.jsonl`

### Phase 2: Migrate "Pagination" Adapters (Week 3)
**Goal**: Port scrapers that rely on paginated listing pages.

Order:
1. **moh** — Joomla offset pagination (`?start=N`)
2. **mcmc** — Bootstrap pagination (`?page=N`)
3. **rmp** — Sitefinity path pagination (`/page/N`)

These share a similar pattern: paginated listing → detail page → extract embedded docs.

For each:
- [ ] Same checklist as Phase 1
- [ ] Additional test: pagination stop conditions (empty page, last page, max_pages)
- [ ] Additional test: embedded document extraction from detail pages

### Phase 3: Migrate "Complex" Adapters (Week 4)
**Goal**: Port scrapers with multi-level discovery, special download mechanics, or both.

Order:
1. **mohe** — RSS feeds + DOCman `/file` endpoints
2. **kpkt** — Hub-and-spoke + **hex-obfuscated download links**
3. **dewan-johor** — Sitemaps + WPDM redirect tokens + 4 hub pages
4. **dewan-selangor** — Sitemaps + WP pagination + Bootstrap pagination + 3-level hub + pdfjs iframes

These require the most custom `fetch_and_extract()` and `extract_downloads()` overrides.

For each:
- [ ] Same checklist as Phase 1
- [ ] Additional test: multi-level discovery (hub → sub-page → documents)
- [ ] Additional test: special download link resolution (hex decode, WPDM follow, etc.)

### Phase 4: Integration, QA Gates & Deployment (Week 5)
**Goal**: End-to-end validation, QA gate compliance, and production deployment.

- [ ] **Download Detection Regression Suite** (see Testing section below)
- [ ] Full dry-run of all 11 adapters sequentially
- [ ] Compare `records.jsonl` output against original scrapers' output (document count parity)
- [ ] **QA Gates** (from Scraper-Guide.md — mandatory before production):
  - [ ] Validate minimum metadata completeness: every record has title, published_at, canonical_url
  - [ ] Spot-check at least 20 records per adapter (220 total minimum)
  - [ ] Confirm publication dates are parsed correctly (sample Malay + English dates)
  - [ ] Confirm duplicates are below threshold (0 duplicate SHA256 within each adapter's output)
  - [ ] Confirm host-alias rules working (no records with URLs outside the adapter's allowlist)
  - [ ] Confirm discovery fallback works (adapters that try sitemap first gracefully fall back to HTML)
  - [ ] Confirm broken file downloads are retried and logged (check structured logs for retry entries)
- [ ] Run on DO Droplet with real Playwright + Spaces upload
- [ ] Deploy systemd service (`polisi-scraper.service`) with `ExecStartPost` indexer chaining
- [ ] Set up systemd timer or cron for every-3-days schedule
- [ ] Write deployment runbook (see `infra/droplet/RUNBOOK.md`)
- [ ] Verify 3 unattended cycles (9 days) complete without errors

---

## Testing Requirements

### Tier 1: Unit Tests (Per Adapter)
Every adapter MUST have tests covering:

1. **Discovery tests**: Given fixture HTML/XML/JSON, `discover()` yields correct items
   - Correct URLs extracted
   - Correct titles parsed
   - Correct dates parsed (including Malay formats)
   - Pagination works (next page detected, stop conditions met)
   - `--since` date filtering works

2. **Download extraction tests**: Given fixture HTML, `extract_downloads()` returns correct links
   - All document links found (PDF, DOCX, XLSX, etc.)
   - No duplicate links
   - Relative URLs resolved to absolute
   - Site-specific patterns handled (hex decode, WPDM tokens, etc.)

3. **Dedup tests**: State store correctly skips already-processed URLs and SHA256 hashes

**Minimum test counts** (based on current coverage):
| Adapter | Min. Tests | Notes |
|---------|-----------|-------|
| bheuu | 80+ | Already has 84, port them |
| dewan-johor | 30+ | Port existing |
| dewan-selangor | 55+ | Port existing |
| idfr | 25+ | Port existing |
| kpkt | 40+ | Port existing, especially hex decode tests |
| mcmc | 60+ | Port existing |
| moe | **20+ (NEW)** | Currently has 0 — must write from scratch |
| moh | 25+ | Port existing |
| mohe | 35+ | Port existing |
| perpaduan | 10+ | Port existing basic tests |
| rmp | 25+ | Port existing |

### Tier 2: Download Detection Regression Suite (Critical)
**This addresses the "missing Muat Turun button" problem.**

Create `tests/integration/test_download_detection.py` with **real HTML snapshots** from each government site. For each snapshot:

```python
@pytest.mark.parametrize("fixture,expected_downloads", [
    # Each fixture is a real page that MUST have its downloads detected
    ("bheuu/media_statement.json", ["uploads/file1.pdf"]),
    ("dewan_johor/wpdm_package.html", ["download_redirect.pdf"]),
    ("kpkt/obfuscated_dl.html", ["/kpkt/resources/user_1/.../file.pdf"]),
    ("mcmc/getattachment.html", ["/getattachment/UUID/file.pdf"]),
    # ... every known download pattern
])
def test_adapter_finds_all_downloads(fixture, expected_downloads):
    """Regression: adapter must find ALL download links on this page."""
    ...
```

**Required regression cases** (at minimum):
1. Direct `<a href="file.pdf">` link
2. `<a href>` with Malay label "Muat Turun"
3. WPDM redirect token (`?wpdmdl=N&ind=N`)
4. Hex-obfuscated `/index.php/dl/<HEX>` link (KPKT)
5. ASP.NET `/getattachment/UUID/file.aspx` redirect (MCMC)
6. DOCman `/file` endpoint (MOHE)
7. pdfjs-viewer `<iframe>` with encoded PDF URL (Dewan Selangor)
8. PDF link inside jQuery accordion (KPKT Siaran Media)
9. PDF link inside DataTables `<table>` (MOE)
10. PDF link inside Sitefinity RadGrid table (RMP)
11. PDF link inside Divi accordion toggle (Dewan Johor hub pages)
12. Link where text says "Download" but href is to an HTML intermediary page
13. Multiple PDFs on a single page (e.g., annual reports collection)
14. Zero-download page (listing page with no documents — should return empty)

### Tier 3: Dry-Run Smoke Tests
```bash
# Run each adapter in dry-run, verify it produces records
polisi-scraper --sites bheuu --dry-run --max-pages 2
polisi-scraper --sites dewan-johor --dry-run --max-pages 2
# ... for all 11
polisi-scraper --dry-run --max-pages 2  # all adapters
```

Automated in CI as:
```python
@pytest.mark.slow
@pytest.mark.network  # requires internet
def test_dry_run_produces_records(adapter_slug):
    """Each adapter must produce at least 1 record in dry-run mode."""
    result = runner.run_scrape(sites=[adapter_slug], dry_run=True, max_pages=2)
    assert result.processed > 0
    assert result.errors == 0
```

### Tier 4: Output Parity Check
After each adapter is migrated:
1. Run the **old** standalone scraper with `--dry-run` → save `records.jsonl`
2. Run the **new** unified adapter with `--dry-run` → save `records.jsonl`
3. Compare: new output must have **>= the same number of documents** as old output
4. Any missing documents = regression = must fix before merging

```python
def test_output_parity(adapter_slug, old_records_path, new_records_path):
    old_urls = {r["canonical_url"] for r in load_jsonl(old_records_path)}
    new_urls = {r["canonical_url"] for r in load_jsonl(new_records_path)}
    missing = old_urls - new_urls
    assert not missing, f"Regression: {len(missing)} documents lost: {missing}"
```

---

## The "Muat Turun" / Missing Download Problem

This is the #1 quality risk. Government sites embed downloads in non-obvious ways:

### Known Patterns to Handle

| Pattern | Sites | How to Detect |
|---------|-------|--------------|
| Direct `<a href="file.pdf">` | All | Default scanner |
| "Muat Turun" labeled button | KPKT, MOH, others | `a` tag where text contains "muat turun" or "download" (case-insensitive) |
| Hex-obfuscated `/dl/` link | KPKT | Decode hex→base64→path |
| WPDM redirect token | Dewan Johor | Follow `?wpdmdl=` redirect to final URL |
| ASP.NET GetAttachment | MCMC | Follow `/getattachment/UUID/` redirect |
| DOCman `/file` endpoint | MOHE | Recognize `/file` suffix as binary download |
| pdfjs-viewer iframe | Dewan Selangor | Parse `viewer.php?file=<encoded-url>` |
| Accordion-hidden links | KPKT, Dewan Johor | Parse full DOM, not just visible content |
| RadGrid/DataTable links | RMP, MOE | CSS selectors specific to grid widgets |
| `onclick="window.open()"` | Potential future | Playwright click + intercept |

### Default Scanner (`core/extractors.py`)

The default `extract_downloads()` in `BaseSiteAdapter` will:
1. Find all `<a href>` with document extensions (.pdf, .doc, .docx, .xls, .xlsx, .ppt, .pptx, .zip)
2. Find all `<a>` where link text matches "muat turun", "download", "muat-turun" (case-insensitive)
3. Find all `<iframe src>` with pdfjs-viewer patterns
4. Find all `<a href>` matching `/getattachment/`, `/dl/`, `/file` patterns
5. Deduplicate results by canonical URL
6. Return list of `DownloadLink(url, label, method)` objects

Adapters override this for site-specific decoding (e.g., KPKT hex decode).

---

## Playwright Integration

Since Playwright is **always available**, the setup is:

### Browser Pool (`core/browser.py`)
```python
class BrowserPool:
    """Lazy-initialized Playwright browser shared across adapters."""

    def __init__(self):
        self._playwright = None
        self._browser = None

    def get_page(self) -> Page:
        """Get a new Playwright page. Launches browser on first call."""
        if not self._browser:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(headless=True)
        return self._browser.new_page()

    def close(self):
        if self._browser: self._browser.close()
        if self._playwright: self._playwright.stop()
```

### Usage in Adapters
```python
class MoheAdapter(BaseSiteAdapter):
    requires_browser = True  # Forms section needs JS rendering

    def discover(self, since, max_pages):
        # RSS sections: use requests (fast)
        yield from self._discover_rss(since)
        # DOCman forms: use Playwright (needs JS)
        page = self.browser_pool.get_page()
        page.goto(self.config["forms_url"])
        page.wait_for_selector(".k-js-documents-table")
        yield from self._extract_docman_items(page.content())
        page.close()
```

### DO Droplet Setup
```bash
# Install Playwright + Chromium on the Droplet
pip install playwright
playwright install chromium
playwright install-deps  # system-level dependencies (libgbm, etc.)
```

Estimated memory overhead: ~100MB for headless Chromium (fits in 1GB Droplet).

### Consistency with Scraper-Guide.md

The browser pool approach is consistent with the updated Scraper-Guide.md section 2.1:
- Playwright is always installed and available
- Adapters opt in via `requires_browser: true` in YAML config
- Adapters that only use `requests` never trigger browser launch (zero overhead)
- Static parsing is preferred for speed; Playwright used when static parsing misses content

---

## Deployment on DO Droplet

### systemd Service (Primary — matches Scraper-Guide.md)

Register as a systemd service at `/etc/systemd/system/polisi-scraper.service`:

```ini
[Unit]
Description=Polisi Scraper — crawl government websites
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=polisi
Group=polisi
WorkingDirectory=/opt/polisigpt
EnvironmentFile=/opt/polisigpt/.env
ExecStart=/opt/polisigpt/venv/bin/polisi-scraper --all --workers 3
ExecStartPost=/opt/polisigpt/venv/bin/polisi-indexer --incremental
TimeoutStartSec=7200
TimeoutStopSec=60
StandardOutput=append:/opt/polisigpt/logs/scraper.log
StandardError=append:/opt/polisigpt/logs/scraper.log

[Install]
WantedBy=multi-user.target
```

Key points:
- **`ExecStartPost`** chains the indexer automatically after scraper completes
- Dedicated `polisi` system user with least privilege (write to Spaces, read `.env`)
- Logs to `/opt/polisigpt/logs/` (accessible via `tail` and `journalctl`)
- 2-hour timeout (`TimeoutStartSec=7200`) for full 11-adapter run

### Cron / systemd Timer

```cron
# Every 3 days at 9:00 AM MYT (1:00 AM UTC)
0 1 */3 * * systemctl start polisi-scraper.service
```

Or equivalently as a systemd timer (`polisi-scraper.timer`):
```ini
[Timer]
OnCalendar=*-*-01,04,07,10,13,16,19,22,25,28 01:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

### CLI Commands
```bash
# Run all adapters
polisi-scraper --all

# Run specific adapters
polisi-scraper --sites bheuu,moh,mcmc

# Point to custom config directory
polisi-scraper --sites kpkt --site-config /path/to/configs/

# Dry run (no uploads, no state writes)
polisi-scraper --sites kpkt --dry-run

# With date filter
polisi-scraper --sites moh --since 2026-03-01

# Limit pages (for testing)
polisi-scraper --sites dewan-selangor --max-pages 5

# Control parallelism
polisi-scraper --all --workers 5      # 5 concurrent adapters (needs 2GB Droplet)
polisi-scraper --all --workers 1      # Sequential (for debugging)
```

### Environment Variables
```bash
# DO Spaces
DO_SPACES_KEY=xxx
DO_SPACES_SECRET=xxx
DO_SPACES_BUCKET=polisi-gov-docs
DO_SPACES_REGION=sgp1
DO_SPACES_ENDPOINT=https://sgp1.digitaloceanspaces.com

# Scraper behavior
SCRAPER_REQUEST_DELAY=1.5
SCRAPER_HTTP_TIMEOUT=30
SCRAPER_LOG_LEVEL=INFO
```

---

## Risk Register

| Risk | Impact | Mitigation |
|------|--------|------------|
| Government site HTML changes break an adapter | Single adapter fails | Per-adapter isolation; failing adapter doesn't block others; alert on error count > 0 |
| Playwright OOM on $6 Droplet | All adapters fail | Lazy-init browser; close after each adapter that uses it; upgrade to $12 Droplet if needed |
| Thread contention / race conditions | Corrupted state or duplicate uploads | Per-adapter state DBs eliminate DB races; Playwright serialized via lock; boto3 is thread-safe; test with `--workers 3` before production |
| Tail-bottleneck adapter | One slow adapter blocks completion | Sort heaviest adapters first; log per-adapter timing; `--workers` tunable |
| Missing "Muat Turun" links | Documents not indexed | Download Detection Regression Suite (Tier 2 tests); output parity check vs old scrapers |
| SQLite corruption | Lost crawl state for one adapter | Per-adapter DBs limit blast radius; daily backup to Spaces |
| Rate limiting / IP ban | Adapter blocked | Per-adapter configurable delay; respect Retry-After; rotate User-Agent |

---

## Success Criteria

The merger is **complete** when:

1. All 11 adapters pass their unit tests (400+ tests total)
2. Download Detection Regression Suite passes (14+ patterns)
3. Dry-run of all adapters produces `records.jsonl` with document counts >= old scrapers
4. Full run on DO Droplet with `--workers 3` completes within 50 minutes
5. `records.jsonl` output is compatible with the existing indexing pipeline
6. All QA Gates from Scraper-Guide.md pass (metadata completeness, date parsing, dedup, host allowlist, retry logging)
7. systemd service runs unattended for 3 cycles (9 days) with indexer chained via `ExecStartPost`
8. MOE adapter has tests for the first time (20+ tests minimum)
9. Spaces objects follow `gov-docs/<slug>/raw/<YYYY>/<MM>/<DD>/<sha256>_<filename>` convention

---

## Appendix: Per-Adapter Migration Checklist

Use this checklist for EACH adapter migration:

```
## Adapter: <slug>

### Code
- [ ] `adapters/<slug>.py` implements discover(), fetch_and_extract(), extract_downloads()
- [ ] `configs/<slug>.yaml` copied and updated (Spaces instead of GCS if applicable)
- [ ] Site-specific extractors ported (date parsing, download link resolution)
- [ ] Host allowlist configured
- [ ] Browser usage declared via `requires_browser` flag

### Tests
- [ ] Fixtures copied to `tests/fixtures/<slug>/`
- [ ] Unit tests ported to `tests/adapters/test_<slug>.py`
- [ ] Discovery tests pass (correct URLs, titles, dates, pagination)
- [ ] Download extraction tests pass (all document links found)
- [ ] Dedup tests pass (URL + SHA256 skip logic)
- [ ] Edge cases covered (empty pages, missing dates, malformed HTML)

### Validation
- [ ] `pytest tests/adapters/test_<slug>.py -v` — all green
- [ ] `polisi-scraper --sites <slug> --dry-run --max-pages 2` — produces records
- [ ] Output parity check vs old scraper passes (no missing documents)
- [ ] Download regression cases added to Tier 2 suite
```
