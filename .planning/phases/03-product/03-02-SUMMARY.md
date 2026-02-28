---
phase: 03-product
plan: 02
subsystem: ui
tags: [nextjs, supabase-auth, middleware, app-router, vitest]
requires:
  - phase: 03-01
    provides: "Stable backend auth and chat/history contract shapes for the product app"
provides:
  - "Next.js App Router scaffold under web/"
  - "Combined Supabase email/password auth surface"
  - "Protected minimal /chat shell with BM-aware first-run state"
affects: [phase-03-product, frontend-chat, auth-session]
tech-stack:
  added: [nextjs, react, @supabase/ssr, vitest, testing-library]
  patterns: ["auth-first-routing", "server-session-shell", "combined-auth-surface"]
key-files:
  created:
    - web/.env.example
    - web/app/layout.tsx
    - web/app/page.tsx
    - web/app/auth/page.tsx
    - web/app/(app)/layout.tsx
    - web/app/(app)/chat/page.tsx
    - web/components/auth/auth-form.tsx
    - web/components/app/app-shell.tsx
    - web/lib/supabase/client.ts
    - web/lib/supabase/server.ts
    - web/middleware.ts
    - web/tests/auth_shell.test.tsx
  modified:
    - web/package.json
    - web/vitest.config.ts
key-decisions:
  - "The web app redirects authenticated users straight into /chat and sends unauthenticated root/chat visits to /auth."
  - "Auth stays on one email/password surface with mode toggling instead of separate login and signup pages."
  - "The signed-in shell remains intentionally sparse so later chat features can extend it without undoing onboarding chrome."
patterns-established:
  - "Protected pages should read the server session first and let middleware keep root/auth/chat routing consistent."
  - "Frontend auth and shell behavior are covered with Vitest + Testing Library using pure route-decision helpers where possible."
requirements-completed: [FE-01]
duration: 5min
completed: 2026-02-28
---

# Phase 3 / Plan 02 Summary

**Next.js product shell with Supabase auth-first routing, one combined auth page, and a minimal BM-aware workspace at `/chat`.**

## Performance
- **Duration:** 5 min
- **Started:** 2026-02-28T22:40:07+08:00
- **Completed:** 2026-02-28T22:45:13+08:00
- **Tasks:** 3
- **Files modified:** 14

## Accomplishments
- Scaffolded the `web/` Next.js app with TypeScript, lint/test tooling, and shared Supabase browser/server helpers.
- Built a combined login/signup screen and auth-first middleware that sends successful sessions into the protected shell.
- Added a minimal `/chat` empty state that stays familiar, sparse, and explicitly ready for BM questions.

## Task Commits
1. **Task 1: Scaffold the Next.js App Router app and Supabase client helpers** - `6b5bdc7`
2. **Task 2: Implement the combined auth page and auth-first routing** - `bd409ef`
3. **Task 3: Add the minimal authenticated shell and first-run empty state** - `d36f204`

## Files Created/Modified
- `web/package.json` - defines the Next.js runtime plus lint and Vitest scripts.
- `web/tsconfig.json` - configures strict TypeScript and the `@/` alias used across the app.
- `web/.env.example` - documents the public Supabase and backend API env contract.
- `web/app/layout.tsx` - sets the root document layout and global stylesheet.
- `web/app/page.tsx` - routes the root entry into `/auth` or `/chat` based on the current session.
- `web/app/auth/page.tsx` - renders the combined auth entry screen.
- `web/app/(app)/layout.tsx` - enforces the server-side session gate for protected routes.
- `web/app/(app)/chat/page.tsx` - provides the first-run empty chat surface with BM-ready guidance.
- `web/components/auth/auth-form.tsx` - handles sign-in/sign-up mode toggling and Supabase auth actions.
- `web/components/app/app-shell.tsx` - provides the minimal signed-in workspace wrapper and sign-out action.
- `web/lib/supabase/client.ts` - exports the browser Supabase SSR helper.
- `web/lib/supabase/server.ts` - exports the server Supabase SSR helper.
- `web/middleware.ts` - keeps `/`, `/auth`, and `/chat` on the auth-first routing contract.
- `web/tests/auth_shell.test.tsx` - validates auth-mode switching, route decisions, and signed-in shell copy.

## Decisions Made
- Used `/chat` as the first protected landing route so the later conversation UI can extend the same path rather than introducing a route migration.
- Kept the first-run state to a headline, short description, and BM-ready example prompts instead of adding onboarding cards or extra dashboard chrome.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Adjusted Vitest root/config so the GSD verification command resolves the test file**
- **Found during:** Task 2 (Implement the combined auth page and auth-first routing)
- **Issue:** `npm --prefix web run test -- web/tests/auth_shell.test.tsx` ran from the `web/` directory, so the plan’s filter path did not resolve by default.
- **Fix:** Updated the test script and Vitest config to run from the repo root while still resolving `@/` imports into `web/`.
- **Files modified:** `web/package.json`, `web/vitest.config.ts`
- **Verification:** `npm --prefix web run test -- web/tests/auth_shell.test.tsx`
- **Committed in:** `bd409ef`

**2. [Rule 3 - Blocking] Escaped quoted example prompts so Next lint passes**
- **Found during:** Plan verification
- **Issue:** Raw quote characters in the `/chat` empty-state copy violated `react/no-unescaped-entities`.
- **Fix:** Replaced them with HTML entities while preserving the intended example prompts.
- **Files modified:** `web/app/(app)/chat/page.tsx`
- **Verification:** `npm --prefix web run lint`
- **Committed in:** `f7455c6`

---

**Total deviations:** 2 auto-fixed (2 blocking)
**Impact on plan:** Both fixes were required to make the exact workflow verification commands pass. No scope expansion.

## Issues Encountered
- `next lint` emits a deprecation notice in Next 15 and warns about an external lockfile at `/Users/jasonwee/package-lock.json`, but it still passes and does not block execution.

## User Setup Required
External services still require manual configuration:
- Provide `NEXT_PUBLIC_SUPABASE_URL`.
- Provide `NEXT_PUBLIC_SUPABASE_ANON_KEY`.
- Provide `NEXT_PUBLIC_API_BASE_URL` once the FastAPI service is running.

## Next Phase Readiness
- The frontend now has a stable auth-first shell ready for conversation streaming, citation rendering, and recent-history navigation.
- Plan `03-04` can build directly on `/chat`, the protected layout, and the shared Supabase session helpers.

---
*Phase: 03-product*
*Completed: 2026-02-28*
