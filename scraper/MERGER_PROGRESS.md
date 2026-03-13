# Scraper Merger Progress — Context Handoff

## Status: PHASE 0–3 COMPLETE — All 11 adapters, configs, tests written and passing

## What's DONE

### Core Infrastructure (Phase 0 — COMPLETE)
- `src/polisi_scraper/core/dates.py` — Consolidated Malay date parser
- `src/polisi_scraper/core/urls.py` — URL canonicalization + host allowlist
- `src/polisi_scraper/core/extractors.py` — Default document link scanner
- `src/polisi_scraper/core/browser.py` — Playwright browser pool (lazy-init, thread-safe)

### Adapter Framework (COMPLETE)
- `src/polisi_scraper/adapters/base.py` — Rich adapter interface (BaseSiteAdapter ABC, data models, state store, HTTP client, Spaces archiver)
- `src/polisi_scraper/adapters/registry.py` — Auto-discovery + registration for all 11 adapters
- `src/polisi_scraper/adapters/__init__.py` — Updated to use new registry

### Runner & CLI (COMPLETE)
- `src/polisi_scraper/runner.py` — ThreadPoolExecutor-based parallel runner
- `src/polisi_scraper/cli.py` — Click CLI with --sites/--workers/--dry-run/--since/--max-pages

### All 11 Adapters (Phases 1–3 — COMPLETE)
| Adapter | File | CMS | Status |
|---------|------|-----|--------|
| bheuu | `adapters/bheuu.py` | Strapi v3 API | COMPLETE |
| perpaduan | `adapters/perpaduan.py` | CSS selector | COMPLETE |
| idfr | `adapters/idfr.py` | Joomla 4, 4 archetypes | COMPLETE |
| moe | `adapters/moe.py` | DataTables listing | COMPLETE |
| moh | `adapters/moh.py` | Joomla 4 offset pagination | COMPLETE |
| mcmc | `adapters/mcmc.py` | Kentico ASP.NET, Bootstrap pagination | COMPLETE |
| rmp | `adapters/rmp.py` | Sitefinity, path pagination | COMPLETE |
| mohe | `adapters/mohe.py` | RSS feeds + DOCman | COMPLETE |
| kpkt | `adapters/kpkt.py` | Custom Joomla, hex-obfuscated downloads | COMPLETE |
| dewan_johor | `adapters/dewan_johor.py` | WordPress + WPDM + Divi | COMPLETE |
| dewan_selangor | `adapters/dewan_selangor.py` | WordPress + pdfjs-viewer + e-QUANS | COMPLETE |

### YAML Configs (11 of 11 — COMPLETE)
All configs in `configs/`:
bheuu.yaml, dewan_johor.yaml, dewan_selangor.yaml, idfr.yaml, kpkt.yaml, mcmc.yaml, moe.yaml, moh.yaml, mohe.yaml, perpaduan.yaml, rmp.yaml

### Tests (1041 passing)
| Category | File | Tests |
|----------|------|-------|
| **Adapter: bheuu** | `tests/adapters/test_bheuu.py` | 101 |
| **Adapter: perpaduan** | `tests/adapters/test_perpaduan.py` | 24 |
| **Adapter: idfr** | `tests/adapters/test_idfr.py` | 82 |
| **Adapter: moe** | `tests/adapters/test_moe.py` | 56 |
| **Adapter: moh** | `tests/adapters/test_moh.py` | 56 |
| **Adapter: mcmc** | `tests/adapters/test_mcmc.py` | 111 |
| **Adapter: rmp** | `tests/adapters/test_rmp.py` | 56 |
| **Adapter: mohe** | `tests/adapters/test_mohe.py` | 60 |
| **Adapter: kpkt** | `tests/adapters/test_kpkt.py` | 87 |
| **Adapter: dewan_johor** | `tests/adapters/test_dewan_johor.py` | 117 |
| **Adapter: dewan_selangor** | `tests/adapters/test_dewan_selangor.py` | 116 |
| **Core: dates** | `tests/core/test_dates.py` | 30 |
| **Core: urls** | `tests/core/test_urls.py` | 30 |
| **Core: extractors** | `tests/core/test_extractors.py` | 15 |
| **Core: browser** | `tests/core/test_browser.py` | 6 |
| **Integration: download detection** | `tests/integration/test_download_detection.py` | 27 |
| **Integration: dry run** | `tests/integration/test_dry_run.py` | 8 |
| **Pre-existing tests** | `tests/test_*.py` | ~15 |
| **TOTAL** | | **1041** |

### Test Fixtures (COMPLETE)
Fixtures copied from specific-scrapers to `tests/fixtures/`:
- bheuu (6 JSON), dewan_johor (9 HTML/XML), dewan_selangor (9 HTML/XML), idfr (4 HTML), kpkt (6 HTML), mcmc (6 HTML), moh (4 HTML), rmp (5 HTML)
- moe, mohe, perpaduan use inline fixtures in tests

## What's NOT DONE (Phase 4: Integration & Deployment)

### Live Integration Testing
- [ ] Full dry-run of all 11 adapters against live sites: `polisi-scraper --dry-run --max-pages 2`
- [ ] Compare `records.jsonl` output against original scrapers' output (document count parity)
- [ ] Spot-check at least 20 records per adapter (220 total minimum)

### QA Gates (from Scraper-Guide.md)
- [ ] Validate minimum metadata completeness: every record has title, published_at, canonical_url
- [ ] Confirm publication dates are parsed correctly (sample Malay + English dates)
- [ ] Confirm duplicates are below threshold (0 duplicate SHA256 within each adapter)
- [ ] Confirm host-alias rules working
- [ ] Confirm discovery fallback works
- [ ] Confirm broken file downloads are retried and logged

### Deployment
- [ ] Run on DO Droplet with real Playwright + Spaces upload
- [ ] Deploy systemd service (`polisi-scraper.service`) with `ExecStartPost` indexer chaining
- [ ] Set up systemd timer for every-3-days schedule
- [ ] Write deployment runbook
- [ ] Verify 3 unattended cycles (9 days)

## Key Architecture Decisions Already Made
- Click CLI (not argparse)
- Per-adapter SQLite DBs at `data/state/<slug>.sqlite3`
- DO Spaces only (no GCS) — path: `gov-docs/<slug>/raw/YYYY/MM/DD/<sha256>_<filename>`
- ThreadPoolExecutor with 3 default workers
- Rich adapter hooks: discover() → fetch_and_extract() → extract_downloads()
- @register_adapter decorator for auto-registration
- Existing indexer pipeline left untouched
