# 5. No code comments, enforced by tooling

- Status: Accepted
- Date: 2026-10-13

## Context

Comments drift from the code they describe, hide unclear naming and accumulate commented-out code and stale TODOs. Much of this codebase will be written and maintained with coding agents, which copy whatever patterns they see.

## Decision

Authored files contain no comments: Python, TypeScript, JavaScript, CSS, YAML, TOML, shell, Dockerfiles and SQL. The only exceptions are machine directives: `# noqa: <code>`, `# type: ignore[<code>]`, `# pragma: no cover`, shebang lines, `// eslint-disable-next-line <rule>`, `// @ts-expect-error <reason>` and triple-slash references.

Enforcement:

- `packages/config/eslint/rules/no-comments.mjs` reports every other comment in TypeScript and JavaScript, and `eslint-comments/no-use` blocks file-wide disables that would silence it.
- `scripts/check_no_comments.py` covers Python through `tokenize` and the other languages through quote-aware scanners.
- Both run in lint-staged and in CI, and both have tests with passing and failing fixtures.

Generated files, lockfiles and test fixtures are excluded. Markdown is documentation, not code, and is not checked.

## Consequences

- Intent has to be expressed through names, small functions and types.
- Explanations of decisions live in ADRs, `docs/` and pull request descriptions.
- Tools that generate code with comments (for example shadcn/ui) need the comments removed after generation.
