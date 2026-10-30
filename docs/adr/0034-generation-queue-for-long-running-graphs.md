# 34. A dedicated queue for long-running generation graphs

- Status: Accepted
- Date: 2026-10-24
- Refines: [ADR 0002](0002-postgres-backed-job-queue.md)

## Context

One generation run holds a worker slot for minutes (model calls, narration, scene generation, waiting for the render). `worker-default` also delivers one-time passwords and receipts. A procrastinate worker handles one task at a time unless told otherwise, so graph runs on `default` would delay sign-in emails.

## Decision

- A fifth queue, `generation`, carries `generation.run_job` and the generation sweepers. `worker-default` listens to `default`, `billing`, `publishing` with concurrency 4; a new `worker-generation` service listens only to `generation` with concurrency 4 and the same image. Render work stays on `render`.
- Tasks defer with `lock=<job id>`, so one job never runs two graph slices at once, and a retry after a worker crash resumes from the LangGraph checkpoint.
- A run ends at the approval interrupt, at the end of the graph or on a permanent error. Approval resumes the same thread in a new task.
- The graph waits for its render inside the `render` node by following the render's progress channel with a database check, so render progress reaches the job stream live.

## Consequences

- OTP and receipt delivery are isolated from generation load.
- Capacity for generation is the product of `worker-generation` replicas and concurrency; both scale independently of render capacity.
- Deployment gains one service and one queue name in `docs/context.md`.
