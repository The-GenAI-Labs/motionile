# 1. Modular monolith with three entrypoints

- Status: Accepted
- Date: 2026-10-13

## Context

Motionile needs an HTTP API, an MCP server for Claude and ChatGPT, and background workers for billing, publishing and rendering. The team is small, the domain is still moving, and features such as generation and billing share data and transactions. Separate services would add network boundaries, duplicated infrastructure and distributed transactions before there is a scaling reason for them.

## Decision

The backend is one Python codebase, `apps/server`, with three entrypoints:

- `motionile.entrypoints.api` for the FastAPI application,
- `motionile.entrypoints.mcp` for the MCP server,
- `motionile.entrypoints.worker` for procrastinate workers.

Business logic lives in modules under `motionile.modules`, each exposing a public surface through its `__init__.py`. Infrastructure lives in `motionile.core`, engines in `motionile.engine`. `core` imports nothing from `modules`, `engine` or `mcp`; `engine` imports nothing from `modules`; modules import each other only through their packages. import-linter and `scripts/check_module_boundaries.py` enforce these rules in CI.

Two images are built from one Dockerfile: `motionile-api` for the API, MCP, default worker and migrations, and `motionile-worker` with Chromium and ffmpeg for the render worker.

## Consequences

- One deployment, one migration history and in-process calls between modules.
- Each entrypoint scales independently as its own container.
- Boundaries are enforced by tooling, so a module can later be extracted into a service with a clear interface.
- A bad change can affect every entrypoint at once, which CI and staging must catch.
