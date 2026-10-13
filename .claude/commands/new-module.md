---
description: Scaffold a new backend module in apps/server following the Motionile module conventions
argument-hint: <module-name> <one-line purpose>
---

Scaffold the backend module `$ARGUMENTS`.

1. Read `docs/context.md` sections 3 and 6, `apps/server/CLAUDE.md` and `.claude/skills/fastapi-module/SKILL.md`.
2. Confirm the module name is a lowercase plural noun that is not already used under `apps/server/src/motionile/modules/`.
3. Create `apps/server/src/motionile/modules/<name>/` with `__init__.py`, `router.py`, `schemas.py`, `service.py`, `repository.py`, `models.py`, `dependencies.py` and `exceptions.py`, containing only what the requested behaviour needs.
4. Export the public service, schemas and exceptions from `__init__.py`. Other modules import only from there.
5. Register the router in `motionile.entrypoints.api` under `/v1`.
6. Add unit tests under `apps/server/tests/unit/modules/<name>/` using fakes, and integration tests for the repository and routes under `apps/server/tests/integration/`.
7. If tables are needed, run `/new-migration` for this module.
8. Run `pnpm contract:generate`, then `pnpm verify` and `pnpm test:integration`. Fix every failure without weakening a check.
9. Report the files created, routes with their `operation_id`, and the command results.
