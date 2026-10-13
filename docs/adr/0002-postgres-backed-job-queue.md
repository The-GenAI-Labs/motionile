# 2. Postgres-backed job queue with procrastinate

- Status: Accepted
- Date: 2026-10-13

## Context

Generation, rendering, billing webhooks and publishing all run in the background. We already depend on PostgreSQL. A separate broker such as RabbitMQ or a Redis-based queue adds another stateful service to operate, back up and monitor, and it cannot enqueue a job in the same transaction as the business write that caused it.

## Decision

Background jobs use procrastinate on PostgreSQL. There are four queues:

| Queue                              | Worker                         |
| ---------------------------------- | ------------------------------ |
| `default`, `billing`, `publishing` | `worker-default`               |
| `render`                           | `worker-render`, concurrency 1 |

The procrastinate schema is installed by the first Alembic migration. Upgrades of procrastinate ship as new Alembic migrations that apply its schema migrations. Queue names are defined once in `motionile.core.tasks.app.Queue`.

## Consequences

- Jobs are enqueued transactionally with the writes that create them.
- No extra broker to run; job state is queryable with SQL.
- Queue throughput is bounded by Postgres; render work is long-running and isolated on its own worker so it never starves billing or publishing.
- Workers need a direct, non-pooled connection for `LISTEN/NOTIFY`, which is why `DATABASE_DIRECT_URL` exists.
