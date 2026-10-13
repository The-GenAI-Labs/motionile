# Roadmap

Motionile is built in twelve phases. Each phase lands as one or more pull requests into `develop`, merges only with `ci-ok` green, and is released to production by a pull request from `develop` into `prod`. A phase is done only when every "done when" item holds.

## Phase 1 — Foundation, tooling and CI

**Scope:** pnpm and Turborepo monorepo; shared ESLint, TypeScript and Prettier configs; the `no-comments` ESLint rule and `scripts/check_no_comments.py`; module-boundary checks with import-linter; FastAPI, MCP and worker entrypoints with health routes; settings and structured logging; Alembic with the first migration (extensions and procrastinate schema); OpenAPI export and the generated API contract; Next.js skeleton with the brand theme and SEO defaults; Dockerfiles; Compose for development and production; Playwright, ZAP and k6 harnesses; Husky, lint-staged and commitlint; agent instruction files; documentation; the CI pipeline.

**Done when:**

- `pnpm install` and `pnpm verify` pass from a clean clone.
- `uv run pytest -m unit` and `uv run pytest -m integration` pass in `apps/server`.
- The development Compose stack starts, migrations apply, `api` and `mcp` answer `/health/live`, both workers stay running, and the web app serves the home page.
- The comments, module-boundary and import-linter checks fail on violating fixtures and pass on real code.
- `contract:check` passes and fails after a deliberate API change.
- Husky runs on commit, commit message and push.
- Every CI job passes on the pull request.

## Phase 2 — Core platform and database blueprint

**Scope:** async database engine and session management; Redis client; RFC 9457 error handling; camelCase base schemas; cursor pagination; UUIDv7 IDs; clock abstraction; domain events; `SafeHttpClient`; request ID middleware; rate limiter with the sliding-window Lua script and policies; Turnstile verification; storage adapter for the S3 API; settings store; the complete schema blueprint in `docs/db/` and the migrations for it; readiness checks for Postgres and Redis.

**Done when:**

- `/health/ready` reports Postgres and Redis status.
- Every table in the blueprint exists with the conventions in `docs/db/conventions.md`, and its migration upgrades and downgrades cleanly.
- Rate limits return 429 with `Retry-After` and `RateLimit-*` headers, proven by security tests.
- `SafeHttpClient` blocks private, loopback, link-local and metadata addresses, proven by tests.

## Phase 3 — Staging infrastructure and continuous deployment

**Scope:** OpenTofu under `infra/aws` for EC2 with an EBS data volume, ECR, S3, CloudFront, WAF, SES, SSM and CloudWatch; Neon or RDS for Postgres; `_deploy.yml`, `deploy-staging.yml` and `deploy-production.yml` with OIDC; `deploy.sh` with migrate, `compose up --wait` and rollback; `nightly.yml`; Vercel projects for both branches; submission of platform developer applications for publishing.

**Done when:**

- A merge into `develop` deploys to staging automatically and the staging health checks pass.
- A merge into `prod` deploys the same images to production after reviewer approval.
- A failed deploy rolls back to the previous images.
- Nightly load, ZAP full scan and full evals run against staging.
- Developer applications for every publishing platform have been submitted.

## Phase 4 — Auth backend

**Scope:** registration, password login, OTP login, verification tickets, OAuth with Google, GitHub and Microsoft, password reset, sessions, refresh rotation with reuse detection, revocation denylist, JWKS endpoint, CSRF, origin guard, CORS, security headers, Turnstile on sensitive routes, rate-limit policies for auth.

**Done when:**

- Every flow in `docs/context.md` section 7 works end to end against fakes.
- Cookie names, attributes and lifetimes match the context exactly.
- Security tests cover CSRF, origin, CORS, rate limits, JWT tampering, refresh reuse, Turnstile and token leakage.

## Phase 5 — Auth frontend

**Scope:** login, register, verify, forgot-password, reset-password and refresh pages; proactive refresh with a Web Lock; shared refresh on `401 token_expired`; the session-expiry handler; the server guard in `(user)/layout.tsx`; `proxy.ts`.

**Done when:**

- e2e tests cover every auth journey, including expiry, refresh and the no-loop guarantee on `/refresh`.
- Multiple tabs share one refresh.
- All auth pages are accessible and keyboard navigable.

## Phase 6 — Users, RBAC, admin console and catalog

**Scope:** users and roles, RBAC enforcement, audit logs, the admin console (users, roles, audit logs, catalog, prompts, system skills, platform specs, settings, feature flags), the catalog module and the public explore pages with ISR, sitemap and JSON-LD.

**Done when:**

- Admin actions are authorized in services and recorded in audit logs.
- Explore pages are statically generated, revalidate on catalog changes and emit `BreadcrumbList` JSON-LD.
- `sitemap.ts` lists every public catalog page.

## Phase 7 — Credits and billing

**Scope:** products, orders, payments, subscriptions, wallets, the append-only credit ledger, usage records, refunds, Razorpay webhooks, reconciliation, billing pages and the admin billing views.

**Done when:**

- Credit packs and subscriptions settle idempotently from both checkout and webhooks.
- Duplicate, concurrent and out-of-order webhooks never change balances twice.
- Refunds claw back unused credits proportionally.
- Reconciliation settles or expires stale orders.

## Phase 8 — Render and audio engine

**Scope:** the HTML runtime with bundled GSAP, sanitization, the network-isolated sandbox, frame capture with Playwright, ffmpeg encode and mux, loudness normalization, subtitles, background music ducking, renditions in 16:9, 9:16 and 1:1, TTS providers with word timestamps, voice cloning with consent, private S3 storage and CloudFront signed-cookie delivery.

**Done when:**

- A fixture composition renders to MP4 in all three formats on the `render` queue.
- Audio is normalized to −16 LUFS and scene timing matches narration.
- Videos play only for their owner through signed cookies.

## Phase 9 — AI generation pipeline and evals

**Scope:** LangGraph pipeline with the Postgres checkpointer, guard check, storyboard with human approval, narration-first TTS, scene generation, composition, validation and repair, versioned prompts with canaries, usage records per stage, SSE progress, eval suites for planning, visuals, safety and captions with thresholds.

**Done when:**

- A topic produces an approved storyboard and a rendered video against fake providers.
- Failing scenes are repaired at most twice.
- Eval suites run in CI and block prompt versions that miss their thresholds.

## Phase 10 — Memory, RAG, web search and custom skills

**Scope:** user preferences and memory, RAG with pgvector, web search through Tavily or Exa, custom skills in Claude's `SKILL.md` format with versions, scanning, sanitization, enablement and pinning, the skill router.

**Done when:**

- Context assembly uses memory, skills, RAG and search as described in section 9.
- User skills enter prompts only inside the delimited `<user_skill>` block and cannot override policy, proven by safety evals.
- Skill uploads are scanned and size-limited, proven by security tests.

## Phase 11 — Publishing connectors

**Scope:** the `PublisherProvider` interface, connected accounts with encrypted credentials, per-platform captions, publishing tasks with per-provider rate limits, status reconciliation for unknown outcomes, revocation and data-deletion callbacks, the share kit for platforms without an API.

**Done when:**

- Every listed platform publishes through its official API against fakes.
- A post-creation timeout marks the target `unknown` and `fetch_status` resolves it without duplicate posts.
- Tokens never appear in logs or responses, proven by tests.

## Phase 12 — MCP server, launch and hardening

**Scope:** the MCP server with API-key auth and tools that let a user's own LLM generate HTML and narration with Motionile skills and submit them; production launch on the final domains; load and security hardening; ECS and Auto Scaling plan for `worker-render`.

**Done when:**

- Claude and ChatGPT can connect, generate and submit a video that Motionile validates, voices and renders.
- The full load test and ZAP full scan pass against production-like staging.
- Production runs on the final domains with monitoring and alerting in place.
