# apps/server

Rules local to the Python backend. The root `AGENTS.md` and `CLAUDE.md` still apply.

## Layout

- `src/motionile/entrypoints/` holds the three processes: `api.py` (FastAPI), `mcp.py` (MCP server, health only until Phase 12) and `worker.py` (procrastinate).
- `src/motionile/core/` holds cross-cutting infrastructure: settings, logging, database base, middleware, task queue setup. It never imports `modules`, `engine` or `mcp`.
- `src/motionile/modules/<name>/` holds business modules from Phase 2 on. Export the public surface from `__init__.py`.
- `src/motionile/engine/` holds AI, audio and render engines. It never imports `modules`.
- `migrations/` holds Alembic migrations. `evals/` holds eval suites and `thresholds.yaml`.

## Commands

Run from `apps/server`:

| Command                                               | Purpose                              |
| ----------------------------------------------------- | ------------------------------------ |
| `uv run ruff check . && uv run ruff format --check .` | Lint and format check                |
| `uv run pyright -p .`                                 | Strict type check                    |
| `uv run pytest -m unit`                               | Unit tests                           |
| `uv run pytest -m integration`                        | Integration tests (needs Docker)     |
| `uv run lint-imports`                                 | import-linter contracts              |
| `uv run python -m motionile.scripts.export_openapi`   | Write `openapi.json`                 |
| `uv run python -m evals.run`                          | Run eval suites against thresholds   |
| `uv run alembic revision -m "<message>"`              | New migration (use `/new-migration`) |

## Rules

- Add settings only to `core/config.py` as typed fields with safe local defaults. Deployed environments must set them explicitly; add a check to `Settings.deployment_problems()` when a value has no safe default.
- Use `structlog.get_logger()` for logging. Never log secrets, tokens or personal data.
- Give every route `response_model`, `status_code`, `responses=problem_responses(...)`, a rate-limit policy and a summary. Operation IDs are generated as `<tag>_<function_name>` and become the generated TypeScript names, so name route functions deliberately.
- Register procrastinate tasks with the `task()` decorator from `core/tasks/registry.py` on the matching `Queue`, and list the module in `TASK_MODULES`. Render work goes only to `render`. Enqueue from a transaction with `defer_after_commit()`.
- Build process-wide clients in `core/resources.py` and inject them through `core/dependencies.py`; never create clients inside request handlers.
- Run migrations with psycopg (`PSYCOPG_SCHEME`); the application uses asyncpg.
- When upgrading procrastinate, add a migration that applies its schema migrations; never edit `0001`.
- Mark tests by directory: everything under `tests/unit` is `unit`, everything under `tests/integration` is `integration`. Mark slow tests with `@pytest.mark.slow`.
- Keep `filterwarnings = ["error"]`; fix deprecations instead of silencing them.
