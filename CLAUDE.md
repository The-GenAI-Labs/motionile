@AGENTS.md

# Claude workflow

## Before you start

- Read `docs/context.md` in full at the start of every phase, then `docs/roadmap.md` for the phase scope and "done when" criteria.
- Read every ADR in `docs/adr/` that touches the area you are changing. If your change contradicts an ADR, stop and propose a new ADR instead.
- Read the `CLAUDE.md` inside the app you are working in: `apps/server/CLAUDE.md` or `apps/web/CLAUDE.md`.

## Use the right subagent

| Task                                                                       | Subagent            |
| -------------------------------------------------------------------------- | ------------------- |
| New or changed backend module, router, service, repository or migration    | `backend-module`    |
| New or changed frontend feature, page or component                         | `frontend-feature`  |
| Missing tests, flaky tests, coverage gaps, e2e or load scenarios           | `test-engineer`     |
| Anything touching auth, cookies, tokens, SSRF, uploads, headers or secrets | `security-reviewer` |
| Anything touching prices, orders, payments, credits, refunds or webhooks   | `billing-reviewer`  |

Use the project commands to scaffold consistently: `/new-module`, `/new-feature`, `/new-migration`, and `/review-pr` before asking for review.

## Before you finish

- Run `pnpm verify` and fix every failure. Run `pnpm test:integration` when you touched the server and Docker is available.
- Run `pnpm contract:generate` and commit the result when the API changed.
- Never weaken a check to make it pass: do not add ignores, lower thresholds, skip tests, disable rules or loosen types. Fix the code.
- Never add comments. If code needs explaining, rename or restructure it.
