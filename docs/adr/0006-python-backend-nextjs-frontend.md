# 6. Python backend with a Next.js frontend

- Status: Accepted
- Date: 2026-10-13

## Context

The backend orchestrates LLMs, text-to-speech, headless Chromium and ffmpeg, and needs strong libraries for AI pipelines, evals and data. The frontend needs server rendering for SEO on public explore pages, a rich interactive editor and fast iteration.

## Decision

- Backend: Python 3.13 with FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, procrastinate and LangGraph, managed with uv and checked by ruff and pyright in strict mode.
- Frontend: Next.js App Router with React 19 and the React Compiler, TypeScript strict, Tailwind CSS v4 and shadcn/ui, deployed on Vercel and runnable from its own Dockerfile.
- The contract between them is the FastAPI OpenAPI schema. `@hey-api/openapi-ts` generates TypeScript types and Zod schemas into `packages/api-contract`, and CI fails when the committed output drifts.
- One pnpm and Turborepo monorepo holds both, with the Python project exposed to Turborepo through `apps/server/package.json`.

## Consequences

- The best ecosystem is used on each side, at the cost of two toolchains.
- API types cannot silently diverge because the contract is generated and checked.
- Contributors need Node.js 24, pnpm 10, Python 3.13 and uv locally.
