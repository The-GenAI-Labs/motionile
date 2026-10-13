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
10. **Billing.** Razorpay subscriptions and one-time credit packs. Every generation consumes credits through an append-only ledger.
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
- Public explore pages (`/explore`, `/explore/[category]`, `/explore/[category]/[topic]`) are statically generated with ISR.
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
| Queues | `default`, `billing`, `publishing` (run by `worker-default`); `render` (run by `worker-render`) |
| Database | PostgreSQL 17 with pgvector. Local Docker in development; Neon or RDS in staging and production, chosen only by `DATABASE_URL` |
| Redis | Rate limits, OTP, OAuth state, revocation denylist, verification tickets, cache, SSE pub/sub. `maxmemory-policy noeviction`, every key has a TTL |
| Auth | Custom, in FastAPI: cookie-based JWT access tokens plus rotating opaque refresh tokens |
| Payments | Razorpay with an append-only credit ledger |
| Storage | S3 API only, with configurable endpoint (AWS S3, MinIO, R2) |
| Media delivery | CloudFront signed cookies plus WAF Referer rule; presigned-URL fallback for non-AWS |
| Publishing | Official platform APIs only |
| Cloud | AWS, with no lock-in: configuration by environment variables, AWS SDK used only inside storage and media-delivery adapters, OpenTofu only under `infra/aws` |
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
| Security | argon2-cffi, PyJWT with cryptography (EdDSA), Authlib, phonenumbers, email-validator |
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
├── deploy/                   compose.yml  compose.dev.yml  compose.prod.yml  Caddyfile  scripts/
├── infra/aws/
├── docs/                     context.md  roadmap.md  adr/  db/
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
│   │   │   ├── explore/  [category]/  [topic]/
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
│   │   │   ├── users/[userId]/  roles/  analytics/  audit-logs/
│   │   │   ├── billing/  payments/  refunds/  webhooks/
│   │   │   ├── catalog/  prompts/  skills/  platforms/  settings/
│   │   ├── forbidden/
│   │   └── api/health/route.ts
│   ├── components/           ui/  layouts/  shared/
│   ├── features/             auth/  catalog/  generation/  library/  publishing/  skills/  billing/  voices/  memory/  settings/  dashboard/  admin/
│   ├── lib/                  api/  auth/  query/  razorpay/  seo/  utils/  validations/
│   ├── providers/
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
│   │   ├── settings_store/   service.py
│   │   └── tasks/            app.py  registry.py
│   ├── modules/
│   │   ├── auth/             router.py  schemas.py  service.py  repository.py  models.py  dependencies.py  exceptions.py  verification.py  oauth/  otp/
│   │   ├── users/
│   │   ├── catalog/
│   │   ├── generation/       router.py  schemas.py  service.py  repository.py  models.py  tasks.py  stream.py  estimator.py
│   │   ├── media/            router.py  service.py  renditions.py  delivery/
│   │   ├── voices/
│   │   ├── skills/           router.py  admin_router.py  schemas.py  service.py  repository.py  models.py  validator.py  scanner.py  packager.py
│   │   ├── memory/
│   │   ├── billing/          router.py  admin_router.py  webhook_router.py  schemas.py  models.py  repository.py  exceptions.py  tasks.py  services/  razorpay/
│   │   ├── credits/          service.py  repository.py  models.py  schemas.py  router.py  usage.py
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
- Errors are RFC 9457 `application/problem+json` with a stable machine-readable `code`.
- Lists use cursor pagination.
- Mutating endpoints that create money or credit side effects require an `Idempotency-Key` header.
- Every route declares `response_model`, status codes and rate-limit policy.

### Database
- Primary keys are UUIDv7 generated in the application.
- Every table has `created_at` and `updated_at` (`timestamptz`, UTC).
- Soft delete (`deleted_at`) only on `users` and `skills`.
- Status columns are `text` with a `CHECK` constraint; no native Postgres enums.
- Money is `bigint` paise. Credits are `bigint`.
- `jsonb` only for payloads and metadata, never for queried fields.
- SQLAlchemy `naming_convention` for all constraints. Every foreign key is indexed. `ON DELETE` is chosen explicitly per foreign key.
- Migrations: one per pull request, reversible, expand/contract only so a code rollback never breaks the schema.

### Security
- All outbound HTTP goes through `SafeHttpClient`.
- Secrets never appear in logs, errors, responses or the frontend bundle.
- Tokens and third-party credentials are stored hashed (refresh tokens, OTPs) or encrypted with AES-GCM (OAuth tokens for connectors).
- Authorization is checked in the service layer, not only in routers. Resource lookups always include the owner.
- Never trust client-supplied prices, amounts, roles or user IDs.

### Billing
- Prices come only from the `products` table.
- Every credit change is an append-only `credit_ledger` row with `balance_after` and a unique `idempotency_key`.
- Webhooks are verified on the raw body, stored, deduplicated by event ID and processed asynchronously.
- Status changes follow explicit state machines; stale events are recorded as `ignored`.

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
- Server integration tests use testcontainers Postgres and Redis; each test runs in a rolled-back transaction.
- Root `tests/` holds e2e, security and load tests against a running stack.
- CI runs external providers in `PROVIDERS_MODE=fake`: fake LLM, TTS, OTP channels, Razorpay and publishing providers; Cloudflare's dummy Turnstile keys.

### Git
- Branches: `phase-<n>/<slug>` or `feat/<slug>` → pull request into `staging` → fast-forward into `main`.
- Conventional Commits, enforced by commitlint.
- Pull requests merge only with every CI check green.

---

## 7. Auth

### Tokens and cookies

| Cookie | Content | Attributes | Lifetime |
|---|---|---|---|
| `__Secure-mo_at` | Access JWT (EdDSA) with `sub`, `sid`, `roles`, `iss`, `aud`, `iat`, `exp` | `Domain=.<root>`, HttpOnly, Secure, SameSite=Lax, Path=/ | 15 minutes |
| `__Secure-mo_rt` | Opaque 256-bit refresh token; only its SHA-256 hash is stored | Host-only on the API, HttpOnly, Secure, SameSite=Strict, `Path=/v1/auth` | 7 days idle, 60 days absolute |
| `__Secure-mo_vt` | Verification ticket for first-time OTP | Host-only on the API, HttpOnly, Secure, SameSite=Strict, `Path=/v1/auth` | 10 minutes |
| `mo_csrf` | CSRF token, HMAC-bound to the session | `Domain=.<root>`, Secure, SameSite=Lax, readable by JS | Session |
| `mo_auth` | Access token expiry timestamp only (a hint, not a secret) | `Domain=.<root>`, Secure, SameSite=Lax, readable by JS | Matches the access token |

- The Next.js server verifies the access JWT with the API's public key from `/v1/auth/jwks.json`.
- Every refresh rotates the refresh token. The successor's idle expiry is `min(now + 7 days, absolute_expires_at)`.
- Presenting an already-rotated refresh token outside a 10-second grace window revokes the whole session family.
- Revoked session families are added to a Redis denylist for 15 minutes so logout is immediate.

### Flows
- **Register:** email or phone plus password and Turnstile → user `pending_verification` → OTP sent (email via SES, phone via WhatsApp authentication template) → verification ticket cookie → verify code → user `active` → session.
- **Login with password:** Turnstile → argon2id check → if the contact is unverified, respond `403 verification_required`, set a ticket and send an OTP → otherwise create a session.
- **OTP login:** for verified contacts; 6 digits, HMAC-hashed in Redis for 5 minutes, at most 5 attempts, 60-second resend cooldown.
- **OAuth:** Google, GitHub, Microsoft with PKCE, state and nonce in Redis for 10 minutes, redirect target allowlist, account linking only on a provider-verified email.
- **Password reset:** single-use hashed token, 30 minutes.
- **Sessions:** list active sessions, revoke one, revoke all.

### Frontend session handling
- Proactive refresh 60 seconds before `mo_auth` expiry while the tab is visible, guarded by a Web Lock across tabs.
- On `401 token_expired`, one shared refresh, then retry the original request once.
- The refresh request never triggers another refresh.
- If refresh fails, the session-expiry handler runs once: clear the query cache and redirect to `/login?next=<relative path>&reason=expired`.
- Server guard in `(user)/layout.tsx`: valid JWT renders; expired JWT with the hint cookie redirects to `/refresh?next=`; `/refresh` attempts exactly one refresh and falls back to `/login`, never looping.

### Request protection
- **CSRF:** SameSite cookies, Origin check on every unsafe method, double-submit `mo_csrf` cookie matched against `X-CSRF-Token`.
- **CORS:** explicit origin allowlist, credentials allowed, no wildcards.
- **Origin guard:** state-changing requests from non-allowlisted origins are rejected (Referer as fallback).
- **SSRF:** https only, DNS resolved and private, loopback, link-local and metadata ranges blocked, redirects re-validated, timeouts and size caps. EC2 uses IMDSv2 with hop limit 1. The render sandbox blocks all network access except the bundled runtime.
- **Turnstile** on register, login, OTP send, forgot-password and contact. Verified server-side with remote IP, hostname and action checks.
- **Security headers:** HSTS, `nosniff`, `Cache-Control: no-store` on auth responses; the web app sets a CSP with `frame-ancestors 'none'` and `Referrer-Policy: strict-origin-when-cross-origin`.

### Rate-limit policies (Redis sliding window, atomic Lua)

| Policy | Limit |
|---|---|
| `auth.login` | 5/min per IP+identifier, 30/hour per IP |
| `auth.otp.send` | 1/60 s and 5/hour per destination, 15/hour per IP |
| `auth.otp.verify` | 5 attempts per code |
| `auth.refresh` | 30/min per session |
| `api.default` | 120/min per user, 60/min per IP when unauthenticated |
| `jobs.create` | 5/min per user, at most 2 concurrent jobs |
| `billing.order.create` | 10/min per user |
| `skills.write` | 20/hour per user |
| `publishing.publish` | 30/hour per user |
| `mcp.submit` | 10/hour per API key |
| `webhooks.razorpay` | 600/min |

Every 429 includes `Retry-After` and `RateLimit-*` headers. Real client IPs are trusted only from the reverse proxy.

---

## 8. Billing (Razorpay)

### Tables
`products`, `orders`, `payments`, `subscriptions`, `credit_wallets`, `credit_ledger`, `usage_records`, `refunds`, `webhook_events`, `billing_customers`.

### Flows
- **Credit pack:** create `orders` row → Razorpay order (amount from `products`, `receipt` = order ID) → Checkout → verify `HMAC(order_id|payment_id)` → fetch the payment from Razorpay and confirm status, amount and currency → in one transaction mark paid, credit the wallet and write the ledger. The `payment.captured` and `order.paid` webhooks run the same idempotent settlement.
- **Subscription:** create the Razorpay subscription from `products.razorpay_plan_id` → Checkout → verify `HMAC(payment_id|subscription_id)` → webhooks drive the state (`activated`, `charged` grants credits once per payment, `pending`, `halted`, `cancelled`, `completed`, `paused`, `resumed`, `updated`). Cancellation happens at the end of the period.
- **Refund:** admin-initiated, bounded by the refundable amount → Razorpay refund → `refund.processed` marks it done and claws back unused credits proportionally.
- **Reconciliation:** every 15 minutes, pending orders older than 30 minutes are settled or expired; a daily report compares Razorpay settlements with `payments`.
- **Credits for jobs:** reserve on job creation, commit the actual amount on completion and release the difference, or release everything on failure. A sweeper re-queues stuck jobs and releases stale reservations.

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

- System prompts are versioned (`prompt_templates`, `prompt_versions`), contain canary strings and are never returned by any API. A new version is activated only after its eval run passes.
- User skills enter the prompt inside a delimited `<user_skill>` block below the system rules and cannot override policy.
- The MCP path enters the pipeline at sanitization, running TTS first when only narration text is submitted.
- Every stage writes a `usage_records` row.

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
| `worker-default` | `motionile-api` | procrastinate worker on `default`, `billing`, `publishing` |
| `worker-render` | `motionile-worker` | procrastinate worker on `render`, concurrency 1 |
| `migrate` | `motionile-api` | `alembic upgrade head` (one-off) |
| `redis` | `redis` | AOF on, `noeviction`, password |

Local development adds Postgres with pgvector, MinIO and Mailpit. The web app runs with `pnpm dev` locally and on Vercel in staging and production; its Dockerfile exists for self-hosting.

### Environments
`APP_ENV` is `local`, `ci`, `staging` or `production`. `PROVIDERS_MODE` is `fake` or `live`.

### CI/CD
- **`ci.yml`** on every pull request into `staging` or `main`: lint (ESLint, ruff, no-comments, module boundaries, commitlint), typecheck (tsc, pyright), unit, integration, API contract drift, evals, scan (gitleaks, pip-audit, pnpm audit, Trivy), build images, e2e, security (security suite + ZAP baseline), load (k6 smoke).
- **Deploy:** push to `staging` → build → push to ECR → SSH to EC2 (runner IP temporarily allowed in the security group) → `deploy.sh`: pull, migrate, `compose up --wait`, roll back on failure. `main` deploys the same image after reviewer approval.
- **`nightly.yml`:** full load test, ZAP full scan and full evals against staging.
- **Frontend:** Vercel Git integration for both branches.

### AWS path
- **Phase 1 of infrastructure:** one EC2 instance with Compose, an EBS data volume, S3 + CloudFront + WAF, SES, SSM, CloudWatch agent; Neon or RDS for Postgres.
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
| 7 | Credits and billing (Razorpay) |
| 8 | Render and audio engine, media delivery, voices, multi-format renditions |
| 9 | AI generation pipeline and evals |
| 10 | Memory, RAG, web search and custom skills |
| 11 | Publishing connectors |
| 12 | MCP server, production launch and hardening |

The detailed roadmap lives in `docs/roadmap.md`.
