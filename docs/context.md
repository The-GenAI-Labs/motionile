# Motionile — Project Context

This document is the single source of truth for what Motionile is and how it is built. Every phase, every agent and every contributor follows it. When a later decision changes something here, this file is updated in the same pull request.

---

## 1. Product

Motionile turns a topic or a question into a short animated explainer video, 10 seconds to 2 minutes long, with narration. An AI pipeline plans a storyboard, writes the narration, generates narration audio, then generates animated HTML/CSS/GSAP scenes timed exactly to that audio. Headless Chromium records the scenes frame by frame and ffmpeg merges frames and audio into an MP4. Users can then publish the video to social platforms and blogs in one click.

### Features

1. **Catalog.** Categories → subcategories → topics, fully database-driven and admin-editable. Seed categories: Education; Tech → Frontend, Backend, System Design, DevOps, Concepts, Applied AI, ML, Blockchain/Web3, Cybersecurity. Users pick a topic or type any free-text query.
2. **Context assembly.** Before generating, the system gathers the user's preferences and memory, the relevant skills (system and user-created), RAG documents and, when needed, web search results.
3. **Storyboard first, with human approval.** The LLM produces a structured storyboard (scenes with goal, narration, visual description, target duration, skills used). The user can review, edit, reorder and approve it before anything expensive runs.
4. **Narration before visuals.** Text-to-speech runs per scene and returns word-level timestamps and real durations. Scene animations are then timed to the actual audio. Users can clone their own voice after a consent step.
5. **Scene generation.** Each scene becomes HTML/CSS/GSAP. Scenes are composed into one page that exposes a paused GSAP master timeline as `window.__timeline`.
6. **Validation and repair.** Generated HTML is sanitized, rendered in a network-isolated sandbox and checked (lint, overflow, overlap, contrast, sync, vision-model review). Failing scenes are regenerated at most twice.
7. **Rendering.** Playwright seeks the timeline frame by frame (30 fps) and screenshots; ffmpeg encodes H.264, concatenates scene audio, normalizes loudness to −16 LUFS, ducks background music and optionally burns in subtitles. Formats: 16:9, 9:16 and 1:1, produced from the same composition by changing the viewport.
8. **Library and secure playback.** Videos live in a private S3 bucket and are served through CloudFront with signed cookies scoped to the owner's path.
9. **Custom skills.** Users create skills in Claude's skill format (`SKILL.md` with `name` and `description` frontmatter, a markdown body, optional assets). Skills are versioned, scanned, sanitized, enabled or disabled, and can be pinned to a generation.
10. **Billing.** Razorpay subscriptions and one-time credit packs. Credits live in expiring lots; every generation reserves, commits and releases them through an append-only ledger.
11. **Publishing.** Official APIs only: YouTube, LinkedIn, Instagram (Reels), Facebook Pages, Threads, X, TikTok, Dev.to, Hashnode, WordPress, Ghost, Blogger. AI writes a caption per platform. Platforms without an API (Medium, Substack) get a share kit: format downloads, copy caption, composer links and the native mobile share sheet. Stealth or headless-browser automation of user accounts is never used.
12. **MCP server.** Users connect Motionile to Claude or ChatGPT. Their own LLM subscription generates the HTML and narration using Motionile skills, then submits them; Motionile validates, voices and renders.
13. **Admin console.** Users, roles, audit logs, billing (payments, refunds, webhooks), prompts, system skills, catalog, platform specs, system settings, feature flags.
14. **Evals.** Golden datasets and quality gates for planning, visuals, safety and captions, enforced in CI.

---

## 2. Brand, design and SEO

### Name
- The product is **Motionile**. Always written exactly like that in visible text.
- Code identifiers: npm scope `@motionile/*`, Python package `motionile`, images `motionile-api` and `motionile-worker`, cookie prefix `mo_`.

### Theme
A single dark monochrome theme. There is no light mode, no theme toggle and no theme provider.

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0E0E10` | Page background |
| `--surface` | `#16161A` | Cards, sidebar, inputs |
| `--elevated` | `#1E1E23` | Dialogs, dropdowns, hover states |
| `--border` | `#2A2A30` | Dividers, input borders |
| `--text-muted` | `#8A8A93` | Hints, timestamps |
| `--text-secondary` | `#B4B4BC` | Body copy, labels |
| `--text` | `#F2F2F3` | Headings, primary text |
| `--accent` | `#FAFAFA` | Primary buttons (accent background, `--bg` text) |
| `--ring` | `rgb(255 255 255 / 0.4)` | Focus outline |
| `--danger` | `#E5484D` | Errors and failures only |
| `--success` | `#3DD68C` | Success states only |

- `color-scheme: dark` on the root and a `theme-color` meta tag of `#0E0E10`.
- Fonts: Geist Sans for UI, Geist Mono for code and numbers, both through `next/font`.
- shadcn/ui CSS variables are mapped to these tokens; components never use raw hex values.
- The default video style skill uses the same palette.

### SEO
- Title template `%s · Motionile`; default title "Motionile — AI Animated Explainer Videos".
- One unique description per page, generated from catalog data where applicable.
- Canonical URL on every page; lowercase kebab-case slugs.
- Public explore pages (`/explore`, `/explore/[category]`, `/explore/[category]/[subcategory]`, `/explore/[category]/[subcategory]/[topic]`) are statically generated with ISR.
- `sitemap.ts` built from the catalog; `robots.ts` blocks `/admin`, the authenticated user area and auth pages.
- Open Graph images per page via `next/og` in the brand style.
- JSON-LD: `Organization` and `SoftwareApplication` on the home page, `BreadcrumbList` on explore pages, `VideoObject` on public video pages.

---

## 3. Architecture decisions

| Decision | Choice |
|---|---|
| Backend style | Python modular monolith: one codebase, three entrypoints (`api`, `worker`, `mcp`) |
| Frontend | Next.js App Router on Vercel, also runnable from its own Dockerfile |
| Background jobs | `procrastinate`, a Postgres-backed queue. No separate broker. |
| Queues | `default`, `billing`, `publishing` (run by `worker-default`); `generation` (run by `worker-generation`, [ADR 0034](adr/0034-generation-queue-for-long-running-graphs.md)); `render` (run by `worker-render`) |
| Database | PostgreSQL 17 with pgvector. Local Docker in development; Neon or RDS in staging and production, chosen only by `DATABASE_URL` |
| Redis | Rate limits, OTP, OAuth state, revocation denylist, verification tickets, cache, SSE pub/sub. `maxmemory-policy noeviction`, every key has a TTL |
| Auth | Custom, in FastAPI: cookie-based JWT access tokens plus rotating opaque refresh tokens |
| Payments | Razorpay with an append-only credit ledger |
| Storage | S3 API only, with configurable endpoint (AWS S3, MinIO, R2) |
| Media delivery | CloudFront signed cookies plus WAF Referer rule; presigned-URL fallback for non-AWS |
| Publishing | Official platform APIs only |
| Cloud | AWS, with no lock-in: configuration by environment variables, AWS SDK used only inside storage, SES email and media-delivery adapters, OpenTofu only under `infra/aws` |
| Code comments | None. Code must explain itself through naming and structure |

Each of these has an ADR in `docs/adr/`.

---

## 4. Tech stack

**Version policy:** use the latest stable release of every tool and library at the time it is added, verify it against the registry, and pin exact versions through lockfiles.

| Area | Tools |
|---|---|
| Runtime | Node.js 24 LTS, pnpm 10, Python 3.13, uv |
| Monorepo | Turborepo, pnpm workspaces, uv project in `apps/server` |
| Frontend | Next.js (latest stable), React 19 with React Compiler, TypeScript strict, Tailwind CSS v4, shadcn/ui, Zod, Axios, TanStack Query, TanStack Virtual, react-hook-form, Zustand (UI state only), `@marsidev/react-turnstile`, `@microsoft/fetch-event-source` |
| API contract | FastAPI OpenAPI → `@hey-api/openapi-ts` generating TypeScript types and Zod schemas into `packages/api-contract` |
| Backend | FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2 async, asyncpg, Alembic, redis-py, httpx, structlog, orjson, `uuid-utils` (UUIDv7) |
| Security | argon2-cffi, PyJWT with cryptography (EdDSA), provider protocols, phonenumbers, email-validator |
| Jobs | procrastinate |
| AI | LangGraph with Postgres checkpointer, LiteLLM, pgvector, Tavily or Exa, DeepEval, Langfuse |
| Media | Playwright (Chromium), ffmpeg, GSAP (bundled locally), ElevenLabs and OpenAI TTS behind a provider interface |
| Payments | Razorpay REST API |
| Testing | pytest, pytest-asyncio, testcontainers, Vitest, Testing Library, Playwright Test, k6, OWASP ZAP |
| Quality | ruff, pyright strict, import-linter, ESLint flat config with typescript-eslint strict-type-checked, Prettier, Husky, lint-staged, commitlint, gitleaks, pip-audit, pnpm audit, Trivy |
| Infra | Docker, Docker Compose, Caddy, AWS (EC2 + EBS, ECR, S3, CloudFront, WAF, SES, SSM, CloudWatch, later ECS and Auto Scaling), OpenTofu, GitHub Actions with OIDC |

---

## 5. Repository structure

```
motionile/
├── .claude/
│   ├── settings.json
│   ├── agents/
│   ├── commands/
│   └── skills/
├── .github/
│   ├── workflows/            ci.yml  _deploy.yml  deploy-staging.yml  deploy-production.yml  nightly.yml
│   ├── dependabot.yml
│   └── pull_request_template.md
├── .husky/                   pre-commit  commit-msg  pre-push
├── apps/
│   ├── web/
│   └── server/
├── packages/
│   ├── api-contract/
│   └── config/               eslint/  typescript/  prettier/
├── tests/                    e2e/  security/  load/  support/
├── deploy/                   compose.yml  compose.dev.yml  compose.prod.yml  Caddyfile  parameters.csv  scripts/  systemd/
├── infra/
│   ├── aws/                  bootstrap/  modules/  envs/staging/  envs/production/
│   └── scripts/              put-parameters.sh
├── docs/                     context.md  roadmap.md  infrastructure.md  billing.md  adr/  db/  runbooks/
├── scripts/                  check_no_comments.py  check_module_boundaries.py  generate-api-contract.sh
├── AGENTS.md
├── CLAUDE.md
├── commitlint.config.mjs
├── lint-staged.config.mjs
├── turbo.json
├── pnpm-workspace.yaml
└── package.json
```

### Frontend: `apps/web`

```
apps/web/
├── public/                   images/  icons/
├── src/
│   ├── app/
│   │   ├── layout.tsx  providers.tsx  globals.css  not-found.tsx  error.tsx  global-error.tsx
│   │   ├── sitemap.ts  robots.ts  opengraph-image.tsx
│   │   ├── (public)/
│   │   │   ├── layout.tsx  page.tsx
│   │   │   ├── pricing/  about/  contact/
│   │   │   ├── explore/  [category]/  [subcategory]/  [topic]/
│   │   │   ├── v/[shareId]/
│   │   │   └── legal/  terms/  privacy/  refund-policy/
│   │   ├── (auth)/
│   │   │   ├── layout.tsx
│   │   │   └── login/  register/  verify/  forgot-password/  reset-password/  refresh/
│   │   ├── (user)/
│   │   │   ├── layout.tsx
│   │   │   ├── dashboard/  create/  jobs/[jobId]/  library/
│   │   │   ├── publish/[jobId]/  publications/
│   │   │   ├── skills/  new/  [skillId]/  versions/
│   │   │   ├── billing/  plans/  credits/  history/
│   │   │   └── settings/  profile/  security/  voices/  connections/  integrations/  memory/
│   │   ├── (super-admin)/admin/
│   │   │   ├── layout.tsx  page.tsx
│   │   │   ├── users/
│   │   ├── access/
│   │   ├── notifications/[userId]/  roles/  analytics/  audit-logs/
│   │   │   ├── billing/  payments/  refunds/  webhooks/
│   │   │   ├── catalog/  prompts/  skills/  platforms/  settings/
│   │   ├── forbidden.tsx  not-found.tsx  error.tsx  global-error.tsx  providers.tsx
│   │   └── api/health/route.ts
│   ├── components/           ui/  layouts/  shared/
│   ├── features/             auth/  catalog/  generation/  library/  publishing/  skills/  billing/  voices/  memory/  settings/  dashboard/  admin/
│   ├── lib/                  api/  auth/  query/  razorpay/  seo/  utils/  validations/
│   ├── hooks/
│   ├── stores/
│   ├── config/               env.ts  site.ts  navigation.ts
│   ├── types/
│   └── proxy.ts
├── tests/                    setup.ts  unit/  integration/
├── Dockerfile
├── components.json  eslint.config.mjs  next.config.ts  package.json  postcss.config.mjs  tsconfig.json  vitest.config.ts
```

Every feature folder follows the same shape: `api/<feature>.api.ts`, `components/`, `hooks/`, `schemas/<feature>.schema.ts`, `types/<feature>.types.ts`, `query-keys.ts`.

### Backend: `apps/server`

```
apps/server/
├── src/motionile/
│   ├── entrypoints/          api.py  worker.py  mcp.py
│   ├── core/
│   │   ├── config.py  db.py  redis.py  logging.py  errors.py  schemas.py  clock.py  events.py  pagination.py  ids.py
│   │   ├── security/         jwt.py  passwords.py  tokens.py  csrf.py  cookies.py  rbac.py  encryption.py
│   │   ├── middleware/       request_id.py  security_headers.py  origin_guard.py
│   │   ├── ratelimit/        limiter.py  policies.py  sliding_window.lua
│   │   ├── bot/              turnstile.py
│   │   ├── http/             safe_client.py
│   │   ├── storage/          base.py  s3.py
│   │   └── tasks/            app.py  registry.py
│   ├── modules/
│   │   ├── auth/             router.py  schemas.py  service.py  repository.py  models.py  dependencies.py  exceptions.py  verification.py  oauth/  otp/
│   │   ├── users/
│   │   ├── catalog/
│   │   ├── platform/
│   │   ├── generation/       router.py  schemas.py  service.py  repository.py  models.py  tasks.py  stream.py  estimator.py
│   │   ├── media/            router.py  service.py  renditions.py  delivery/
│   │   ├── voices/
│   │   ├── skills/           router.py  admin_router.py  schemas.py  service.py  repository.py  models.py  validator.py  scanner.py  packager.py
│   │   ├── memory/
│   │   ├── billing/          router.py  admin_router.py  webhook_router.py  schemas.py  models.py  repository.py  exceptions.py  tasks.py  services/  razorpay/
│   │   ├── credits/          router.py  schemas.py  service.py  repository.py  models.py  domain.py  dependencies.py  exceptions.py  tasks.py
│   │   ├── publishing/       router.py  schemas.py  service.py  repository.py  models.py  tasks.py  captions.py  providers/
│   │   ├── integrations/
│   │   └── audit/
│   ├── engine/
│   │   ├── ai/               graphs/  nodes/  llm/  guardrails/  prompts/  skills/  rag/
│   │   ├── audio/            providers/  voice_clone.py
│   │   └── render/           runtime/  sanitize.py  capture.py  encode.py  mux.py
│   └── mcp/                  server.py  auth.py  tools/
├── tests/
│   ├── conftest.py
│   ├── factories/
│   ├── fakes/
│   ├── unit/                 core/  modules/  engine/
│   └── integration/          conftest.py  api/  repositories/  tasks/  webhooks/  engine/
├── evals/                    datasets/  planner/  visual/  safety/  captions/  run.py  thresholds.yaml
├── migrations/
├── alembic.ini  pyproject.toml  uv.lock  Dockerfile  package.json
```

### Root tests: `tests/`

```
tests/
├── package.json  playwright.config.ts
├── e2e/                      pages/  fixtures/  auth/  generation/  billing/  skills/  publishing/
├── security/
│   ├── api/                  csrf  origin  cors  rate-limit  idor  ssrf  jwt-tamper  refresh-reuse  turnstile  webhook-signature  skill-upload  token-leak
│   └── zap/
├── load/                     lib/  scenarios/  thresholds.js
└── support/                  seed.ts  api.ts  signed-webhook.ts  otp-inbox.ts
```

Folders are created by the phase that first puts a real file in them. No placeholder or `.gitkeep` files.

---

## 6. Engineering rules

These rules are mirrored in `AGENTS.md` and enforced by tooling wherever possible.

### General
- No comments in any authored file: Python, TypeScript, JavaScript, CSS, YAML, TOML, shell, Dockerfile, SQL. Allowed exceptions are machine directives only: `# noqa: <code>`, `# type: ignore[<code>]`, `# pragma: no cover`, shebang lines, `// eslint-disable-next-line <rule>`, `// @ts-expect-error <reason>`, triple-slash references. Enforced by `scripts/check_no_comments.py` and a custom ESLint rule.
- Names carry meaning. Small functions with a single job. No dead code, no commented-out code, no TODOs in code (use issues).
- Every change ships with tests at the right layer.
- Formatting is automatic and never discussed: ruff format and Prettier.

### Python
- pyright strict with zero errors; full type hints everywhere.
- Dependencies injected through `Annotated[..., Depends(...)]` aliases named `<Thing>Dep`.
- Async all the way for I/O. No blocking calls inside the event loop; CPU-heavy or blocking work goes to a task or a thread.
- Settings only through `core/config.py`; no `os.environ` anywhere else.

### Module structure and boundaries
- A module owns `router.py` (HTTP only), `schemas.py` (Pydantic), `service.py` (business logic and transactions), `repository.py` (SQL only), `models.py` (ORM), `dependencies.py`, `exceptions.py`.
- Modules communicate only through what their `__init__.py` exports. A module never imports another module's `repository`, `models` or internals.
- `core` imports nothing from `modules`, `engine` or `mcp`. `engine` imports nothing from `modules`.
- Asynchronous side effects across modules go through `core/events.py`.
- Enforced by import-linter plus `scripts/check_module_boundaries.py`.

### API design
- Versioned under `/v1`. Health checks at `/health/live` and `/health/ready`.
- JSON uses camelCase on the wire through a Pydantic alias generator; Python stays snake_case.
- Request schemas use `extra="forbid"` and strip whitespace; every string, number and list is bounded.
- Errors are RFC 9457 `application/problem+json` with a stable machine-readable `code`, a `type` of `urn:motionile:problem:<code>`, the `requestId`, and camelCase `errors[].field` paths for validation failures.
- Lists use cursor pagination.
- Mutating endpoints that create money or credit side effects require an `Idempotency-Key` header.
- Every route declares `response_model`, status codes and a rate-limit policy. Most routes use `api.default`, public cached catalog reads use `catalog.read`, and sensitive operations use stricter policies.
- OpenAPI operation IDs are `<tag>_<function_name>` and become the generated TypeScript names. Error responses are documented as `application/problem+json`.
- Idempotency records live in Postgres (`idempotency_records`): one atomic upsert claims a key per scope and user, a replay returns the stored status, body and `Location`/`ETag` headers with `Idempotent-Replayed: true`, a different body under the same key is `409 idempotency_key_reused`, and a request still running is `409 idempotency_request_in_progress` with `Retry-After`.
- A test-support router under `/v1/_test` exists only when `APP_ENV` is `local` or `ci` and is never part of the published contract.

### Database
- Primary keys are UUIDv7 generated in the application.
- Every table has `created_at` and `updated_at` (`timestamptz`, UTC).
- Soft delete (`deleted_at`) only on `users` and `skills`.
- Status columns are `text` with a `CHECK` constraint; no native Postgres enums.
- Money is `bigint` paise. Credits are `bigint`.
- `jsonb` only for payloads and metadata, never for queried fields.
- SQLAlchemy `naming_convention` for all constraints. Every foreign key is indexed. `ON DELETE` is chosen explicitly per foreign key.
- Migrations: one per pull request, reversible, expand/contract only so a code rollback never breaks the schema. Alembic runs on psycopg; the application uses asyncpg.
- Append-only tables (`audit_log`, `credit_ledger`) are guarded by a trigger; only a retention job that sets `motionile.allow_purge = 'on'` for its transaction may delete.

### Security
- All outbound HTTP goes through `SafeHttpClient`.
- Secrets never appear in logs, errors, responses or the frontend bundle.
- Tokens and third-party credentials are stored hashed (refresh tokens, OTPs) or encrypted with AES-GCM (OAuth tokens for connectors).
- Authorization is checked in the service layer, not only in routers. Resource lookups always include the owner.
- Authorization resolves current roles and permissions from a Redis cache backed by Postgres. Role and permission changes invalidate the affected cache entries immediately; token role claims are display hints only.
- Never trust client-supplied prices, amounts, roles or user IDs.

### Billing
- Prices, credits and plan IDs come only from the `products` table; products are immutable once used.
- Every credit change is an append-only `credit_ledger` row with `delta`, `reserved_delta`, `balance_after`, `reserved_after` and a unique `idempotency_key`, written in one transaction that locks the wallet and then its lots in a fixed order.
- A payment is settled only after the server confirmed it with Razorpay or from a verified webhook, never on a client callback alone.
- Webhooks are verified on the raw body, stored, deduplicated by event ID and processed asynchronously.
- Status changes follow explicit state machines; stale events are recorded as `ignored`, but money received is never ignored.

### Frontend
- Server Components by default; `"use client"` only on leaf components that need it.
- Components never call Axios directly. Data flows: `features/<x>/api` (Zod-validated in and out) → `features/<x>/hooks` (TanStack Query) → components.
- Query keys come only from each feature's `query-keys.ts` factory.
- React Compiler is enabled. No manual `memo`, `useMemo` or `useCallback` unless a profile proves a gain.
- Long lists are virtualized; heavy components (player, editors, checkout) load with `next/dynamic`.
- Zustand holds UI state only; server data lives in TanStack Query.
- Forms use react-hook-form with Zod resolvers.
- Accessibility: semantic HTML, labels on every input, visible focus states, keyboard navigation.
- Every public page exports metadata following the SEO rules.

### Testing
- Server unit tests use `tests/fakes`, never real I/O.
- Server integration tests use testcontainers Postgres, Redis and MinIO; each test runs in a rolled-back transaction unless it must observe committed concurrent transactions, in which case its fixture truncates the mutable tables afterwards.
- Root `tests/` holds e2e, security and load tests against a running stack.
- CI runs external providers in `PROVIDERS_MODE=fake`: fake LLM, TTS, OTP channels, Razorpay and publishing providers; Cloudflare's dummy Turnstile keys.

### Git
- Branches: `phase-<n>/<slug>` or `feat/<slug>` → pull request into `develop` → release pull request from `develop` into `prod`. `develop` deploys to staging and `prod` deploys to production.
- Conventional Commits, enforced by commitlint.
- Pull requests merge only with every CI check green.

---

## 7. Auth

### Ownership

`users` owns users, contacts and preferences; `access` owns roles, user roles, permissions and role permissions; `auth` owns credentials, OAuth identities and sessions; `platform` owns runtime system settings and feature flags; `catalog` owns the exact category → subcategory → topic hierarchy and slug history; `notifications` owns transactional email and WhatsApp delivery with no tables. Modules communicate through public interfaces and domain events.

### Tokens and cookies

| Cookie | Content | Attributes | Lifetime |
|---|---|---|---|
| `__Secure-mo_at` | Access JWT (EdDSA) with `sub`, `sid`, `roles`, `iss`, `aud`, `iat`, `exp`, `jti` | `Domain=.<root>`, HttpOnly, Secure, SameSite=Lax, Path=/ | 15 minutes |
| `__Secure-mo_rt` | Opaque 256-bit refresh token; only its SHA-256 hash is stored | Host-only on the API, HttpOnly, Secure, SameSite=Strict, `Path=/v1/auth` | 7 days idle, 60 days absolute |
| `__Secure-mo_vt` | Verification ticket for first-time OTP | Host-only on the API, HttpOnly, Secure, SameSite=Strict, `Path=/v1/auth` | 10 minutes |
| `__Secure-mo_oauth` | Browser binding for single-use OAuth state | Host-only, HttpOnly, Secure, SameSite=Lax, Path=/v1/auth | 10 minutes |
| `mo_csrf` | CSRF token, HMAC-bound to the session | `Domain=.<root>`, Secure, SameSite=Lax, readable by JS | Session |
| `mo_auth` | Access token expiry timestamp only (a hint, not a secret) | `Domain=.<root>`, Secure, SameSite=Lax, readable by JS | Matches the access token |

- Local/CI fake-provider tests may shorten access lifetime with `AUTH_TEST_ACCESS_SECONDS`; deployed environments reject it.
- The Next.js server verifies the access JWT with the API's public key from `/v1/auth/jwks.json`.
- Every refresh rotates the refresh token. The successor's idle expiry is `min(now + 7 days, absolute_expires_at)`.
- Presenting an already-rotated refresh token outside a 10-second grace window revokes the whole session family.
- `sid` always identifies the session family, including after rotation. Revoked families are denied in Redis for 15 minutes plus the five-second JWT verification leeway.
- Concurrent refreshes within ten seconds return `refresh_conflict` without revocation; older reuse revokes the family immediately.
- The OAuth binding cookie is separate from the Strict OTP ticket so cross-site provider callbacks can present it ([ADR 0016](adr/0016-oauth-browser-binding.md)).

### Flows
- **Register:** email or phone plus password and Turnstile → user `pending_verification` → OTP sent (email via SES, phone via WhatsApp authentication template) → verification ticket cookie → verify code → user `active` → session.
- **Login with password:** Turnstile → argon2id check → if the contact is unverified, respond `403 verification_required`, set a ticket and send an OTP → otherwise create a session.
- **OTP login:** for verified contacts; 6 digits, HMAC-hashed in Redis for 5 minutes, at most 5 attempts, 60-second resend cooldown.
- **OAuth:** Google, GitHub, Microsoft with PKCE, state and nonce in Redis for 10 minutes, redirect target allowlist, account linking only on a provider-verified email. Microsoft subjects are tenant-qualified and signing-key issuers must match the token tenant.
- **Password reset:** six-digit OTP, HMAC-hashed with a server pepper, five-minute expiry and five attempts, referenced by the ten-minute verification ticket. Reset revokes every family; authenticated password change keeps only the current family ([ADR 0015](adr/0015-otp-password-reset.md)).
- **Sessions:** list active sessions, revoke one, revoke all.

### Delivery and abuse controls

Transactional notifications are encrypted before being queued after commit on `default`, with retries and higher OTP priority. SES v2 uses the instance role; local live email uses SMTP/Mailpit. WhatsApp uses approved authentication and security-notice templates through an allowlisted SafeHttpClient. Fake deliveries expose an expiring inbox only in local/CI ([ADR 0014](adr/0014-transactional-notifications.md)).

Password login uses argon2id and a dummy verification for unknown accounts. Ten failures in an hour lock password login for fifteen minutes without blocking OTP. New passwords use the HIBP k-anonymity API, failing open with a redacted warning on provider failure. Public registration, OTP requests and forgot-password use the same challenge shape for known and unknown contacts. Correct credentials may disclose verification or suspension status. All contacts in session responses are masked.

### Frontend session handling
- Proactive refresh 60 seconds before `mo_auth` expiry while the tab is visible, guarded by a Web Lock across tabs.
- On `401 token_expired`, one shared refresh, then retry the original request once.
- The refresh request never triggers another refresh.
- If refresh fails, the session-expiry handler runs once: clear the query cache and redirect to `/login?next=<relative path>&reason=expired`.
- OAuth linking starts with a CSRF-protected POST returning the authorization URL; ordinary sign-in uses GET redirects.
- Server guard in `(user)/layout.tsx`: valid JWT renders; expired JWT with the hint cookie redirects to `/refresh?next=`; `/refresh` attempts exactly one refresh and falls back to `/login`, never looping.

### Request protection
- **CSRF:** SameSite cookies, a required allowlisted Origin (Referer fallback) on every unsafe auth request, and a family-bound HMAC double-submit token. Refresh checks CSRF against its refresh-token family even after access expiry. Only register, login, contact verification, OTP request/verify/resend, forgot and reset omit double-submit; refresh is checked inside the session service. OAuth linking start also requires CSRF.
- **CORS:** explicit origin allowlist (`CORS_ALLOWED_ORIGINS`, https only when deployed), credentials allowed, no wildcards.
- **Origin guard:** state-changing requests from non-allowlisted origins are rejected (Referer as fallback).
- **SSRF:** https only, DNS resolved and private, loopback, link-local and metadata ranges blocked, redirects re-validated, timeouts and size caps. EC2 requires IMDSv2 with a hop limit of 2 so containers can use the instance role ([ADR 0011](adr/0011-imdsv2-hop-limit-two.md)); `SafeHttpClient` blocks the metadata addresses and the render sandbox blocks all network access except the bundled runtime.
- **Turnstile** on register, login, OTP send, forgot-password and contact. Verified server-side with remote IP, hostname and action checks.
- **Security headers:** HSTS, `nosniff`, `Cache-Control: no-store` on auth responses; the web app sets a CSP with `frame-ancestors 'none'` and `Referrer-Policy: strict-origin-when-cross-origin`.

### Rate-limit policies (Redis sliding window, atomic Lua)

| Policy | Limit |
|---|---|
| `auth.register` | 3/hour per IP and per normalized identifier |
| `auth.password.change` | 5/hour per user |
| `auth.login` | 5/min per IP+identifier, 30/hour per IP |
| `auth.otp.send` | 1/60 s and 5/hour per destination, 15/hour per IP |
| `auth.otp.verify` | 5 attempts per code |
| `auth.refresh` | 30/min per session |
| `api.default` | 120/min per user, 60/min per IP when unauthenticated |
| `catalog.read` | 600/min per IP for cached public catalog and billing product reads and static generation |
| `jobs.create` | 5/min per user; at most `jobs.max_active_per_user` (2) active jobs |
| `jobs.write` | 30/min per user (storyboard edits, approve, regenerate, cancel, delete) |
| `share.view` | 120/min per IP (public share page; requests carrying the internal secret skip it) |
| `share.count` | 60/min per IP (browser view counter) |
| `share.manage` | 30/hour per user (create and revoke share links) |
| `billing.order.create` | 10/min per user |
| `skills.write` | 20/hour per user |
| `prompts.write` | 20/hour per user (prompt drafts, activations, rollbacks and evaluation starts) |
| `media.session` | 60/min per user |
| `media.upload` | 30/hour per user |
| `music.write` | 20/hour per user |
| `render.create` | 10/hour per user |
| `voices.clone` | 10/hour per user (opening a cloning attempt) |
| `voices.upload` | 60/hour per user (consent recording and sample uploads) |
| `publishing.publish` | 30/hour per user |
| `mcp.submit` | 10/hour per API key |
| `webhooks.razorpay` | 600/min |

Every 429 includes `Retry-After` and `RateLimit-*` headers. Real client IPs are trusted only from the reverse proxy.

---

## 8. Billing (Razorpay)

Billing and credits are two modules: `credits` owns the wallet, lots, reservations, ledger and usage records; `billing` owns products, customers, orders, payments, subscriptions, refunds, webhook events and reconciliation runs, and reaches credits only through `motionile.modules.credits`. Table designs are in `docs/db/schema.md`; the long-form flows, failure handling and diagrams are in [`billing.md`](billing.md).

### Credit model ([ADR 0018](adr/0018-credit-lots-and-reservations.md))
- Credits live in **lots** with a source (`purchase`, `subscription`, `admin`, `promo`), a remaining amount and an optional expiry. They are consumed from the lot expiring soonest, non-expiring lots last.
- **Reservations** hold credits for jobs, publishing and MCP submissions: `reserve` fails with `insufficient_credits` when available credits (`balance - reserved`) are short, `commit` consumes the actual amount and releases the rest, `release` returns everything, and a sweeper releases reservations past their TTL.
- Every change is one append-only `credit_ledger` row with `delta`, `reserved_delta`, `balance_after`, `reserved_after` and a unique `idempotency_key`, written in one transaction that locks the wallet first and then its lots in a fixed order.
- **Invariant:** per user, the sum of ledger deltas equals the balance and the sum of lot remainders; the sum of reserved deltas equals the reserved amount and the sum of active reservations. A nightly task verifies every wallet and alerts on any mismatch.
- Subscription credits expire at the end of their billing period unless the runtime setting `billing.subscription_rollover` is on. Purchased credits never expire.
- Callers of `reserve` must pass a `ttl` longer than the longest the job or action can run: a reservation past its TTL is released by the sweeper and can no longer be committed (`reservation_not_active`).
- Every mutating method of `CreditsService` takes the caller's session and never commits, so billing grants credits inside its own settlement transaction. `reserve`, `commit`, `clawback` and `adjust` first expire the user's due lots inside the same locked transaction, so expired credits cannot be spent between sweeps. A clawback that finds nothing to take writes no ledger row.
- Periodic tasks on the `billing` queue: `credits.expire_lots` (every 15 minutes), `credits.release_stale_reservations` (every 5 minutes), `credits.send_expiry_reminders` (hourly, once per lot) and `credits.check_integrity` (02:30 UTC, read-only, alerts through `raise_alert`).

### Products ([ADR 0019](adr/0019-product-immutability-and-versioning.md), [ADR 0020](adr/0020-gst-inclusive-pricing-and-invoices-follow-up.md))
- Prices, credits and plan IDs come only from `products`; the client sends a product code and nothing else that affects money.
- Prices are GST-inclusive and shown as "incl. GST". This phase sends receipts; GST tax invoices are a follow-up.
- `GET /v1/billing/products` is public and lists the active products grouped into `creditPacks` and `subscriptions`. It is cached in Redis for 60 seconds and answered with `Cache-Control: public, max-age=60, s-maxage=300, stale-while-revalidate=600`, a strong `ETag` and `304` for `If-None-Match`. Every product change calls `invalidate_product_cache()` and queues `billing.revalidate_products`, which revalidates the web tag `billing-products` like the catalog does.
- A product referenced by any order or subscription is financially immutable. A price change duplicates the product as a new version with a new Razorpay plan and deactivates the old one.

### Flows
- **Credit pack:** `POST /v1/billing/orders` (product code, `Idempotency-Key`) creates an `orders` row, then the Razorpay order with the product amount, `receipt` = our order ID and notes carrying user and order IDs, and returns checkout data. A timeout is recovered by looking the Razorpay order up by receipt, so a retry with the same key never creates a second order. `GET /v1/billing/orders/{id}` and `GET /v1/billing/history` serve the caller's own orders, payments and refunds. After Checkout, `POST /v1/billing/payments/verify` checks `HMAC(order_id|payment_id)`, fetches the payment from Razorpay and confirms it is captured with the order's exact amount and currency, then runs `settle_payment`. The `payment.captured` and `order.paid` webhooks and reconciliation run the same function.
- **`settle_payment`** is idempotent and the only path that settles: in one transaction it locks the order, upserts the payment by Razorpay ID, marks the order `paid` (even from `expired`), grants the product credits as a non-expiring `purchase` lot, writes the ledger and audit rows, and sends the receipt after commit. A payment whose amount or currency does not match the order is recorded without credits, the order is flagged and an alert is raised.
- **Subscription:** `POST /v1/billing/subscriptions` (product code, `Idempotency-Key`, `billing.order.create` policy) refuses a user who already has a live subscription (`409 subscription_exists`), creates the local `created` subscription and a `subscription` order in one short transaction, then the Razorpay subscription from the product's plan (`customer_notify` off, notes carry user, order and subscription IDs) and returns checkout data without any amount. A timed-out creation is recovered by listing the plan's subscriptions and matching `notes.subscriptionId`, never by creating a second one. `POST /v1/billing/subscriptions/verify` checks `HMAC(payment_id|subscription_id)`, fetches the subscription and moves it from `created` to `authenticated`; credits are granted only by webhooks. `GET /v1/billing/subscription` returns the caller's live subscription, `POST /v1/billing/subscription/cancel` cancels at the end of the period while the subscription is `active` and immediately otherwise (an `authenticated`, `pending`, `halted` or `paused` subscription has no renewal to wait for, and Razorpay only schedules cycle-end cancellations for active ones), and `POST /v1/billing/subscription/change` schedules another plan for the next cycle (`409 subscription_not_changeable` unless the subscription is active and not ending). Webhooks drive the state machine in any arrival order (`subscription.authenticated`, `activated`, `charged`, `pending`, `halted`, `cancelled`, `completed`, `paused`, `resumed` and `updated` are all handled, so enable every one of them in the Razorpay dashboard): `charged` records the payment and grants the period's credits once per payment ID (expiring at the period end unless `billing.subscription_rollover` is on), even when it arrives before `activated` and even when it is stale; every other event is ordered by `event_created_at` against `subscriptions.last_event_at`. A charge whose amount differs from the plan price is recorded, grants nothing and alerts.
- **Webhooks:** `POST /v1/webhooks/razorpay` reads the raw body, verifies `X-Razorpay-Signature` (401 `invalid_webhook_signature`, nothing stored), requires `X-Razorpay-Event-Id`, stores the event deduplicated by `(provider, event_id)`, queues `billing.process_webhook_event` on `billing` after commit and returns 200 `received` or `duplicate`; a duplicate whose row is still `received` after 60 seconds is queued again. Processing locks the event row, runs the registered handler for the event type inside a savepoint and ends `processed`, `ignored` (`unhandled_event`, `unknown_entity`, `stale`) or `failed`; failures retry with exponential backoff, alert (`billing.webhook_failed`) after `BILLING_WEBHOOK_MAX_ATTEMPTS` and can be reprocessed by an admin with `reprocess_event`. `billing.requeue_stuck_webhooks` (every 2 minutes) queues `received` events older than 2 minutes and `failed` events with attempts left when no job for them is pending.
- **Refund:** `POST /v1/admin/billing/payments/{paymentId}/refunds` (amount optional, reason required) is admin-initiated with `billing.refunds.create` and an `Idempotency-Key`. One transaction locks the payment, bounds the amount by `amount - refunded - pending refunds` (`422 refund_exceeds_refundable` with the remaining `refundablePaise`) and stores a `pending` refund; the Razorpay call happens outside the transaction and a timeout is resolved by listing the payment's refunds and matching `notes.refundId`, never by sending again. `refund.processed` (or a refund Razorpay already reports as processed) locks payment, refund and then the credits wallet, marks the refund processed, adds to `payments.refunded_paise` and claws back `min(lot.remaining, ceil(credits_granted × refund_amount ÷ payment_amount))`, capped so all clawbacks of a payment never exceed `credits_granted`, from the payment's lot. A retry with the same `Idempotency-Key` resumes the same refund (looked up first, re-sent at most once after a confirmed negative lookup). A refund made in the Razorpay dashboard for a payment known here is adopted as a `processed` refund with reason `external_refund`, and a payment settled while already refunded gets credits only for its unrefunded share. A refund never cancels a subscription.
- **Reconciliation:** every 15 minutes (`billing.reconcile_pending_orders`, recorded in `billing_reconciliation_runs`), `pending` and `created` orders older than 30 minutes are fetched from Razorpay and settled, or expired once past `expires_at`; `billing.finalize_subscriptions` (every 15 minutes) ends cancelling subscriptions whose paid period is over and expires abandoned `created` ones, but only after it re-checks the row and finds the Razorpay subscription still `created` (anything further along is synced forward instead of cancelled); `billing.reconcile_pending_refunds` (every 15 minutes) resolves refunds that stayed `pending` without a Razorpay ID for 15 minutes by looking them up through `notes.refundId` and marks them `failed` with `not_found_at_provider` after a confirmed negative lookup; `billing.sync_subscriptions` (03:15 UTC) fetches every live subscription, and every `created` one that already has a Razorpay ID, and repairs status, period, plan, counts and cancellation through the state machine without ever moving a subscription backwards; `billing.settlement_check` (04:00 UTC) compares the previous UTC day's Razorpay payments with `payments` by payment ID (missing, extra, mismatched amount, currency, status or refunded amount), writes the JSON report to `{BILLING_REPORT_STORAGE_PREFIX}/settlement/YYYY-MM-DD.json`, records it in a `settlement` run that is unique per day and resumable after a failure, and alerts with `billing.reconciliation_mismatch` on any difference.
- **Credits for jobs:** reserve on job creation, commit the actual amount on completion and release the difference, or release everything on failure. Stale reservations are released by the sweeper after their TTL.

### Admin API
- Every route lives under `/v1/admin/billing` (tag `admin-billing`, `api.default` policy) and authorizes through `billing.read` for reads, `billing.products.manage` for product writes, `billing.refunds.create` for refunds and subscription cancellation, `billing.credits.adjust` for credit adjustments and `billing.webhooks.manage` for every webhook route; `super_admin` bypasses the checks. Lists are cursor-paginated newest first.
- **Products:** `GET/POST /products`, `GET/PATCH /products/{id}`, `POST /products/{id}/duplicate|activate|deactivate|sync-plan`. Every effective `PATCH` bumps `version` and needs the current `version` in the body (`409 product_version_conflict`). `kind`, `pricePaise`, `currency`, `interval`, `creditsGranted` and `planKey` change only while no order or subscription uses the product (`409 product_immutable`, which says to duplicate it); the database trigger remains the backstop. Changing the price, interval, currency or kind of an unused subscription product unlinks its Razorpay plan and deactivates it. Subscription products are created inactive; `activate` needs a synced plan (`409 plan_not_synced`) and a free `planKey` + `interval` slot (`409 active_plan_exists`, naming the product to deactivate first). `duplicate` creates the inactive next version `<base>_v<n>` (`n` = source version + 1, bumped past taken codes) that supersedes the source. `sync-plan` is idempotent once a plan is stored; it is the one Razorpay create without a lookup, so an ambiguous failure returns `503 payment_provider_unavailable` explaining that a plan may exist unlinked, and a retry creates a fresh plan. Every product write is audited, invalidates the product cache and queues the web revalidation after commit.
- **Payments, orders, refunds, subscriptions:** list and detail routes for each. `GET /payments/{id}` returns the order (with flag information), subscription summary, refunds, credit lot, `refundablePaise` and a clawback preview computed by the same `clawback_amount` the refund processing uses; `amountPaise` previews any refundable amount. `GET /orders?flagged=true` surfaces orders flagged for amount, currency or duplicate-payment mismatches. `POST /subscriptions/{id}/cancel` (`{immediately}`) reuses the user cancellation logic with the admin as audited actor and never refunds.
- **Webhooks:** list without payloads, detail with the redacted payload, and `POST /webhooks/{id}/reprocess` (`202`, audited) for `failed`, `processed` and `ignored` events.
- **Credits:** `GET /users/{userId}/credits` (wallet and lots), `GET /users/{userId}/credits/ledger`, `POST /users/{userId}/credits/adjust` (`delta`, `reason`, optional `expiresAt`, `Idempotency-Key` required). The ledger key is derived from admin, user and request key; a deduction beyond the available credits returns `409 adjustment_exceeds_available`.
- **Reconciliation:** run list and detail, and `GET /reconciliation/runs/{id}/report` streams the stored JSON report as an attachment with `Cache-Control: no-store` (`404 reconciliation_report_not_found` when the run has none).
- **Analytics** (`billing.read`, at most 366 UTC days, zero-filled): `/analytics/revenue` (captured, refunded, net paise and payment count per day; INR only), `/analytics/subscriptions` (live and active subscriptions per plan plus counts by status) and `/analytics/credits` (grants by source, consumption, expiry, clawbacks and admin deductions per day plus the sum of balances and reservations).

### Permissions
`billing.read`, `billing.products.manage`, `billing.refunds.create`, `billing.credits.adjust` and `billing.webhooks.manage`. `admin` holds all but `billing.refunds.create` and `billing.credits.adjust`, which belong to `super_admin` by default.

### Rate-limit policies
`billing.order.create` (10/min per user), `webhooks.razorpay` (600/min) and `api.default` for the rest.

---

## 9. Generation pipeline

```
query or topic
  → guard check
  → context: preferences and memory, skill router (system + user + pinned), RAG and web search when needed
  → storyboard
  → human approval (LangGraph interrupt; the user edits and approves)
  → TTS per scene: audio, word timestamps, real durations
  → scene HTML generation with fixed durations → compose master timeline
  → sanitize → sandbox validation → visual QA → repair (at most 2)
  → frame capture → encode → mux, loudness, subtitles → renditions (16:9, 9:16, 1:1)
  → S3 → job completed → SSE event
```

- System prompts are versioned (`prompt_templates`, `prompt_versions`), contain canary strings and are never returned by any API, with one documented exception: the admin prompt diff, available to `prompts.manage` holders only. A new version is activated only after finished, passing eval runs cover it for every required suite ([ADR 0033](adr/0033-eval-gated-prompt-activation.md)).
- User skills enter the prompt inside a delimited `<user_skill>` block below the system rules and cannot override policy.
- The MCP path enters the pipeline at sanitization, running TTS first when only narration text is submitted.
- Every stage writes a `usage_records` row.

### AI generation pipeline (Phase 9)

The pipeline is specified in [`ai-pipeline.md`](ai-pipeline.md) (graph, nodes, contracts, model layer, prompts, skills, repair, charging, settings), [`ai-policy.md`](ai-policy.md) (content policy and refusal codes) and [`evals.md`](evals.md) (datasets, suites, thresholds, CI and nightly runs).

- **Scene builders, assembled by code** ([ADR 0029](adr/0029-scene-builders-assembled-by-code.md)): the model returns a `scene-module@1` per scene; a deterministic composer builds the `runtime@1` document. `storyboard@1` is the plan the user reviews.
- **Graceful degradation** ([ADR 0030](adr/0030-graceful-degradation-with-fallback-scenes.md)): a scene that cannot be repaired within `ai.max_repairs` becomes a kinetic-typography fallback; the job still completes.
- **Predictable charging** ([ADR 0031](adr/0031-predictable-charging.md)): the reservation equals the published estimate and the charge never exceeds it; true costs live in `usage_records`.
- **Revisions are child jobs** ([ADR 0032](adr/0032-revisions-as-child-jobs.md)) with `jobs.parent_job_id`; unchanged narration comes from `tts_cache`.
- **Queue and runtime**: graph runs execute on the `generation` queue (`worker-generation`); the API image has ffmpeg but no browser, so composition validation and frame sampling run on the `render` queue ([ADR 0035](adr/0035-composition-checks-run-on-the-render-queue.md)); the `scenes` and `sync` eval suites, which also need Chromium, run there too ([ADR 0036](adr/0036-browser-eval-suites-run-on-the-render-queue.md)).
- **Modules**: `generation` owns `jobs`, `storyboards`, `scenes`, `job_events` and `share_links` (moved here from `media` because it joins jobs); `prompts` owns `prompt_templates`, `prompt_versions` and `eval_runs`; `skills` owns the skill tables (system skills only until Phase 10). Phase 10 adds user skills, pinning and the memory, RAG and search context providers.
- **Streams**: `GET /v1/jobs/{id}/events` sends `snapshot` then `job_event` frames with `Last-Event-ID` replay from `job_events`; live frames come from the Redis channel `<prefix>:job:<id>`.
- **Permissions**: `jobs.read_all`, `skills.manage` (admin and super_admin), `prompts.manage` and `evals.run` (super_admin by default).
- **Settings**: runtime `ai.*`, `charging.*`, `jobs.max_active_per_user`, `evals.ci_live_budget_micros_usd`; environment `AI_*`, `EMBEDDING_*` (see `ai-pipeline.md` section 11).

### Render and audio engine (Phase 8)

The render and audio engine is specified in [`render.md`](render.md) (composition contract, `runtime@1`, determinism, sanitizer, sandbox, validation codes, pipeline, storage layout, delivery, test bed, benchmark) and [`audio.md`](audio.md) (providers, alignment, TTS cache, narration assembly, mixing, loudness, subtitles, voices).

- **Renders are an aggregate** ([ADR 0021](adr/0021-renders-as-an-aggregate.md)): `renders` and `renditions` live in the `media` module; Phase 9 jobs and MCP submissions create a render through `create_render` and read it through `get_render` and `renditions_for`. `share_links` belongs to Phase 9.
- **Pipeline:** `render.run` on the `render` queue runs `preparing → voicing → mixing → capturing → encoding → finalizing`; each stage records a checkpoint and a retry resumes at the first incomplete stage. Progress goes to the Redis channel `render:<id>`.
- **TTS cache** ([ADR 0022](adr/0022-tts-cache-by-content-hash.md)): identical narration is synthesized and paid for once; `MediaService.narrate` exposes narration-first synthesis to Phase 9.
- **Music** ([ADR 0023](adr/0023-music-library-and-licensing.md)) comes only from licensed `music_tracks`.
- **Determinism** ([ADR 0024](adr/0024-deterministic-capture-through-web-animations-and-frozen-clock.md)): timeline and `document.getAnimations()` seeked per frame, frozen clock, seeded `Math.random`.
- **Contract and sandbox** ([ADR 0025](adr/0025-narration-first-composition-contract.md), [ADR 0026](adr/0026-render-sandbox-design.md)): `window.__narration` in, `Motionile.composition` and `window.__timeline` out; network-isolated Chromium with its sandbox on, and a strict CSP.
- **Voices** ([ADR 0027](adr/0027-voice-consent-verification.md)): a curated built-in catalog and consent-verified cloning with a random sentence, transcoded samples only and a retained consent record.
- **Delivery** ([ADR 0028](adr/0028-media-delivery-and-microphone-policy.md)): CloudFront signed cookies scoped to the owner's path, or presigned URLs.

---

## 10. Publishing

- `modules/publishing` with a `PublisherProvider` interface: `connect`, `refresh`, `validate`, `upload`, `publish`, `fetch_status`.
- Tables: `platform_specs`, `connected_accounts`, `account_credentials` (AES-GCM encrypted, key versioned), `publications`, `publication_targets`. `renditions` lives in the media module.
- Captions are generated per platform within each platform's limits.
- Publish flow: credits check → publication and targets → one task per target on the `publishing` queue with per-provider rate limits → refresh token → ensure rendition → upload → create post → store URL.
- A post-creation call is never retried blindly. After a timeout the target is marked `unknown` and `fetch_status` decides.
- Revocation and data-deletion callbacks are handled. Tokens never appear in logs or responses.

---

## 11. Infrastructure and deployment

### Domains
- Production (placeholder until confirmed): web at `motionile.com` (`www` redirects to the apex), `api.motionile.com`, `mcp.motionile.com`, `cdn.motionile.com`. Cookie domain `.motionile.com`.
- Staging uses its own separate registrable domain so production cookies never reach staging.

### Containers
One server Dockerfile with two targets produces two images.

| Container | Image | Command |
|---|---|---|
| `proxy` | `caddy` | Reverse proxy and automatic TLS (not used in local development) |
| `api` | `motionile-api` | uvicorn `motionile.entrypoints.api:app` |
| `mcp` | `motionile-api` | uvicorn `motionile.entrypoints.mcp:app` |
| `worker-default` | `motionile-api` | procrastinate worker on `default`, `billing`, `publishing`, concurrency 4 |
| `worker-generation` | `motionile-api` | procrastinate worker on `generation`, concurrency 4 |
| `worker-render` | `motionile-worker` | procrastinate worker on `render`, concurrency 1; non-root, read-only root file system, Playwright's seccomp profile, all capabilities dropped, Chromium and ffmpeg inside |
| `migrate` | `motionile-api` | `alembic upgrade head` (one-off) |
| `redis` | `redis` | AOF on, `noeviction`, password |

Local development adds Postgres with pgvector, MinIO and Mailpit. The web app runs with `pnpm dev` locally and on Vercel in staging and production; its Dockerfile exists for self-hosting. In staging and production, Redis and Caddy keep their data on the EBS data volume at `/srv/motionile/data`, images come from ECR, and the two environments differ only by the env file rendered from SSM.

### Environments
`APP_ENV` is `local`, `ci`, `staging` or `production`. `PROVIDERS_MODE` is `fake` or `live`. Settings are grouped by prefix (`DATABASE_`, `REDIS_`, `SECURITY_`, `CORS_`, `RATE_LIMIT_`, `STORAGE_`, `TURNSTILE_`, `ENCRYPTION_`, `LOG_`, `OUTBOUND_HTTP_`, `RENDER_`, `AUDIO_`, `ELEVENLABS_`, `OPENAI_`, `MEDIA_`, `VOICES_`); blank values count as unset, and staging and production refuse to start without live providers, explicit database, Redis and https CORS origins, a cursor-signing secret, encryption keys, a Turnstile secret and a storage bucket.

### CI/CD
- **`ci.yml`** on every pull request into `develop` or `prod`: lint (ESLint, ruff, no-comments, module boundaries, commitlint), typecheck (tsc, pyright), unit, integration, API contract drift, evals, scan (gitleaks, pip-audit, pnpm audit, Trivy), build images, e2e, security (security suite + ZAP baseline), load (k6 smoke).
- **Deploy:** push to `develop` → build `api` and `worker` with buildx → Trivy scan → push to staging ECR tagged with the commit SHA → `_deploy.yml`: assume the environment's OIDC role, allow the runner's IP on port 22 (always revoked), pin the host key, `rsync` `deploy/` to `/srv/motionile/bundle`, run `deploy.sh` (render `.env` from SSM, pull, migrate against `DATABASE_DIRECT_URL`, `compose up --wait`, roll back to the previous tag on failure), then HTTPS health checks and the Playwright smoke project.
- **Release:** `prod` is only ever fast-forwarded to a commit already deployed from `develop`. After reviewer approval on the `production` environment, `deploy-production.yml` copies that commit's images from staging ECR to production ECR and deploys them; it never rebuilds and fails if the images are missing.
- **`nightly.yml`:** full k6 load profile, ZAP full scan of the web app and OpenAPI scan of the API, and the full eval suite against staging; reports are artifacts.
- **`ci.yml` `infra` job:** `tofu fmt` and `validate`, tflint, Trivy configuration scan of `infra/` and `deploy/`, shellcheck and actionlint; `ci-ok` requires it.
- **Frontend:** Vercel Git integration, one project: production branch `prod`, staging domain on branch `develop`.

### AWS path
- **Phase 1 of infrastructure:** one EC2 instance with Compose, an EBS data volume, S3 + CloudFront + WAF, SES, SSM, CloudWatch agent; Neon or RDS for Postgres. OpenTofu 1.13 with the AWS provider 6.68 builds it from `infra/aws`: one `environment` module called by `envs/staging` and `envs/production`, state in an S3 bucket with lockfile locking, everything in `ap-south-1` except the CloudFront certificate and web ACL in `us-east-1`. See `docs/infrastructure.md` and `docs/runbooks/`.
- **Configuration:** `deploy/parameters.csv` lists every environment parameter under `/motionile/<env>/`. OpenTofu writes the non-secret ones from its outputs; the owner uploads secrets as SecureString with `infra/scripts/put-parameters.sh`; `render-env.sh` refuses to deploy while a required one is missing ([ADR 0013](adr/0013-one-environment-module-and-parameter-catalog.md)).
- **Logs and alarms:** containers log to `/motionile/<env>` through the awslogs driver ([ADR 0012](adr/0012-container-logs-through-awslogs.md)); the CloudWatch agent ships host logs and memory and disk metrics; alarms on CPU, memory, both disks, the API 5xx rate and task failures notify an SNS topic.
- **Later:** `worker-render` moves to ECS with an Auto Scaling capacity provider, scaling on queue depth; the API moves behind an ALB; Redis moves to ElastiCache.

---

## 12. Roadmap

| Phase | Scope |
|---|---|
| 1 | Foundation: monorepo, tooling, Husky, linting, no-comments enforcement, agent files, Docker, Compose, test harnesses, CI |
| 2 | Core platform and complete database blueprint |
| 3 | Staging infrastructure and continuous deployment; submit platform developer applications |
| 4 | Auth backend |
| 5 | Auth frontend |
| 6 | Users, RBAC, admin console and catalog |
| 7 | Credits and billing (Razorpay); GST invoices follow later |
| 8 | Render and audio engine, media delivery, voices, multi-format renditions |
| 9 | AI generation pipeline and evals |
| 10 | Memory, RAG, web search and custom skills |
| 11 | Publishing connectors |
| 12 | MCP server, production launch and hardening |

The detailed roadmap lives in `docs/roadmap.md`.
