---
phase: 02-indexing-pipeline
plan: 04
subsystem: infra
tags: [droplet, systemd, preflight, runbook, operations]
requires:
  - phase: 02-03
    provides: "Runnable indexer runner, smoke query helper, and direct persistence path"
provides:
  - "Component-aware preflight checks for scraper and indexer runtime"
  - "Systemd scraper-to-indexer handoff on the droplet"
  - "Phase 2 runbook for first full index, BM/EN smoke checks, and incremental reruns"
affects: [production-ops, phase-03-product]
tech-stack:
  added: [systemd, bash, postgresql-client]
  patterns: ["component-aware-preflight", "scraper-post-run-handoff", "runbook-driven-acceptance"]
key-files:
  created: []
  modified:
    - infra/droplet/setup_runtime.sh
    - infra/droplet/systemd/polisi-scraper.service
    - infra/droplet/systemd/polisi-indexer-placeholder.service
    - infra/droplet/RUNBOOK.md
    - scraper/scripts/preflight_check.py
    - scraper/src/polisi_scraper/indexer/runner.py
    - scraper/src/polisi_scraper/indexer/pipeline.py
    - scraper/README.md
    - scraper/tests/test_indexer_pipeline.py
key-decisions:
  - "Preflight now validates specific components so droplet operators can isolate scraper or indexer readiness."
  - "The existing placeholder service path was preserved and converted into the real indexer execution unit to avoid a second orchestration path."
  - "Operational acceptance is documented around first full index, BM/EN smoke queries, and incremental reruns."
patterns-established:
  - "Systemd handoff should trigger the indexer only after scraper completion and preflight success."
  - "Operators should dry-run indexer config before live reruns when secrets or infrastructure change."
requirements-completed: [INDX-04]
duration: 4min
completed: 2026-02-28
---

# Phase 2 / Plan 04 Summary

**Phase 2 now runs as an operational droplet workflow with component-aware preflight checks, scraper-to-indexer systemd handoff, and a runbook for full and incremental indexing.**

## Performance
- **Duration:** 4 min
- **Started:** 2026-02-28T21:36:00+08:00
- **Completed:** 2026-02-28T21:39:48+08:00
- **Tasks:** 3
- **Files modified:** 9

## Accomplishments
- Extended droplet bootstrap and preflight checks to cover indexer env vars, imports, and connectivity targets.
- Replaced the placeholder indexer service path with a real `polisi_scraper.indexer.runner` execution flow triggered after scraper completion.
- Wrote the Phase 2 runbook for first full index, Bahasa Malaysia / English smoke queries, and incremental rerun validation.

## Task Commits
1. **Task 1: Extend droplet runtime and preflight checks for indexing** - `25e05b5`
2. **Task 2: Replace the placeholder indexer service and wire scraper handoff** - `77eb8db`
3. **Task 3: Write the Phase 2 operational runbook and acceptance checklist** - `ab2249a`

## Files Created/Modified
- `scraper/scripts/preflight_check.py` - validates scraper and indexer runtime readiness by component.
- `infra/droplet/setup_runtime.sh` - provisions parser, embedding, and Postgres client dependencies on the droplet.
- `scraper/src/polisi_scraper/indexer/runner.py` - adds incremental/full runner modes for manual and service-driven execution.
- `scraper/src/polisi_scraper/indexer/pipeline.py` - supports full reruns or single-path manual indexing from the runner.
- `infra/droplet/systemd/polisi-scraper.service` - triggers the indexer service after successful scraper completion.
- `infra/droplet/systemd/polisi-indexer-placeholder.service` - now runs the real indexer service path.
- `infra/droplet/RUNBOOK.md` - documents setup, full index, query smoke, and incremental rerun acceptance.
- `scraper/README.md` - documents runner modes and indexer preflight usage.
- `scraper/tests/test_indexer_pipeline.py` - locks runner mode flags and smoke-query behavior.

## Decisions Made
- Kept the original systemd file names so existing droplet installation steps remain stable while the service behavior changes underneath.
- Required preflight on both the scraper and indexer service paths so missing credentials or imports fail fast before long-running jobs start.

## Deviations from Plan
- None - plan executed exactly as written.

## Issues Encountered
- None.

## User Setup Required
**External services still require manual configuration.** See `02-03-USER-SETUP.md` for the OpenAI and Supabase DB credentials this operational path expects.

## Next Phase Readiness
- Phase 2 is operationally complete and ready to support the API/backend retrieval work in Phase 3.
- The next phase can assume chunked, embedded, retrievable corpus data is available once the user supplies the remaining external credentials.

---
*Phase: 02-indexing-pipeline*
*Completed: 2026-02-28*
