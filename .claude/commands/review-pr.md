---
description: Review the current branch against the Motionile definition of done before opening or merging a pull request
argument-hint: "[base branch, defaults to develop]"
---

Review the current branch against `${ARGUMENTS:-develop}`.

1. Run `git diff --stat ${ARGUMENTS:-develop}...HEAD` and read every changed file.
2. Check the definition of done in `AGENTS.md`:
   - `pnpm verify` passes; run it.
   - Tests exist at the right layer for every behaviour change.
   - No comments, dead code or TODOs; `pnpm check:comments` passes.
   - Module boundaries hold; `pnpm check:boundaries` passes.
   - The API contract is regenerated when routes or schemas changed; `pnpm contract:check` passes.
   - At most one migration, reversible and expand/contract.
   - `docs/context.md`, ADRs and `AGENTS.md` reflect any changed decision.
   - Commit messages follow Conventional Commits.
3. Delegate to `security-reviewer` when auth, cookies, tokens, uploads, outbound HTTP or headers changed, and to `billing-reviewer` when prices, payments, credits or webhooks changed.
4. Report findings ordered by severity with file and line, then a one-line verdict: ready, or blocked with the list of blockers.
