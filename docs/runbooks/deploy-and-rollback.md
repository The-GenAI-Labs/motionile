# Deploy and roll back

This runbook explains how Motionile deployments run, how to watch them, and how to roll back, re-run or drill a failed deployment. The branch `develop` deploys to the `staging` environment and `prod` deploys to `production`.

It assumes [bootstrap-aws.md](bootstrap-aws.md) and [github-setup.md](github-setup.md) are done. Commands on your machine run from the repository root with `export AWS_PROFILE=<AWS_PROFILE>` and `repo=<GITHUB_OWNER>/<GITHUB_REPOSITORY>` set.

## How a deployment works

### Triggers

| Event                        | Workflow                | What happens                                                                                                                                                                                                |
| ---------------------------- | ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Push to `develop`            | `deploy-staging.yml`    | Builds `motionile-api` and `motionile-worker`, scans them with Trivy, pushes `staging/<image>:<commit SHA>` to ECR, then runs `_deploy.yml` for `staging`. A build is skipped when that tag already exists. |
| Push to `prod`               | `deploy-production.yml` | Waits for a reviewer to approve the `production` environment, then runs `_deploy.yml` for `production` with `promote-from: staging`. Nothing is rebuilt.                                                    |
| Manual (`workflow_dispatch`) | Either workflow         | Same as a push, for the tip of `develop` or `prod`. The environments refuse other branches.                                                                                                                 |

Only one deployment per environment runs at a time (`concurrency` groups `deploy-staging-pipeline`, `deploy-production-pipeline` and `deploy-<environment>`); a second one queues.

### What `_deploy.yml` does

The job `deploy <environment>` runs these steps in order:

1. **Validate inputs:** the image tag must be a full 40-character commit SHA, and every required environment variable must be set.
2. **Assume the deploy role** through GitHub OIDC.
3. **Log in to ECR.**
4. **Promote images** (production only): for each image, fail if `staging/<image>:<SHA>` does not exist, skip if `production/<image>:<SHA>` already exists, otherwise copy the manifest with `docker buildx imagetools create`.
5. **Check images exist** in the target environment's repositories.
6. **Allow this runner on port 22:** adds an ingress rule for the runner's IP with the description `github-run-<run id>`.
7. **Configure SSH with the pinned host key** from `DEPLOY_SSH_KNOWN_HOSTS` and wait up to a minute for SSH.
8. **Upload the deploy bundle:** `rsync --delete` of the repository's `deploy/` directory to `/srv/motionile/bundle/`.
9. **Run deploy.sh** on the instance as `deploy` with the commit SHA as the tag.
10. **Check API and MCP health over HTTPS:** `API_URL/health/ready` and `MCP_URL/health/live`, with retries.
11. **Playwright smoke test** against `WEB_URL`.
12. **Revoke port 22** for this runner, always, even when an earlier step failed or the run was cancelled.
13. **Remove SSH credentials** from the runner, and upload the Playwright report when something failed.

GitHub records a deployment for the environment, with `WEB_URL` as its link.

### What `deploy.sh` does

`/srv/motionile/bundle/scripts/deploy.sh <tag>` runs on the instance:

1. Checks that the tag matches `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`.
2. Appends all output to `/srv/motionile/logs/deploy.log` and takes the lock `/srv/motionile/state/deploy.lock`. A second run fails at once with `another deployment holds ... deploy.lock`.
3. Runs `render-env.sh`: reads `/motionile/<env>/*` from SSM and writes `/srv/motionile/.env` (mode 600). It stops if a required parameter is missing.
4. Logs in to ECR and reads the current tag from `/srv/motionile/state/current-tag`.
5. Pulls `motionile-api:<tag>` and `motionile-worker:<tag>`. **If a pull fails, it stops and changes nothing**: the running containers, `images.env` and the state files stay as they were (only `.env` has been re-rendered from SSM).
6. Writes `/srv/motionile/state/images.env` with the new image references.
7. Runs migrations: `migrate` (`alembic upgrade head` against `DATABASE_DIRECT_URL`).
8. Runs `docker compose up --detach --remove-orphans --wait --wait-timeout 180`, which waits for every container health check, then calls `/health/ready` inside the `api` container up to 12 times, 5 seconds apart, so a wrong database or Redis credential fails the deployment.
9. **If step 7 or 8 fails, it rolls back automatically**: it writes the previous tag (the one that was in `current-tag`) back to `images.env`, pulls it and starts the services again with `--wait`, then exits with status 1. Migrations are not reverted. If there is no previous tag, it leaves the services as they are.
10. On success, moves the old tag into `previous-tag`, writes the new tag into `current-tag`, and prunes images unused for more than 24 hours.

`worker-render` has no health check, so a deployment cannot prove that Chromium's sandbox works on the host. After the first deployment that contains it, and after every Docker Engine upgrade, run [Check the render sandbox](access-and-operations.md#7-check-the-render-sandbox).

The HTTPS health check and the Playwright smoke test (steps 10 and 11 of `_deploy.yml`) run after `deploy.sh` has finished. If they fail, the job fails but nothing rolls back on its own; decide whether to roll back by hand (see below).

## Watch a deployment

From your machine:

```bash
gh run list --repo "$repo" --workflow deploy-staging.yml --limit 5
run_id=$(gh run list --repo "$repo" --workflow deploy-staging.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$run_id" --repo "$repo" --exit-status
```

Use `deploy-production.yml` for production. Expected result: every job green and exit status 0. A production run shows **Waiting** until a reviewer approves it under **Actions > Deploy production > Review deployments**.

Follow the server side in CloudWatch while it runs:

```bash
instance_id=$(tofu -chdir=infra/aws/envs/staging output -raw instance_id)
aws logs tail /motionile/staging --region ap-south-1 --follow --log-stream-name-prefix "host/$instance_id/deploy"
```

Expected result: lines such as `[deploy] deploying <SHA> to staging`, `[render-env] wrote <n> parameters`, `[deploy] running database migrations`, `[deploy] starting services and waiting up to 180s for health checks` and `[deploy] deployed <SHA>`.

Or on the instance itself:

```bash
aws ssm start-session --region ap-south-1 --target "$instance_id"
```

Inside the Session Manager shell:

```bash
sudo -iu deploy
tail -f /srv/motionile/logs/deploy.log
```

### Where logs live

| What                    | Where                                                                                               |
| ----------------------- | --------------------------------------------------------------------------------------------------- |
| Deployment log, on disk | `/srv/motionile/logs/deploy.log` on the instance                                                    |
| Deployment log, shipped | CloudWatch log group `/motionile/<env>`, stream `host/<instance id>/deploy`                         |
| Workflow log            | GitHub Actions run, step **Run deploy.sh** (the same lines as `deploy.log`)                         |
| Container logs          | `/motionile/<env>`, streams `containers/<container name>`, for example `containers/motionile-api-1` |
| Host logs               | `/motionile/<env>`, streams `host/<instance id>/syslog` and `host/<instance id>/cloud-init`         |

Useful commands as `deploy` on the instance:

```bash
/srv/motionile/bundle/scripts/compose.sh ps
/srv/motionile/bundle/scripts/compose.sh logs --tail 200 api
cat /srv/motionile/state/current-tag /srv/motionile/state/previous-tag
```

## Re-run a failed deployment

When a deployment failed for a transient reason (a network error, an ECR or SSH timeout, a flaky smoke test), re-run it:

1. Open the failed run in **Actions** and choose **Re-run jobs > Re-run failed jobs**, or:

   ```bash
   gh run rerun "$run_id" --repo "$repo" --failed
   gh run watch "$run_id" --repo "$repo" --exit-status
   ```

2. Expected result: the failed jobs run again and finish green. For staging, the build jobs that already succeeded are not repeated.

This is safe because:

- **Tags are immutable.** ECR refuses to overwrite a tag, the build skips a tag that exists, and promotion skips an image that is already in production. A re-run deploys exactly the same images.
- **Deployments cannot overlap.** The workflow concurrency groups queue runs, and `deploy.sh` holds `deploy.lock`.
- **Migrations are idempotent.** `alembic upgrade head` does nothing when the database is already at head.

Only re-run the **latest** run for an environment. A re-run deploys that run's commit, so re-running an older run after a newer one succeeded would move the environment backwards.

If the failure was not transient (the new code fails its health checks, a migration fails), a re-run fails the same way. Fix forward with a new commit, or roll back.

If a runner died before **Revoke port 22** ran, a stale rule may remain. Check and remove it:

```bash
security_group_id=$(tofu -chdir=infra/aws/envs/staging output -raw security_group_id)
aws ec2 describe-security-group-rules --region ap-south-1 \
  --filters "Name=group-id,Values=$security_group_id" \
  --query 'SecurityGroupRules[?FromPort==`22`].[SecurityGroupRuleId,CidrIpv4,Description]' --output text
aws ec2 revoke-security-group-ingress --region ap-south-1 --group-id "$security_group_id" --security-group-rule-ids <SECURITY_GROUP_RULE_ID>
```

Expected result: the first command prints nothing when no deployment is running.

## Roll back by hand

Prefer rolling forward: revert the bad change on `develop` with a pull request, let staging deploy it, and release it to `prod` as usual. Roll back by hand when production is broken and you cannot wait.

### 1. Find the tag to roll back to

On the instance, as `deploy`:

```bash
cat /srv/motionile/state/current-tag /srv/motionile/state/previous-tag
```

Expected result: two commit SHAs. `previous-tag` is the release before the current one.

To see older releases, list the last ten tags in ECR from your machine (use `production/motionile-api` for production):

```bash
aws ecr describe-images --region ap-south-1 --repository-name staging/motionile-api \
  --query 'sort_by(imageDetails,&imagePushedAt)[-10:].imageTags' --output json
git log -1 --format='%h %ad %s' <TAG>
```

Expected result: up to ten tags, newest last, and the commit each tag was built from. ECR keeps the last 30 tagged images per repository.

### 2. Check the migrations between the two tags

```bash
git diff --stat <TAG> <CURRENT_TAG> -- apps/server/migrations/versions
```

- **No output:** no migration was added after `<TAG>`. Use step 3a.
- **Files listed:** the database is at a revision that `<TAG>` does not know. `deploy.sh` would fail at `alembic upgrade head` ("Can't locate revision") and restore the current tag. Read the migration checklist below, then use step 3b.

### 3a. Roll back with `deploy.sh`

Open a Session Manager shell on the instance and switch to `deploy`:

```bash
aws ssm start-session --region ap-south-1 --target <INSTANCE_ID>
```

```bash
sudo -iu deploy
/srv/motionile/bundle/scripts/deploy.sh <TAG>
```

Expected result: the log ends with `deployed <TAG>`, the exit status is 0, and `cat /srv/motionile/state/current-tag` prints `<TAG>`.

`deploy.sh` re-renders `.env` from SSM and uses the bundle (`compose.yml`, `compose.prod.yml`, `Caddyfile`, scripts) from the **last deployment**, not from `<TAG>`. That is normally fine. If the last deployment changed those files in a way the older images cannot run with, roll forward with a revert instead.

### 3b. Roll back the images only

This starts the older images against the current schema without running migrations, the same way `deploy.sh` does its automatic rollback. As `deploy` on the instance:

```bash
export TAG=<TAG>
flock --nonblock /srv/motionile/state/deploy.lock bash -euo pipefail <<'SCRIPT'
env_value() { grep -E "^$1=" /srv/motionile/.env | tail -n 1 | cut -d "'" -f 2; }
api_image="$(env_value IMAGE_REPOSITORY_API):$TAG"
worker_image="$(env_value IMAGE_REPOSITORY_WORKER):$TAG"
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin "$(env_value ECR_REGISTRY)"
docker pull --quiet "$api_image"
docker pull --quiet "$worker_image"
printf "MOTIONILE_API_IMAGE='%s'\nMOTIONILE_WORKER_IMAGE='%s'\n" "$api_image" "$worker_image" > /srv/motionile/state/images.env
/srv/motionile/bundle/scripts/compose.sh up --detach --remove-orphans --wait --wait-timeout 180
cp /srv/motionile/state/current-tag /srv/motionile/state/previous-tag
printf '%s\n' "$TAG" > /srv/motionile/state/current-tag
SCRIPT
```

Expected result: Compose reports every container as `Healthy` or `Started`, and `cat /srv/motionile/state/current-tag` prints `<TAG>`. If the lock is held, a deployment is running; wait for it and try again.

### 4. Verify the rollback

```bash
/srv/motionile/bundle/scripts/compose.sh ps
exit
```

From your machine:

```bash
curl -fsS https://api.<DOMAIN>/health/ready
curl -fsS https://mcp.<DOMAIN>/health/live
```

Expected result: every service `running` and `healthy`, and HTTP 200 from both URLs. The next push to the branch deploys normally and records `<TAG>` as the previous tag.

## Migration-safe rollback checklist

Rolling back images never rolls back the database. Old code must therefore run on the new schema. Check this before every release and before every manual rollback:

- [ ] Every migration since the target tag follows expand/contract: it only **adds** tables, nullable columns, columns with defaults, indexes or constraints that old rows satisfy. Read each file in `git diff --stat <TAG> <CURRENT_TAG> -- apps/server/migrations/versions`.
- [ ] No migration since the target tag drops or renames a column or table that the old code reads or writes. Such a "contract" migration ships only after a release that stopped using the column, so old code no longer needs it.
- [ ] Data backfills are idempotent and leave the old columns intact, so old code still finds the data it expects.
- [ ] New behaviour that old code would break is behind a feature flag. Turn the flag off instead of rolling back when you can.
- [ ] Never run `alembic downgrade` in production unless a runbook written for that specific migration says so. Downgrades can drop data.

If a migration since the target tag is not backwards compatible, do not roll back the images. Roll forward with a fix.

## Drill: a failing health check rolls the deployment back

Run this drill on staging to prove that a deployment whose API health check fails rolls back to the previous images. Do it after staging has had at least one successful deployment. The staging API is unavailable for about three minutes.

A broken commit cannot be used for the drill: CI boots the same images in its end-to-end job, so `ci-ok` blocks it from reaching `develop`. A broken health check in the `deploy/` files would also break the rollback, because the rollback reuses the bundle. The drill therefore pushes a deliberately broken API image under a separate tag and deploys it with `deploy.sh`, which runs exactly the code path a failed GitHub deployment runs.

You need Docker with Buildx on your machine (`docker buildx version`).

1. Read the current tag. In a Session Manager shell on the staging instance, as `deploy`:

   ```bash
   cat /srv/motionile/state/current-tag
   ```

   Expected result: a commit SHA. This is `<CURRENT_TAG>`.

2. Push the drill images from your machine. The API image runs `sleep infinity` instead of the web server, so migrations still work but its health check never passes. The worker image is the current one under the new tag.

   ```bash
   current_tag=<CURRENT_TAG>
   drill_tag=rollback-drill-$(date -u +%Y%m%d)
   registry=$(tofu -chdir=infra/aws/envs/staging output -raw ecr_registry)
   drill_dir=$(mktemp -d)
   printf 'FROM %s\nCMD ["sleep", "infinity"]\n' "$registry/staging/motionile-api:$current_tag" > "$drill_dir/Dockerfile"
   aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin "$registry"
   docker buildx build --platform linux/amd64 --provenance=false --push --tag "$registry/staging/motionile-api:$drill_tag" "$drill_dir"
   docker buildx imagetools create --tag "$registry/staging/motionile-worker:$drill_tag" "$registry/staging/motionile-worker:$current_tag"
   echo "$drill_tag"
   ```

   Expected result: both images pushed, and the drill tag printed, for example `rollback-drill-20261014`.

3. Deploy the drill tag. In the Session Manager shell, as `deploy`:

   ```bash
   /srv/motionile/bundle/scripts/deploy.sh <DRILL_TAG>; echo "exit status $?"
   ```

   Expected result, after up to three minutes:

   ```text
   ... [deploy] starting services and waiting up to 180s for health checks
   ... [deploy] rolling back from <DRILL_TAG> to <CURRENT_TAG>
   ... [deploy] rollback to <CURRENT_TAG> succeeded
   ... [deploy] ERROR: deployment of <DRILL_TAG> failed health checks
   exit status 1
   ```

4. Verify the rollback:

   ```bash
   cat /srv/motionile/state/current-tag
   /srv/motionile/bundle/scripts/compose.sh ps
   grep -E 'rolling back|rollback to' /srv/motionile/logs/deploy.log | tail -n 2
   ```

   Expected result: `current-tag` is still `<CURRENT_TAG>`, every service runs the `<CURRENT_TAG>` images and is healthy, and the log shows the rollback. From your machine, `curl -fsS https://api.<STAGING_DOMAIN>/health/ready` returns HTTP 200, and the same lines appear in CloudWatch:

   ```bash
   aws logs tail /motionile/staging --region ap-south-1 --since 30m \
     --log-stream-name-prefix "host/$(tofu -chdir=infra/aws/envs/staging output -raw instance_id)/deploy" \
     --filter-pattern '"rolling back"'
   ```

5. Remove the drill images:

   ```bash
   for image in motionile-api motionile-worker; do
     aws ecr batch-delete-image --region ap-south-1 --repository-name "staging/$image" --image-ids "imageTag=$drill_tag"
   done
   rm -rf "$drill_dir"
   ```

   Expected result: each command lists the deleted image and an empty `failures` list.

6. Confirm the normal path still works: start "Deploy staging" with `gh workflow run deploy-staging.yml --repo "$repo" --ref develop` and watch it finish green.

In a real failed deployment from GitHub, the same `rolling back` and `rollback to ... succeeded` lines appear in the **Run deploy.sh** step, the job fails, and the GitHub deployment is marked as failed.
