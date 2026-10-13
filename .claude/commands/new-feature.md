---
description: Scaffold a new frontend feature in apps/web following the Motionile feature structure
argument-hint: <feature-name> <one-line purpose>
---

Scaffold the frontend feature `$ARGUMENTS`.

1. Read `docs/context.md` sections 2 and 6, `apps/web/CLAUDE.md` and `.claude/skills/nextjs-feature/SKILL.md`.
2. Confirm the endpoints exist in `@motionile/api-contract`. If not, stop and list the backend work needed first.
3. Create `apps/web/src/features/<name>/` with `api/<name>.api.ts`, `hooks/`, `components/`, `schemas/<name>.schema.ts`, `types/<name>.types.ts` and `query-keys.ts`, containing only what the requested behaviour needs.
4. Add or update the route under `apps/web/src/app/` with metadata that follows the SEO rules.
5. Add Vitest tests under `apps/web/tests/unit/` and a Playwright journey under `tests/e2e/` when a new user flow appears.
6. Run `pnpm verify` and fix every failure without weakening a check.
7. Report the routes, components and hooks added, and the command results.
