# 12. Container logs through the awslogs driver

- Status: Accepted
- Date: 2026-10-14

## Context

The server writes one JSON object per line through structlog. CloudWatch metric filters for API 5xx responses and failed tasks must match fields such as `$.event` and `$.status`. If the CloudWatch agent tails Docker's `json-file` logs, every application line arrives wrapped in Docker's own JSON (`{"log": "...", "stream": ..., "time": ...}`), so the structlog fields are an escaped string that JSON metric filters cannot address.

## Decision

- Production and staging Compose services use Docker's `awslogs` driver in non-blocking mode, writing to the environment log group `/motionile/<env>` with streams named `containers/<container name>`. Each structlog line becomes one CloudWatch event, and metric filters match its fields directly.
- Docker's dual logging keeps a local cache, so `docker compose logs` still works on the instance.
- The CloudWatch agent ships host logs (`syslog`, `cloud-init-output.log`, `/srv/motionile/logs/deploy.log`) to the same log group under `host/<instance id>/` and collects memory and disk metrics. Its configuration lives in SSM and cloud-init loads it.
- The Docker daemon keeps `json-file` with rotation as its default driver for anything started outside Compose.

## Consequences

- Log-based metrics and alarms work on the structlog schema without a parsing pipeline.
- Container log delivery depends on the instance role's `logs:PutLogEvents` permission on the environment log group; non-blocking mode drops lines rather than stalling the application when CloudWatch is unreachable.
- Renaming structlog events `http.request` or `task.failed`, or the `status` field, requires updating the metric filters in `infra/aws/modules/observability`.
