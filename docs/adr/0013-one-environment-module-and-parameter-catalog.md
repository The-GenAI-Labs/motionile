# 13. One environment module and a shared parameter catalog

- Status: Accepted
- Date: 2026-10-14

## Context

Staging and production must differ only by variables, never by structure. The server reads its configuration from an env file rendered from SSM Parameter Store, and some of those values are known only to OpenTofu (bucket names, repository URLs, the log group), while others are secrets that must never enter OpenTofu state.

## Decision

- `infra/aws/modules/environment` composes every module. `infra/aws/envs/staging` and `infra/aws/envs/production` only declare variables, the backend key and providers, then call it.
- `deploy/parameters.csv` is the single catalog of environment parameters, with a `source` column:
  - `infra` parameters are plain `String` values that OpenTofu writes from its own outputs under `/motionile/<env>/`.
  - `owner` parameters are `SecureString` values the owner uploads with `infra/scripts/put-parameters.sh`; OpenTofu never sees them.
- `render-env.sh` on the instance renders `/srv/motionile/.env` from that namespace and fails when any parameter marked required is missing. The secrets module, the parameter upload script, the render script and the runbooks all read the same catalog.
- The CDN is enabled by a variable after its certificate validation record exists, so an environment can be applied with an external DNS provider in two passes without targeted applies.

## Consequences

- Adding a setting means one row in `deploy/parameters.csv` plus either an OpenTofu value (`infra`) or an uploaded secret (`owner`); a check fails the plan when an `infra` row has no value.
- Secrets never appear in code, state, logs or workflow output.
- A structural change made for one environment applies to both.
