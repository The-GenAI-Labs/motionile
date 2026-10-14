# Motionile

Motionile turns a topic or a question into a short, narrated, animated explainer video. An AI pipeline plans a storyboard, voices each scene, animates it in sync with the audio, renders it to video and publishes it to social platforms and blogs in one click.

## Prerequisites

| Tool    | Version                                                    |
| ------- | ---------------------------------------------------------- |
| Node.js | 24 LTS (see `.node-version`)                               |
| pnpm    | 10 (enabled through Corepack)                              |
| Python  | 3.13 (see `.python-version`)                               |
| uv      | 0.13 or newer                                              |
| Docker  | with Compose v2, for integration tests and the local stack |

## Setup

```bash
git clone https://github.com/The-GenAI-Labs/motionile.git
cd motionile
git checkout develop
corepack enable
pnpm install
uv sync --project apps/server
cp .env.example apps/server/.env
```

`pnpm install` also installs the Husky git hooks.

## Main commands

| Command                  | What it does                                                             |
| ------------------------ | ------------------------------------------------------------------------ |
| `pnpm dev`               | Run the web app on port 3000 and the API on port 8000 with reload        |
| `pnpm verify`            | Run every check CI runs that does not need Docker                        |
| `pnpm lint`              | ESLint, ruff, the no-comments check, module boundaries and import-linter |
| `pnpm typecheck`         | `tsc` across workspaces and pyright in strict mode                       |
| `pnpm test:unit`         | Vitest and pytest unit tests                                             |
| `pnpm test:integration`  | pytest integration tests against Postgres and Redis containers           |
| `pnpm contract:generate` | Export the OpenAPI schema and regenerate `packages/api-contract`         |
| `pnpm contract:check`    | Fail when the committed API contract is out of date                      |
| `pnpm evals`             | Run eval suites against `apps/server/evals/thresholds.yaml`              |
| `pnpm format`            | Format everything with Prettier and ruff                                 |

### Local stack

```bash
docker compose -f deploy/compose.yml -f deploy/compose.dev.yml up --build -d postgres redis
docker compose -f deploy/compose.yml -f deploy/compose.dev.yml run --rm migrate
docker compose -f deploy/compose.yml -f deploy/compose.dev.yml up --build
pnpm --filter @motionile/web dev
```

| Service       | URL                               |
| ------------- | --------------------------------- |
| Web           | http://localhost:3000             |
| API           | http://localhost:8000/health/live |
| MCP           | http://localhost:8001/health/live |
| MinIO console | http://localhost:9001             |
| Mailpit       | http://localhost:8025             |

### End-to-end, security and load tests

With the stack and the web app running:

```bash
pnpm --filter @motionile/tests exec playwright install chromium
pnpm --filter @motionile/tests run e2e
pnpm --filter @motionile/tests run security
pnpm --filter @motionile/tests run zap -- http://localhost:3000
pnpm --filter @motionile/tests run load
```

## Environment variables

`.env.example` lists every variable used so far; `deploy/.env.example` lists the variables Compose reads in production.

| Variable                       | Used by | Meaning                                                                                           |
| ------------------------------ | ------- | ------------------------------------------------------------------------------------------------- |
| `APP_ENV`                      | server  | `local`, `ci`, `staging` or `production`; test-support routes exist only in `local` and `ci`      |
| `PROVIDERS_MODE`               | server  | `fake` for local and CI, `live` in staging and production                                         |
| `DATABASE_URL`                 | server  | PostgreSQL connection URL (`postgresql://`)                                                       |
| `DATABASE_DIRECT_URL`          | server  | Optional direct connection for migrations and workers when `DATABASE_URL` goes through a pooler   |
| `REDIS_URL`                    | server  | Redis connection URL                                                                              |
| `LOG_LEVEL`                    | server  | `DEBUG`, `INFO`, `WARNING` or `ERROR`                                                             |
| `CORS_ALLOWED_ORIGINS`         | server  | Comma-separated origins allowed by CORS and the Origin guard                                      |
| `RATE_LIMIT_ENABLED`           | server  | Turns rate limiting on or off; always on when deployed                                            |
| `RATE_LIMIT_OVERRIDES`         | server  | JSON map of policy name to rules, for example `{"auth.login":[{"limit":10,"window_seconds":60}]}` |
| `SECURITY_PAGINATION_SECRET`   | server  | At least 32 characters; signs pagination cursors                                                  |
| `ENCRYPTION_KEYS`              | server  | JSON map of key version to base64 32-byte AES-GCM key; the highest version encrypts               |
| `TURNSTILE_SECRET_KEY`         | server  | Cloudflare Turnstile secret; fake verification is used while `PROVIDERS_MODE=fake`                |
| `TURNSTILE_EXPECTED_HOSTNAMES` | server  | Comma-separated hostnames Turnstile tokens must come from                                         |
| `STORAGE_ENDPOINT_URL`         | server  | S3-compatible endpoint; leave empty for AWS S3                                                    |
| `STORAGE_BUCKET`               | server  | Bucket for private media                                                                          |
| `STORAGE_ACCESS_KEY_ID`        | server  | Static S3 credentials for MinIO; leave empty to use the instance role                             |
| `STORAGE_SECRET_ACCESS_KEY`    | server  | Static S3 secret for MinIO; leave empty to use the instance role                                  |
| `FORWARDED_ALLOW_IPS`          | uvicorn | IPs trusted to set forwarded headers; only the reverse proxy in production                        |
| `NEXT_PUBLIC_SITE_URL`         | web     | Public site URL used for canonical URLs, Open Graph and the sitemap                               |
| `WEB_BASE_URL`                 | tests   | Web app under test                                                                                |
| `API_BASE_URL`                 | tests   | API under test                                                                                    |

Staging and production must set `DATABASE_URL`, `REDIS_URL`, `CORS_ALLOWED_ORIGINS` (https only), `SECURITY_PAGINATION_SECRET`, `ENCRYPTION_KEYS`, `TURNSTILE_SECRET_KEY` and `STORAGE_BUCKET` explicitly and use `PROVIDERS_MODE=live`; the server refuses to start otherwise.

## Branching

| Branch    | Purpose                                                                                                                                                 |
| --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `init`    | Snapshot of the initial repository setup. Not used for new work.                                                                                        |
| `develop` | Integration branch. Feature and phase branches merge here through pull requests; it deploys to staging.                                                 |
| `prod`    | Production. Only ever fast-forwarded to a commit already deployed from `develop`; see [`docs/runbooks/github-setup.md`](docs/runbooks/github-setup.md). |

Work on `phase-<n>/<slug>` or `feat/<slug>` branches cut from `develop`. Commits follow [Conventional Commits](https://www.conventionalcommits.org/) and must be signed so they show as **Verified** on GitHub. Pull requests merge only when the `ci-ok` check is green.

## Documentation

- [`docs/context.md`](docs/context.md): the single source of truth for the product and its architecture
- [`docs/roadmap.md`](docs/roadmap.md): the twelve phases and their "done when" criteria
- [`docs/adr/`](docs/adr/): architecture decision records
- [`docs/db/conventions.md`](docs/db/conventions.md): database conventions
- [`docs/infrastructure.md`](docs/infrastructure.md): AWS, Vercel and Neon topology and the deployment flow
- [`docs/runbooks/`](docs/runbooks/): step-by-step setup, deployment, operations, backups, secret rotation and platform applications
- [`AGENTS.md`](AGENTS.md): rules for coding agents and contributors
