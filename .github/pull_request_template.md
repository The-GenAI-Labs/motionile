## Summary

_What changes and why. Link the phase or issue._

## How it was verified

_Commands run locally, and anything verified only in CI._

## Definition of done

- [ ] `pnpm verify` passes locally
- [ ] Tests added or updated at the right layer (unit, integration, e2e, security, load)
- [ ] No comments added outside the allowed machine directives
- [ ] Module boundaries respected (`pnpm check:boundaries`)
- [ ] API contract regenerated and committed (`pnpm contract:generate`) when the API changed
- [ ] At most one reversible, expand/contract migration
- [ ] `docs/context.md`, ADRs and `AGENTS.md` updated when a decision changed
- [ ] Commit messages follow Conventional Commits
- [ ] No secrets, tokens or personal data in code, logs or fixtures
