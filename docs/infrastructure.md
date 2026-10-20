# Infrastructure

Motionile runs one AWS environment per stage in `ap-south-1`, built from the same OpenTofu module. The web app runs on Vercel; Postgres runs on Neon (or RDS when `enable_rds` is set). This page describes the topology; the [runbooks](runbooks/) say how to build and operate it.

| Branch    | Environment  | Web                       | API and MCP                               |
| --------- | ------------ | ------------------------- | ----------------------------------------- |
| `develop` | `staging`    | Vercel, staging domain    | EC2 `motionile-staging`, `c7i.xlarge`     |
| `prod`    | `production` | Vercel, production domain | EC2 `motionile-production`, `c7i.2xlarge` |

The phase brief calls these branches `staging` and `main`; this repository names them `develop` and `prod`.

## Topology

```mermaid
flowchart LR
    user([Browser])
    platforms([YouTube, Meta, LinkedIn, X, TikTok])

    subgraph vercel[Vercel]
        web[Next.js web app]
    end

    subgraph neon[Neon]
        pg[(PostgreSQL 17<br/>pooled and direct)]
    end

    subgraph aws_global[AWS global and us-east-1]
        cf[CloudFront cdn.domain]
        waf[WAF web ACL]
        acm[ACM certificate]
    end

    subgraph aws[AWS ap-south-1]
        subgraph vpc[VPC, two AZs]
            subgraph public[Public subnet]
                eip[Elastic IP]
                subgraph ec2[EC2 instance, Ubuntu 24.04]
                    caddy[Caddy TLS]
                    api[api]
                    mcp[mcp]
                    wd[worker-default]
                    wr[worker-render]
                    redis[(Redis AOF)]
                end
                data[(EBS data volume<br/>/srv/motionile/data)]
            end
            private[Private subnets<br/>reserved for RDS, ElastiCache, ECS]
            s3e[S3 gateway endpoint]
        end
        ecr[ECR motionile-api<br/>motionile-worker]
        media[(S3 media)]
        backup[(S3 backup)]
        ssm[SSM Parameter Store<br/>/motionile/env]
        ses[SES domain identity]
        cw[CloudWatch logs, metrics, alarms]
        sns[SNS alerts]
    end

    user --> web
    user -->|api, mcp| eip --> caddy
    caddy --> api & mcp
    user -->|signed cookies or URLs| cf
    waf --- cf
    acm --- cf
    cf -->|origin access control| media
    api & mcp & wd & wr --> pg
    api & wd & wr --> redis
    api & wd & wr -->|SafeHttpClient| platforms
    api & wr -->|via S3 endpoint| s3e --> media
    redis -. daily backup .-> backup
    ec2 --> ecr
    ec2 --> ssm
    api & wd --> ses
    ec2 --> cw --> sns
    data --- redis
    data --- caddy
```

## Deployment flow

```mermaid
sequenceDiagram
    autonumber
    participant Dev as Merge into develop
    participant GH as GitHub Actions
    participant ECR as ECR (staging)
    participant EC2 as Staging instance
    participant Rev as Reviewer
    participant ECRP as ECR (production)
    participant EC2P as Production instance

    Dev->>GH: push
    GH->>GH: buildx api and worker, Trivy scan
    GH->>ECR: push :commit-sha
    GH->>EC2: OIDC role, open port 22 for runner IP
    GH->>EC2: rsync deploy/, deploy.sh commit-sha
    EC2->>EC2: render .env from SSM, migrate, compose up --wait
    EC2-->>GH: success, or rollback to previous tag and fail
    GH->>GH: revoke port 22, health checks, Playwright smoke
    Note over GH,EC2P: Release: fast-forward prod to the same commit
    GH->>Rev: production environment approval
    Rev->>GH: approve
    GH->>ECR: verify :commit-sha exists
    GH->>ECRP: copy manifests (no rebuild)
    GH->>EC2P: same deploy steps as staging
```

## Components

| Concern           | Implementation                                                                                                                                            | Code                                       |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ |
| State             | S3 bucket with versioning, encryption, TLS-only policy; native S3 lockfile locking; one key per environment                                               | `infra/aws/bootstrap`, `envs/*/backend.tf` |
| Network           | VPC, two public and two private subnets, internet gateway, S3 gateway endpoint, no NAT, rejected-traffic flow logs                                        | `modules/network`                          |
| Compute           | One EC2 instance, IMDSv2 hop limit 2 ([ADR 0011](adr/0011-imdsv2-hop-limit-two.md)), encrypted root and data volumes, daily snapshots, auto-recovery      | `modules/compute`                          |
| Bootstrap         | cloud-init installs Docker, the Compose plugin, AWS CLI, CloudWatch agent, fail2ban, unattended upgrades, the `deploy` user and systemd timers            | `modules/compute/templates`                |
| Images            | ECR `<env>/motionile-api` and `<env>/motionile-worker`, immutable tags, scan on push, keep 30 tagged, expire untagged after 7 days                        | `modules/registry`                         |
| Media and backups | Private buckets, ownership enforced, TLS only, SSE-S3, versioning, lifecycle rules (including `work/` and `voice/`), CORS for the web origin              | `modules/storage`                          |
| CDN               | CloudFront with OAC; `/media/*` signed cookies, `/share/*` signed URLs, everything else 403; range requests; HTTP/2 and HTTP/3; logs to the backup bucket | `modules/cdn`                              |
| Edge protection   | WAF: IP reputation list, per-IP rate limit, `/media/*` referer rule, logs with cookies and query strings redacted                                         | `modules/waf`                              |
| Email             | SES identity with Easy DKIM, MAIL FROM, configuration set, bounces and complaints to SNS                                                                  | `modules/email`                            |
| Observability     | Log group, awslogs driver ([ADR 0012](adr/0012-container-logs-through-awslogs.md)), agent metrics, log metric filters, alarms, encrypted alert topic      | `modules/observability`                    |
| CI access         | GitHub OIDC provider, one deploy role per environment trusting only that GitHub environment                                                               | `modules/iam-github`                       |
| Configuration     | `/motionile/<env>/*` from the catalog `deploy/parameters.csv` ([ADR 0013](adr/0013-one-environment-module-and-parameter-catalog.md))                      | `modules/secrets`, `deploy/scripts`        |
| DNS               | Route 53 records when `manage_dns` is true, otherwise every record as an output                                                                           | `modules/dns`                              |
| Database          | Neon by default; optional RDS PostgreSQL 17 in the private subnets                                                                                        | `modules/database`                         |

## Server layout

| Path                         | Contents                                                        |
| ---------------------------- | --------------------------------------------------------------- |
| `/srv/motionile/bundle`      | The `deploy/` directory, synced on every deployment             |
| `/srv/motionile/.env`        | Rendered from SSM by `render-env.sh`, mode 600                  |
| `/srv/motionile/state`       | `current-tag`, `previous-tag`, `images.env`, `deploy.lock`      |
| `/srv/motionile/logs`        | `deploy.log`, shipped to CloudWatch                             |
| `/srv/motionile/data`        | EBS data volume: `redis/`, `caddy/data`, `caddy/config`         |
| `/etc/motionile/environment` | `MOTIONILE_ENVIRONMENT` and `AWS_REGION`, written by cloud-init |

## Security boundaries

- No secret is stored in code, OpenTofu state, logs or workflow output. Secrets are SecureString parameters uploaded by the owner, and GitHub holds only the SSH deploy key.
- Port 22 is closed. Deployments open it for the runner's IP and always revoke it; humans use Session Manager.
- The GitHub deploy role can push to its environment's repositories and change only port 22 on its environment's security group. Production's role can also read staging's repositories to promote images.
- The instance role can only pull its images, read its parameters, use its two buckets, send from its SES identity and write its logs.
- Media is reachable only through CloudFront with a valid signature; the bucket policy trusts only that distribution.
- Generated compositions run in a Chromium sandbox inside `worker-render`, a non-root, read-only container with no capabilities, no network access for the page and Playwright's seccomp profile ([ADR 0026](adr/0026-render-sandbox-design.md)).

## Media delivery

The media bucket holds several kinds of object under separate prefixes. Only `media/` and `share/` are reachable through CloudFront.

| Prefix                                 | Contents                                               | CDN | Lifecycle                                                                         |
| -------------------------------------- | ------------------------------------------------------ | --- | --------------------------------------------------------------------------------- |
| `media/u/<userId>/renders/<renderId>/` | Renditions, posters, subtitles, audio, composition     | yes | Kept; noncurrent versions follow `noncurrent_version_retention_days`              |
| `share/`                               | Objects published through signed share URLs            | yes | Kept                                                                              |
| `work/renders/<renderId>/`             | Render checkpoints and intermediate files              | no  | Expire after 7 days; old versions and delete markers removed within a day         |
| `voice/u/<userId>/<voiceId>/`          | Voice samples and the consent recording                | no  | Noncurrent versions removed after 1 day, so a deleted sample is gone within a day |
| `tts/`, `music/`, `voice-preview/`     | Cached narration, licensed tracks, voice preview clips | no  | Kept; the application prunes `tts/` ([audio.md](audio.md))                        |
| `tmp/`                                 | Temporary uploads                                      | no  | Expire after 1 day                                                                |

Incomplete multipart uploads are aborted after 1 day in every prefix.

How the CDN keeps the private prefixes private:

- The distribution has two cache behaviors, `/media/*` and `/share/*`, both with a trusted key group, `https-only` viewers and the `GET`, `HEAD` and `OPTIONS` methods. The default behavior answers 403 from a CloudFront function, so no other path reaches the origin.
- The bucket policy lets only this distribution read, and only `media/*` and `share/*` ([ADR 0028](adr/0028-media-delivery-and-microphone-policy.md)). Even a request that got past the default behavior could not read `work/`, `voice/`, `tts/`, `music/` or `voice-preview/`.
- Cookies are signed per user for `https://cdn.<domain>/media/u/<userId>/*`. The key group trusts every public key in `cloudfront_public_keys`, which is how rotation works ([secrets-rotation.md](runbooks/secrets-rotation.md#5-cloudfront-signing-key-pair)).
- Range requests work for seeking. The cache policy needs no `Range` handling because CloudFront serves ranges itself; `Range` is an allowed request header and `Accept-Ranges`, `Content-Length` and `Content-Range` are exposed to the web origin.
- The instance role reads, writes and deletes every prefix of the media bucket (`ReadWriteObjects` on `<bucket>/*` and `ListBucket` on the bucket). The API and `worker-render` share that role.

`MEDIA_DELIVERY_MODE` is written by OpenTofu: `cloudfront` when `enable_cdn` is true, `presigned` otherwise. In `presigned` mode the API returns per-asset presigned S3 URLs, which rely on the bucket CORS rule for the web origin.

## Render worker

`worker-render` runs generated HTML in Chromium and encodes with ffmpeg. Its container settings in `deploy/compose.yml`:

| Setting                                              | Why                                                                                                                                                                                   |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `user: 10001:10001`                                  | Chromium's own sandbox needs a non-root user                                                                                                                                          |
| `security_opt: seccomp=seccomp/playwright.json`      | Docker's default profile plus permission to create user namespaces, which the Chromium sandbox needs. Copied unchanged from Playwright's `utils/docker/seccomp_profile.json`          |
| `security_opt: no-new-privileges:true`               | No privilege gain through setuid binaries                                                                                                                                             |
| `cap_drop: [ALL]`                                    | The user-namespace sandbox needs no capability                                                                                                                                        |
| `read_only: true` with `tmpfs` at `/tmp` and `/work` | The image is immutable. `/tmp` (512 MB) holds the Chromium profile and `HOME`; `/work` (4 GB, owned by the app user) is `RENDER_WORK_DIRECTORY`; both vanish when the container stops |
| `shm_size: 1gb`                                      | Chromium's renderer shared memory, instead of the weaker `--ipc=host`                                                                                                                 |
| `mem_limit` and `memswap_limit: 6g`                  | A runaway render is killed alone. The tmpfs mounts and shared memory count towards this limit                                                                                         |
| `pids_limit: 1024`                                   | Bounds fork bombs from the browser or ffmpeg                                                                                                                                          |
| `init: true`                                         | Reaps Chromium and ffmpeg children                                                                                                                                                    |

Chromium is never started with `--no-sandbox`, and the container is never privileged or AppArmor-unconfined. `api`, `mcp`, `worker-default` and `migrate` also drop all capabilities and set `no-new-privileges`; `proxy` and `redis` do not, because their entrypoints need `NET_BIND_SERVICE` and `CHOWN`, `SETUID` and `SETGID`.

The seccomp file travels with the rest of `deploy/` (the deploy workflow rsyncs the whole directory to `/srv/motionile/bundle`). Compose reads it relative to the project directory, so `seccomp/playwright.json` resolves to `/srv/motionile/bundle/seccomp/playwright.json` in production and to `deploy/seccomp/playwright.json` locally and in CI.

### Host requirements

- Ubuntu 24.04 restricts unprivileged user namespaces with AppArmor (`kernel.apparmor_restrict_unprivileged_userns=1`). The restriction hits processes that have no AppArmor profile. Containers keep Docker's `docker-default` profile, which allows user namespaces, so the instance needs no sysctl change. cloud-init installs the current `docker-ce` from Docker's apt repository; keep it current, because an older `docker-default` may lack the `userns` rule.
- If Chromium reports `No usable sandbox` in `worker-render`, follow [Check the render sandbox](runbooks/access-and-operations.md#7-check-the-render-sandbox). The last resort there is the host sysctl, which weakens a kernel default for every process on the instance and belongs in the operations log.
- GitHub-hosted `ubuntu-24.04` runners run Chromium without a profile in the integration tests, so the `setup` action with `render: "true"` sets the sysctl to `0` on the runner, for that job only.
- Sizing: a render may use up to the 6 GB limit (browser, tmpfs and shared memory). Keep the instance at 8 GB of memory or more; production's `c7i.2xlarge` has 16 GB.

## Later

Per `docs/context.md`, `worker-render` moves to ECS with queue-depth autoscaling, the API moves behind an ALB and Redis moves to ElastiCache. The private subnets already exist for that move.
