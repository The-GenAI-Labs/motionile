# 11. IMDSv2 with a hop limit of 2

- Status: Accepted
- Date: 2026-10-14
- Supersedes: the "hop limit 1" statement in `docs/context.md` section 7

## Context

The application runs in Docker containers on one EC2 instance. The API, MCP server and workers need AWS credentials for S3 (media and backups) and SES (email). The instance role provides them through the instance metadata service. With IMDSv2 and a hop limit of 1, the PUT that obtains a session token cannot leave a container's network namespace, so containers would need long-lived access keys instead. Long-lived keys are worse: they live in configuration, are not rotated automatically and are not scoped to the instance.

## Decision

The instance requires IMDSv2 (`http_tokens = "required"`) with `http_put_response_hop_limit = 2` and instance metadata tags disabled. Containers obtain short-lived instance-role credentials through the AWS SDK default credential chain. No access keys exist for the application.

Compensating controls:

- All outbound HTTP from application code goes through `SafeHttpClient`, which resolves every host and blocks link-local addresses, including `169.254.169.254`, `fd00:ec2::254` and every IPv4-mapped, NAT64, 6to4 and Teredo encoding of them, and revalidates every redirect. A server-side request forgery bug cannot reach the metadata service through it.
- IMDSv2 tokens require a PUT with a custom header, which ordinary SSRF through GET requests and most proxies cannot issue.
- The render sandbox runs with networking disabled, so generated HTML and scripts cannot reach the metadata service.
- The instance role is least privilege: pull from the environment's ECR repositories, read `/motionile/<env>/*`, read and write the environment's two buckets, send email from the environment's SES identity, write to the environment's log group and the agent's metrics. It cannot modify infrastructure.

## Consequences

- Containers use temporary, automatically rotated credentials with no secrets in configuration.
- A process inside a container that can make arbitrary HTTP requests outside `SafeHttpClient` could obtain the role's credentials; code review and the boundary checks keep outbound HTTP inside `SafeHttpClient`.
- When the API moves to ECS (see `docs/context.md`, AWS path), task roles replace this and the hop limit can return to 1.
