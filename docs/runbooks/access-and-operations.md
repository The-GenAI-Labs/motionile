# Access and operations

Day-to-day access to a Motionile environment: shell access, logs, service restarts, disk space, scheduled jobs and alarms. `develop` deploys to staging and `prod` to production.

Placeholders:

| Placeholder     | Meaning                                                                  |
| --------------- | ------------------------------------------------------------------------ |
| `<ENV>`         | `staging` or `production`                                                |
| `<INSTANCE_ID>` | EC2 instance ID, found in step 1.2                                       |
| `<SERVICE>`     | One of `proxy`, `api`, `mcp`, `worker-default`, `worker-render`, `redis` |
| `<API_DOMAIN>`  | `api.<DOMAIN>` or `api.<STAGING_DOMAIN>`                                 |

All AWS commands run on your machine with credentials for the account and `--region ap-south-1`. On the instance, `compose.sh` and `docker` commands run as the `deploy` user; commands that start with `sudo` run in the `ssm-user` shell Session Manager opens, because `deploy` has no sudo rights. Type `exit` once to leave the `deploy` shell and return to `ssm-user`.

## 1. Open a shell on the instance

The instance has no SSH key pair and port 22 is closed except during deployments. Use AWS Systems Manager Session Manager.

1. Install the Session Manager plugin once.

   macOS (Apple silicon):

   ```bash
   curl -fsSL "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/mac_arm64/session-manager-plugin.pkg" -o session-manager-plugin.pkg
   sudo installer -pkg session-manager-plugin.pkg -target /
   sudo ln -sf /usr/local/sessionmanagerplugin/bin/session-manager-plugin /usr/local/bin/session-manager-plugin
   ```

   Ubuntu or Debian:

   ```bash
   curl -fsSL "https://s3.amazonaws.com/session-manager-downloads/plugin/latest/ubuntu_64bit/session-manager-plugin.deb" -o session-manager-plugin.deb
   sudo dpkg -i session-manager-plugin.deb
   ```

   Verify: `session-manager-plugin` prints `The Session Manager plugin was installed successfully. Use the AWS CLI to start a session.`

2. Find the instance ID:

   ```bash
   aws ec2 describe-instances --region ap-south-1 \
     --filters Name=tag:Name,Values=motionile-<ENV> Name=instance-state-name,Values=running \
     --query 'Reservations[].Instances[].InstanceId' --output text
   ```

   Expected result: one ID such as `i-0123456789abcdef0`. `tofu -chdir=infra/aws/envs/<ENV> output -raw instance_id` returns the same value.

3. Start a session and switch to the deploy user:

   ```bash
   aws ssm start-session --region ap-south-1 --target <INSTANCE_ID>
   ```

   ```bash
   sudo -iu deploy
   ```

   Expected result: a prompt `deploy@ip-10-...:~$`. `id` lists the `docker` group. `/srv/motionile` is owned by `deploy` with mode `0750`, so work there as `deploy`, not as `ssm-user`.

4. On a freshly created instance, confirm cloud-init finished:

   ```bash
   cloud-init status --wait
   sudo tail -n 100 /var/log/cloud-init-output.log
   ```

   Expected result: `status: done`.

Exit with `exit` twice. Session Manager records the session in CloudTrail.

Port forwarding is not needed for routine work: Redis and the application containers listen only on the Compose network, and Postgres is on Neon. Use `compose.sh exec` (section 3) instead.

## 2. Read logs in CloudWatch

Every container logs through the Docker `awslogs` driver to log group `/motionile/<ENV>`, one stream per container named `containers/<container name>`, for example `containers/motionile-api-1` and `containers/motionile-worker-default-1`. The CloudWatch agent ships host logs to the same group as `host/<INSTANCE_ID>/syslog`, `host/<INSTANCE_ID>/cloud-init` and `host/<INSTANCE_ID>/deploy` (`/srv/motionile/logs/deploy.log`). Retention is 30 days.

Follow all container logs:

```bash
aws logs tail /motionile/<ENV> --region ap-south-1 --follow --log-stream-name-prefix containers/
```

Follow one container, or the deployment log:

```bash
aws logs tail /motionile/<ENV> --region ap-south-1 --follow --log-stream-name-prefix containers/motionile-api-1
aws logs tail /motionile/<ENV> --region ap-south-1 --follow --log-stream-name-prefix host/<INSTANCE_ID>/deploy
```

Show failed tasks from the last hour:

```bash
aws logs tail /motionile/<ENV> --region ap-south-1 --since 1h \
  --log-stream-name-prefix containers/ --filter-pattern '{ $.event = "task.failed" }'
```

Expected result: one JSON object per line written by structlog, with `event`, `level`, `timestamp` and event fields.

### Logs Insights queries

Open **CloudWatch → Logs → Logs Insights**, select `/motionile/<ENV>`, pick a time range and run one of these.

API 5xx responses (fields from the `http.request` access log event):

```text
fields @timestamp, method, route, path, status, duration_ms, client_ip
| filter event = "http.request" and status >= 500
| sort @timestamp desc
| limit 100
```

5xx count per route:

```text
filter event = "http.request" and status >= 500
| stats count(*) as errors by route, status
| sort errors desc
```

Slowest routes:

```text
filter event = "http.request"
| stats count(*) as requests, avg(duration_ms) as avg_ms, pct(duration_ms, 95) as p95_ms by route
| sort p95_ms desc
| limit 20
```

Failed tasks (fields bound by `motionile.core.tasks.registry`):

```text
fields @timestamp, task, queue, task_job_id, attempt, exception
| filter event = "task.failed"
| sort @timestamp desc
| limit 50
```

The same query from the terminal:

```bash
query_id=$(aws logs start-query --region ap-south-1 --log-group-name /motionile/<ENV> \
  --start-time $(($(date +%s) - 3600)) --end-time $(date +%s) \
  --query-string 'fields @timestamp, task, queue, attempt | filter event = "task.failed" | sort @timestamp desc | limit 50' \
  --query queryId --output text)
sleep 5
aws logs get-query-results --region ap-south-1 --query-id "$query_id"
```

Expected result: `"status": "Complete"` and the matching rows.

## 3. Logs, status and restarts on the instance

`/srv/motionile/bundle/scripts/compose.sh` runs `docker compose` with `compose.yml`, `compose.prod.yml`, the rendered `/srv/motionile/.env` and the image tags of the current deployment in `/srv/motionile/state/images.env`. Always use it instead of plain `docker compose`.

Check status:

```bash
/srv/motionile/bundle/scripts/compose.sh ps
```

Expected result: `proxy`, `api`, `mcp`, `worker-default`, `worker-render` and `redis` are `running`; `api`, `mcp` and `redis` show `(healthy)`. The `migrate` service only runs during deployments.

Read logs locally (Docker dual logging keeps a local copy next to `awslogs`):

```bash
/srv/motionile/bundle/scripts/compose.sh logs --follow --tail 200 <SERVICE>
```

Restart one service:

```bash
/srv/motionile/bundle/scripts/compose.sh restart <SERVICE>
/srv/motionile/bundle/scripts/compose.sh ps <SERVICE>
```

Expected result: the service is `running` again (and `healthy` where it has a health check). `restart` keeps the current container and configuration; it does not read new SSM values. To apply changed parameters, redeploy (see [secrets-rotation.md](secrets-rotation.md#redeploy-with-the-current-tag)).

Recreate one service with its current configuration (for example after a crash loop):

```bash
/srv/motionile/bundle/scripts/compose.sh up --detach --wait --wait-timeout 180 <SERVICE>
```

Useful extras:

```bash
cat /srv/motionile/state/current-tag /srv/motionile/state/previous-tag
tail -n 100 /srv/motionile/logs/deploy.log
/srv/motionile/bundle/scripts/compose.sh exec redis redis-cli ping
curl -fsS https://<API_DOMAIN>/health/ready
```

`redis-cli` authenticates through `REDISCLI_AUTH` inside the container; expected answer `PONG`. The readiness check expects `{"status":"ok","checks":{"postgres":"ok","redis":"ok"}}`.

Never stop `worker-render` while a render runs unless you accept that the task is retried; it has a 10-minute stop grace period. `worker-default` has 60 seconds.

## 4. Recover disk space

Alarms `motionile-<ENV>-disk-root-high` and `motionile-<ENV>-disk-data-high` fire above 80 percent. The root volume (50 GB) holds Docker images, container layers and the journal. The data volume (`data_volume_size_gb`, 100 GB staging, 200 GB production) at `/srv/motionile/data` holds Redis and Caddy data.

1. Measure. Run the `docker` command as `deploy` and the `sudo` commands as `ssm-user`:

   ```bash
   df -h / /srv/motionile/data
   docker system df
   sudo du -xsh /var/lib/docker /var/log /srv/motionile/data/* 2>/dev/null
   sudo journalctl --disk-usage
   ```

2. Free the root volume:

   ```bash
   docker image prune --all --force --filter until=24h
   docker builder prune --force
   sudo journalctl --vacuum-size=200M
   ```

   Expected result: `Total reclaimed space` lines and a lower `Use%` in `df -h /`. The images of the running deployment are in use and are never removed. `deploy.sh` already prunes images unused for 24 hours after every deployment, and the weekly `motionile-docker-prune.timer` prunes images and build cache older than 7 days.

3. Check Redis on the data volume:

   ```bash
   sudo du -sh /srv/motionile/data/redis/appendonlydir /srv/motionile/data/redis/dump.rdb
   /srv/motionile/bundle/scripts/compose.sh exec redis redis-cli INFO persistence | grep -E '^(aof_current_size|aof_base_size|aof_rewrite_in_progress)'
   /srv/motionile/bundle/scripts/compose.sh exec redis redis-cli INFO memory | grep -E '^used_memory_human'
   ```

   If `aof_current_size` is several times `aof_base_size`, compact the AOF:

   ```bash
   /srv/motionile/bundle/scripts/compose.sh exec redis redis-cli BGREWRITEAOF
   ```

   Expected result: `Background append only file rewriting started`, then `aof_rewrite_in_progress:0` and a smaller `aof_current_size`. Redis runs with `noeviction`; if memory itself is the problem, find the growing keys rather than deleting data blindly.

4. Grow the data volume when it is genuinely full. Prefer OpenTofu so state stays accurate:

   1. In `infra/aws/envs/<ENV>/terraform.tfvars` set `data_volume_size_gb` to the new size (larger only).
   2. Apply:

      ```bash
      cd infra/aws/envs/<ENV>
      tofu init -backend-config=bucket=<STATE_BUCKET_NAME>
      tofu plan -out=tfplan
      tofu apply tfplan
      ```

      Expected result: the plan shows `module.environment.module.compute.aws_ebs_volume.data` updated in place (`size`), nothing replaced.

   In an emergency, use the AWS CLI and then set the same value in `terraform.tfvars` so the next plan is clean:

   ```bash
   volume_id=$(aws ec2 describe-volumes --region ap-south-1 \
     --filters Name=tag:Name,Values=motionile-<ENV>-data \
     --query 'Volumes[0].VolumeId' --output text)
   aws ec2 modify-volume --region ap-south-1 --volume-id "$volume_id" --size <NEW_SIZE_GB>
   aws ec2 describe-volumes-modifications --region ap-south-1 --volume-ids "$volume_id" \
     --query 'VolumesModifications[0].[ModificationState,TargetSize]' --output text
   ```

   Wait until the state is `optimizing` or `completed`, then grow the file system on the instance (the volume has no partition table, the file system is on the whole device):

   ```bash
   sudo resize2fs "$(findmnt -no SOURCE /srv/motionile/data)"
   df -h /srv/motionile/data
   ```

   Expected result: `The filesystem on /dev/nvme1n1 is now ... blocks long` and the new size in `df`. No restart is needed. AWS allows one modification per volume every 6 hours.

## 5. Scheduled jobs

| Timer                          | Schedule (UTC)                   | Job                                                                                                    |
| ------------------------------ | -------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `motionile-redis-backup.timer` | daily 21:00, up to 15 min late   | `backup-redis.sh`: `BGSAVE`, upload to `s3://motionile-<ENV>-<ACCOUNT_ID>-backup/redis/<ENV>/<stamp>/` |
| `motionile-docker-prune.timer` | Sundays 22:00, up to 30 min late | Prune Docker images and build cache older than 7 days                                                  |
| DLM policy (AWS, not systemd)  | daily from 20:30                 | Snapshot of the data volume, 7 kept                                                                    |

Check them:

```bash
systemctl list-timers 'motionile-*'
sudo journalctl -u motionile-redis-backup.service --since '-2 days' --no-pager
sudo journalctl -u motionile-docker-prune.service --since '-8 days' --no-pager
```

Expected result: both timers listed with a `NEXT` time; the backup journal ends with `uploaded backup to s3://.../redis/<ENV>/<YYYYMMDDTHHMMSSZ>` and `Deactivated successfully`.

Run a backup now:

```bash
sudo systemctl start motionile-redis-backup.service
sudo journalctl -u motionile-redis-backup.service -n 20 --no-pager
```

Check the snapshots:

```bash
aws ec2 describe-snapshots --region ap-south-1 --owner-ids self \
  --filters Name=tag:Snapshot,Values=motionile-<ENV>-data \
  --query 'sort_by(Snapshots,&StartTime)[].[SnapshotId,StartTime,State]' --output table
```

Expected result: up to 7 snapshots, the newest from the last 24 hours, all `completed`.

## 6. Alarms

All alarms notify SNS topic `motionile-<ENV>-alerts`, which emails `alert_email`.

| Alarm                                    | Fires when                                                                        |
| ---------------------------------------- | --------------------------------------------------------------------------------- |
| `motionile-<ENV>-cpu-high`               | CPU above 80 percent for 15 minutes                                               |
| `motionile-<ENV>-memory-high`            | Memory above 80 percent for 15 minutes                                            |
| `motionile-<ENV>-disk-root-high`         | `/` above 80 percent for 10 minutes                                               |
| `motionile-<ENV>-disk-data-high`         | `/srv/motionile/data` above 80 percent for 10 minutes                             |
| `motionile-<ENV>-api-5xx-rate`           | More than 5 percent 5xx in two consecutive 5-minute periods (20 requests minimum) |
| `motionile-<ENV>-task-failures`          | 5 or more `task.failed` events in 15 minutes                                      |
| `motionile-<ENV>-system-status-recovery` | Host system check fails for 2 minutes; EC2 also recovers the instance             |

CPU, memory and disk alarms treat missing data as breaching, so they also fire when the CloudWatch agent stops sending metrics. Check the agent with `sudo systemctl status amazon-cloudwatch-agent` before chasing a phantom memory problem.

### Confirm the email subscription

```bash
topic_arn=$(aws sns list-topics --region ap-south-1 --query "Topics[?ends_with(TopicArn, ':motionile-<ENV>-alerts')].TopicArn" --output text)
aws sns list-subscriptions-by-topic --region ap-south-1 --topic-arn "$topic_arn" \
  --query 'Subscriptions[].[Protocol,Endpoint,SubscriptionArn]' --output table
```

Expected result: the email row has a full ARN, not `PendingConfirmation`. If it is pending, click the link in the "AWS Notification - Subscription Confirmation" email.

### Acknowledge an alarm

CloudWatch has no acknowledge button. Handle an alarm like this:

1. List what is firing:

   ```bash
   aws cloudwatch describe-alarms --region ap-south-1 --alarm-name-prefix motionile-<ENV>- --state-value ALARM \
     --query 'MetricAlarms[].[AlarmName,StateUpdatedTimestamp,StateReason]' --output table
   ```

2. Reply to the alert email thread (or your incident channel) with "investigating" so others know someone owns it.
3. If the alarm will keep re-notifying while you fix the cause, mute its actions and remember to unmute:

   ```bash
   aws cloudwatch disable-alarm-actions --region ap-south-1 --alarm-names motionile-<ENV>-<ALARM_SUFFIX>
   aws cloudwatch enable-alarm-actions --region ap-south-1 --alarm-names motionile-<ENV>-<ALARM_SUFFIX>
   ```

4. The alarm returns to `OK` by itself when the metric recovers and sends an OK email.

### Test an alarm

```bash
aws cloudwatch set-alarm-state --region ap-south-1 \
  --alarm-name motionile-<ENV>-task-failures \
  --state-value ALARM --state-reason "Alarm test"
```

Expected result: within a minute an email "ALARM: motionile-<ENV>-task-failures" arrives with reason `Alarm test`. At the next evaluation (up to 15 minutes for this alarm) the alarm returns to `OK` and an OK email follows. Do not test `motionile-<ENV>-system-status-recovery` this way: its action recovers the instance.

## 7. Check the render sandbox

`worker-render` starts Chromium with its own sandbox enabled and never with `--no-sandbox` ([ADR 0026](../adr/0026-render-sandbox-design.md)). Run this check after the first deployment of Phase 8, after a Docker Engine upgrade, and whenever renders fail with `browser_crash` and a `No usable sandbox` message in the logs. On the instance as `deploy`:

```bash
/srv/motionile/bundle/scripts/compose.sh exec -T worker-render id
/srv/motionile/bundle/scripts/compose.sh exec -T worker-render grep -E '^(Seccomp|NoNewPrivs|CapEff)' /proc/self/status
/srv/motionile/bundle/scripts/compose.sh exec -T worker-render python - <<'PY'
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(chromium_sandbox=True)
        page = await browser.new_page()
        await page.set_content("<p>sandboxed</p>")
        print(await page.inner_text("p"))
        await browser.close()

asyncio.run(main())
PY
```

Expected result:

- `uid=10001(app) gid=10001(app)`.
- `Seccomp:	2`, `NoNewPrivs:	1` and `CapEff:	0000000000000000`.
- The last command prints `sandboxed`. `chromium_sandbox=True` matters: without it Playwright adds `--no-sandbox` itself and the check proves nothing.

If the launch fails with `No usable sandbox` or `Operation not permitted` on `clone`:

1. Confirm the container really uses the Playwright profile: `compose.sh config | grep -A3 security_opt` must list `seccomp=` followed by the profile content, not `unconfined`.
2. Confirm the container runs under Docker's default AppArmor profile (as `ssm-user`):

   ```bash
   docker inspect --format '{{.AppArmorProfile}}' "$(docker ps --quiet --filter name=worker-render)"
   sudo sysctl kernel.apparmor_restrict_unprivileged_userns
   ```

   Expected result: `docker-default` and a value of `1` or `0`. An empty profile means AppArmor is off for the container and is not the cause.

3. Upgrade Docker Engine if it is older than the current stable release (`apt-cache policy docker-ce`, then `sudo apt-get install --only-upgrade docker-ce docker-ce-cli containerd.io`), recreate the service ([Logs, status and restarts](#3-logs-status-and-restarts-on-the-instance)) and run the check again.
4. Only if the check still fails with the restriction set to `1`, relax it host-wide, run the check again, and record the change in the operations log. This lets every process on the instance create user namespaces, so remove it as soon as step 3 or a Docker fix makes it unnecessary:

   ```bash
   sudo sysctl --write kernel.apparmor_restrict_unprivileged_userns=0
   echo 'kernel.apparmor_restrict_unprivileged_userns = 0' | sudo tee /etc/sysctl.d/60-motionile-userns.conf
   ```

   To undo it: `sudo rm /etc/sysctl.d/60-motionile-userns.conf && sudo sysctl --write kernel.apparmor_restrict_unprivileged_userns=1`.

Never work around a failing check with `--no-sandbox`, `privileged: true`, `apparmor=unconfined` or `seccomp=unconfined`; each of them removes a layer that the sandbox design depends on.
