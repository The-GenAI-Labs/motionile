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

| Variable               | Used by | Meaning                                                                                         |
| ---------------------- | ------- | ----------------------------------------------------------------------------------------------- |
| `APP_ENV`              | server  | `local`, `ci`, `staging` or `production`                                                        |
| `PROVIDERS_MODE`       | server  | `fake` for local and CI, `live` in staging and production                                       |
| `DATABASE_URL`         | server  | PostgreSQL connection URL (`postgresql://`)                                                     |
| `DATABASE_DIRECT_URL`  | server  | Optional direct connection for migrations and workers when `DATABASE_URL` goes through a pooler |
| `REDIS_URL`            | server  | Redis connection URL                                                                            |
| `LOG_LEVEL`            | server  | `DEBUG`, `INFO`, `WARNING` or `ERROR`                                                           |
| `ALLOWED_ORIGINS`      | server  | Comma-separated origins allowed by CORS                                                         |
| `FORWARDED_ALLOW_IPS`  | uvicorn | IPs trusted to set forwarded headers; only the reverse proxy in production                      |
| `NEXT_PUBLIC_SITE_URL` | web     | Public site URL used for canonical URLs, Open Graph and the sitemap                             |
| `WEB_BASE_URL`         | tests   | Web app under test                                                                              |
| `API_BASE_URL`         | tests   | API under test                                                                                  |

Staging and production must set `DATABASE_URL`, `REDIS_URL` and `ALLOWED_ORIGINS` explicitly and use `PROVIDERS_MODE=live`; the server refuses to start otherwise.

## Branching

| Branch    | Purpose                                                                                                 |
| --------- | ------------------------------------------------------------------------------------------------------- |
| `init`    | Snapshot of the initial repository setup. Not used for new work.                                        |
| `develop` | Integration branch. Feature and phase branches merge here through pull requests; it deploys to staging. |
| `prod`    | Production. Receives release pull requests from `develop` only.                                         |

Work on `phase-<n>/<slug>` or `feat/<slug>` branches cut from `develop`. Commits follow [Conventional Commits](https://www.conventionalcommits.org/) and must be signed so they show as **Verified** on GitHub. Pull requests merge only when the `ci-ok` check is green.

## Documentation

- [`docs/context.md`](docs/context.md): the single source of truth for the product and its architecture
- [`docs/roadmap.md`](docs/roadmap.md): the twelve phases and their "done when" criteria
- [`docs/adr/`](docs/adr/): architecture decision records
- [`docs/db/conventions.md`](docs/db/conventions.md): database conventions
- [`AGENTS.md`](AGENTS.md): rules for coding agents and contributors
