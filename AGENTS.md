# AGENTS.md

Operational rules for any coding agent working in this repository. `docs/context.md` is the source of truth; this file is its enforceable summary. When the two disagree, follow `docs/context.md` and fix this file in the same pull request.

## Project

- Motionile turns a topic or question into a narrated, animated explainer video (10 seconds to 2 minutes) and publishes it through official platform APIs.
- Read [`docs/context.md`](docs/context.md) before starting work and [`docs/roadmap.md`](docs/roadmap.md) to see which phase you are in. Read the ADRs in [`docs/adr/`](docs/adr/) that touch your change.
- Build only what the current phase lists. Never add placeholder files, `.gitkeep` files or empty folders.

## Brand

- Write the product name exactly as **Motionile** in visible text.
- Use `@motionile/*` for npm packages, `motionile` for the Python package, `motionile-api` and `motionile-worker` for images, `mo_` for cookies.
- Use the single dark monochrome theme. Never add a light mode, theme toggle or theme provider.
- Use the CSS tokens in `apps/web/src/app/globals.css` through Tailwind utilities. Never write raw hex values in components.
- Use Geist Sans for UI and Geist Mono for code and numbers, both through `next/font`.
- Give every public page metadata: unique description, canonical URL, Open Graph data. Titles follow `%s · Motionile`.

## Repository map

| Path                    | Purpose                                                                                   |
| ----------------------- | ----------------------------------------------------------------------------------------- |
| `apps/web`              | Next.js App Router frontend                                                               |
| `apps/server`           | Python modular monolith: `api`, `worker` and `mcp` entrypoints, Alembic migrations, evals |
| `packages/config`       | Shared ESLint (including the `no-comments` rule), TypeScript and Prettier configs         |
| `packages/api-contract` | TypeScript types and Zod schemas generated from `apps/server/openapi.json`                |
| `tests`                 | Playwright e2e and security suites, ZAP baseline, k6 load scenarios                       |
| `deploy`                | Compose files, Caddyfile, deployment scripts, systemd units and `parameters.csv`          |
| `infra`                 | OpenTofu for AWS (`infra/aws`) and `put-parameters.sh`                                    |
| `scripts`               | Repository checks: comments, module boundaries, API contract, gitleaks                    |
| `docs`                  | Context, roadmap, ADRs, database conventions, infrastructure and runbooks                 |

## Commands

| Command                                                                     | What it does                                                   |
| --------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `pnpm install`                                                              | Install Node.js dependencies and Husky hooks                   |
| `uv sync --project apps/server`                                             | Install Python dependencies                                    |
| `pnpm dev`                                                                  | Run the web app and the API with reload                        |
| `pnpm verify`                                                               | Run every check CI runs that does not need Docker              |
| `pnpm lint`                                                                 | ESLint, ruff, comments check, module boundaries, import-linter |
| `pnpm typecheck`                                                            | tsc and pyright strict                                         |
| `pnpm test:unit`                                                            | Vitest and pytest unit tests                                   |
| `pnpm test:integration`                                                     | pytest integration tests against testcontainers                |
| `pnpm contract:generate`                                                    | Export OpenAPI and regenerate `packages/api-contract`          |
| `pnpm contract:check`                                                       | Fail when the committed contract is out of date                |
| `pnpm format`                                                               | Format everything with Prettier and ruff                       |
| `docker compose -f deploy/compose.yml -f deploy/compose.dev.yml up --build` | Start the local stack                                          |

## No comments

- Never write comments in Python, TypeScript, JavaScript, CSS, YAML, TOML, shell, Dockerfiles, SQL, Lua, OpenTofu (`.tf`, `.hcl`) or templates (`.tftpl`). Express intent through names and structure; justify scanner exceptions in `.trivyignore.yaml` `statement` fields.
- The only allowed exceptions are machine directives: `# noqa: <code>`, `# type: ignore[<code>]`, `# pragma: no cover`, shebang lines, the `#cloud-config` header, `// eslint-disable-next-line <rule>`, `// @ts-expect-error <reason>` and triple-slash references.
- Never leave commented-out code, TODOs or dead code. Open an issue instead.
- `scripts/check_no_comments.py` and the `motionile/no-comments` ESLint rule enforce this. Never weaken either to make a check pass.

## Python

- Keep pyright strict at zero errors. Type every function and variable that is not inferred.
- Inject dependencies with `Annotated[..., Depends(...)]` aliases named `<Thing>Dep`.
- Stay async for I/O. Move blocking or CPU-heavy work to a task or a thread.
- Read settings only through `motionile.core.config`. Never read `os.environ` anywhere else.

## Module structure and boundaries

- A module under `motionile/modules/<name>` owns `router.py` (HTTP only), `schemas.py`, `service.py` (business logic and transactions), `repository.py` (SQL only), `models.py`, `dependencies.py` and `exceptions.py`.
- Import another module only through `motionile.modules.<name>`, never through its submodules.
- `core` never imports from `modules`, `engine` or `mcp`. `engine` never imports from `modules`.
- Send asynchronous side effects across modules through `core/events.py`.
- `pnpm check:boundaries` runs `scripts/check_module_boundaries.py` and import-linter.

## Auth module ownership

- `users` owns users, contacts and preferences; `access` owns roles, user roles, permissions and role permissions; `platform` owns runtime settings and feature flags; `catalog` owns categories, subcategories, topics and slug history.
- Authorization resolves live roles and permissions through a Redis cache backed by the database. Invalidate it on role changes; access-token role claims are display hints only.
- `auth` owns credentials, OAuth identities and sessions; `notifications` owns queued email and WhatsApp delivery and no tables.
- Access JWT `sid` is the session family ID. Revocation denies the family for the access lifetime plus verification leeway.
- OAuth linking starts with the CSRF-protected POST endpoint; ordinary sign-in uses the GET redirect.
- Password reset uses OTP and a verification ticket. Refresh requires family-bound CSRF; OAuth uses a separate ten-minute Lax binding cookie.
- Notifications carry encrypted queue payloads, use after-commit enqueueing, and never log codes or destinations. SES v2 is the additional instance-role AWS SDK adapter.

## API design

- Version routes under `/v1`. Health checks live at `/health/live` and `/health/ready`.
- Use camelCase on the wire through the Pydantic alias generator; keep Python snake_case.
- Request schemas use `extra="forbid"`, strip whitespace and bound every string, number and list.
- Return errors as RFC 9457 `application/problem+json` with a stable `code`; `type` is `urn:motionile:problem:<code>`. Raise `AppError` subclasses from `motionile.core.errors`; never build error bodies by hand.
- Paginate lists with cursors.
- Require an `Idempotency-Key` header on endpoints that create money or credit side effects through the `idempotent(scope)` dependency and `IdempotencyGuard.respond()`.
- Declare `response_model`, status codes and a rate-limit policy on every route. Operation IDs are generated as `<tag>_<function_name>`.
- Keep test-only endpoints in the test-support router; it mounts only in `local` and `ci` and is excluded from the contract.
- Regenerate and commit the API contract whenever the OpenAPI schema changes.

## Database

- Generate UUIDv7 primary keys in the application.
- Give every table `created_at` and `updated_at` as `timestamptz` in UTC.
- Soft delete (`deleted_at`) only `users` and `skills`.
- Store statuses as `text` with a `CHECK` constraint. Never use native Postgres enums.
- Store money as `bigint` paise and credits as `bigint`.
- Use `jsonb` only for payloads and metadata, never for queried fields.
- Rely on the SQLAlchemy naming convention in `motionile.core.db`. Index every foreign key and choose `ON DELETE` explicitly.
- Ship at most one migration per pull request. Make it reversible and expand/contract only. Wrap explicit constraint names in `op.f()` so the naming convention does not prefix them twice.
- Details live in [`docs/db/conventions.md`](docs/db/conventions.md).

## Security

- Microsoft OAuth subjects include the tenant ID; validate the signing-key issuer against that tenant.

- Send all outbound HTTP through `SafeHttpClient`.
- Read secrets only as `SecretStr` settings; add every value without a safe default to `Settings.deployment_problems()`.
- Never put secrets in logs, errors, responses or the frontend bundle.
- Hash refresh tokens and OTPs. Encrypt third-party credentials with AES-GCM.
- Authorize in the service layer and always include the owner in resource lookups.
- Never trust client-supplied prices, amounts, roles or user IDs.
- Never read `.env` files other than `.env.example`.

## Infrastructure

- Change AWS resources only through `infra/aws`. Staging and production call the same `environment` module and differ only by variables; never add environment-specific resources to an `envs/*` root.
- Pin OpenTofu (`~> 1.13.1`) and the AWS provider exactly in roots; commit `.terraform.lock.hcl` with hashes for every platform. Never commit `*.tfvars`, state or plans.
- Never put a secret in OpenTofu: secrets are SecureString parameters listed with source `owner` in `deploy/parameters.csv` and uploaded with `infra/scripts/put-parameters.sh`. Non-secret values OpenTofu knows are written as `infra` parameters.
- Scope every IAM policy to ARNs and conditions; `*` resources only where AWS supports nothing narrower.
- Run `tofu fmt`, `tofu validate`, tflint and the Trivy configuration scan before pushing; the `infra` CI job enforces them along with shellcheck and actionlint.
- Update the runbook in `docs/runbooks/` in the same pull request as any change to how infrastructure is applied or operated.

## Billing

- Read prices only from the `products` table.
- Record every credit change as an append-only `credit_ledger` row with `balance_after` and a unique `idempotency_key`.
- Verify webhooks on the raw body, store them, deduplicate by event ID and process them asynchronously.
- Drive status changes through explicit state machines and record stale events as `ignored`.

## Frontend

- Default to Server Components. Add `"use client"` only to leaf components that need it.
- Never call Axios from components. Data flows `features/<x>/api` (Zod-validated) → `features/<x>/hooks` (TanStack Query) → components.
- Build query keys only from each feature's `query-keys.ts`.
- Do not add `memo`, `useMemo` or `useCallback` unless a profile proves a gain; the React Compiler is on.
- Virtualize long lists. Load heavy components with `next/dynamic`.
- Keep server data in TanStack Query and UI state in Zustand.
- Build forms with react-hook-form and Zod resolvers.
- Use semantic HTML, label every input, keep focus visible and support keyboard navigation.
- Validate public environment variables in `src/config/env-schema.ts`; the build fails on invalid values.

## Testing

- Ship every change with tests at the right layer.
- Server unit tests use `tests/fakes` and never touch real I/O.
- Server integration tests use testcontainers Postgres, Redis and MinIO; each test runs in a rolled-back transaction unless it must observe committed concurrent transactions, in which case its fixture truncates the mutable tables.
- Root `tests/` holds e2e, security and load tests against a running stack.
- CI runs with `PROVIDERS_MODE=fake` and Cloudflare's dummy Turnstile keys.

## Git workflow

- Branch from `develop` as `phase-<n>/<slug>` or `feat/<slug>`.
- Open pull requests into `develop`. Release by opening a pull request from `develop` into `prod`.
- Write Conventional Commits (`feat`, `fix`, `build`, `ci`, `docs`, `test`, `refactor`, `chore`). commitlint enforces them.
- Never push directly to `develop` or `prod`, never force-push shared branches and never skip hooks.
- Merge only when every CI check is green; branch protection requires `ci-ok`.

## Definition of done

- `pnpm verify` passes locally and every CI job is green.
- Tests cover the change at the right layer.
- `docs/context.md`, the relevant ADRs and this file are updated when a decision changed.
- The API contract is regenerated and committed when the API changed.
- No comments, dead code or TODOs were added.
