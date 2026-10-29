# Backups and restore

What Motionile backs up, where it lives, how to restore each part, and the quarterly drill that proves it works. `develop` deploys to staging and `prod` to production; run every restore on staging first when you have the choice.

Placeholders:

| Placeholder     | Meaning                                                                                                  |
| --------------- | -------------------------------------------------------------------------------------------------------- |
| `<ENV>`         | `staging` or `production`                                                                                |
| `<ACCOUNT_ID>`  | AWS account ID: `aws sts get-caller-identity --query Account --output text`                              |
| `<INSTANCE_ID>` | EC2 instance ID, see [access-and-operations.md](access-and-operations.md#1-open-a-shell-on-the-instance) |
| `<API_DOMAIN>`  | `api.<DOMAIN>` or `api.<STAGING_DOMAIN>`                                                                 |

Bucket names follow `motionile-<ENV>-<ACCOUNT_ID>-media` and `motionile-<ENV>-<ACCOUNT_ID>-backup`; `tofu output -raw media_bucket_name` and `tofu output -raw backup_bucket_name` print them. The OpenTofu state bucket is `motionile-tofu-state-<ACCOUNT_ID>` unless `state_bucket_name` was set in `infra/aws/bootstrap`.

## What is backed up

| Data                                                                                             | Mechanism                                                                                                                   | Location                                                                   | Retention                                                          |
| ------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Postgres (all application data)                                                                  | Neon history (instant restore / point-in-time restore)                                                                      | Neon project `motionile-<ENV>`                                             | History window of the plan: up to 7 days (Launch), 30 days (Scale) |
| Redis (rate-limit windows, short-lived auth state such as OTPs and the session denylist, caches) | `motionile-redis-backup.timer` daily at 21:00 UTC runs `backup-redis.sh`: `BGSAVE`, then `dump.rdb` and `appendonly.tar.gz` | `s3://motionile-<ENV>-<ACCOUNT_ID>-backup/redis/<ENV>/<YYYYMMDDTHHMMSSZ>/` | 30 days (bucket lifecycle `expire-backups`)                        |
| Data volume `/srv/motionile/data` (Redis files, Caddy certificates and ACME account)             | DLM policy, daily from 20:30 UTC                                                                                            | EBS snapshots tagged `Snapshot=motionile-<ENV>-data`                       | 7 snapshots                                                        |
| Media objects                                                                                    | S3 versioning on the media bucket                                                                                           | `motionile-<ENV>-<ACCOUNT_ID>-media`                                       | Overwritten or deleted versions kept 30 days (`tmp/` 1 day)        |
| OpenTofu state                                                                                   | S3 versioning on the state bucket                                                                                           | `s3://motionile-tofu-state-<ACCOUNT_ID>/<ENV>/terraform.tfstate`           | Previous versions kept 90 days                                     |
| CloudFront access logs                                                                           | Standard logs v2                                                                                                            | `s3://motionile-<ENV>-<ACCOUNT_ID>-backup/cloudfront/`                     | 30 days                                                            |
| Secrets                                                                                          | SSM SecureString parameters, plus the owner's password manager                                                              | `/motionile/<ENV>/*`                                                       | Current value only; the password manager is the backup             |

Not backed up: container logs beyond 30 days in CloudWatch, and the root volume of the instance (it is rebuilt by cloud-init).

## 1. Restore Postgres to a point in time

Use this for data loss or corruption caused by a bad migration, a bug or a manual mistake.

1. Find the moment just before the damage in UTC. Use the API logs (`aws logs tail /motionile/<ENV> --since 6h --log-stream-name-prefix containers/`) and Neon **Time Travel Assist** to query the branch at candidate timestamps.
2. Stop the workers so they do not run jobs against data that is about to change. On the instance as `deploy`:

   ```bash
   /srv/motionile/bundle/scripts/compose.sh stop worker-default worker-generation worker-render
   ```

   Expected result: both show `exited` in `compose.sh ps`.

3. Restore in the Neon Console: select the root branch (`staging` or `production`), open **Postgres database → Backup & Restore → Restore from history**, keep **From history**, enter the timestamp, click **Next**, review, click **Restore**. Details and the alternative of restoring into a new branch are in [neon-setup.md](neon-setup.md#point-in-time-restore).

   Expected result: within seconds the branch shows the restored state, and a root branch `<branch>_old_<timestamp>` holds the pre-restore data.

4. If the restore point is before a migration that the running images need, redeploy the current tag so `deploy.sh` reapplies migrations (see [secrets-rotation.md](secrets-rotation.md#redeploy-with-the-current-tag)). Otherwise start the workers:

   ```bash
   /srv/motionile/bundle/scripts/compose.sh up --detach --wait --wait-timeout 180
   ```

5. Verify:

   ```bash
   curl -fsS https://<API_DOMAIN>/health/ready
   ```

   Expected result: `{"status":"ok","checks":{"postgres":"ok","redis":"ok"}}`. Spot-check the repaired records with `psql "<DIRECT_URL>"`.

6. Redis is not rolled back. It holds only short-lived state (rate-limit windows and, from Phase 4, OTPs, OAuth state and the session denylist, all with TTLs of minutes); idempotency records and the task queue live in Postgres and are restored with it. Restore Redis too (section 2) only if the incident also corrupted Redis.

To undo the restore, run instant restore again with **From another branch** and select `<branch>_old_<timestamp>`.

## 2. Restore Redis from the backup bucket

`restore-redis.sh` stops `api`, `mcp`, `worker-default`, `worker-generation`, `worker-render` and `redis`, replaces `/srv/motionile/data/redis` with the backup, and starts everything with `--wait`. The API returns `502` from Caddy while it runs, usually under a minute. Everything written to Redis after the backup time is lost.

1. Open a shell on the instance as `deploy` ([access-and-operations.md](access-and-operations.md#1-open-a-shell-on-the-instance)).
2. List backups:

   ```bash
   /srv/motionile/bundle/scripts/restore-redis.sh --list
   ```

   Expected result: one UTC timestamp per line, for example `20261014T210312Z`, oldest first.

3. Restore one (or `latest`):

   ```bash
   /srv/motionile/bundle/scripts/restore-redis.sh <YYYYMMDDTHHMMSSZ> --yes
   ```

   Expected result: log lines ending with `restored Redis from <YYYYMMDDTHHMMSSZ>`. The script refuses to run without `--yes` and rejects malformed timestamps.

4. Verify:

   ```bash
   /srv/motionile/bundle/scripts/compose.sh ps
   /srv/motionile/bundle/scripts/compose.sh exec redis redis-cli DBSIZE
   curl -fsS https://<API_DOMAIN>/health/ready
   ```

   Expected result: every service `running` (`healthy` where checked), a non-zero key count if the backup had data, and readiness `ok`.

## 3. Restore files from an EBS snapshot

Use this when files on `/srv/motionile/data` are lost or damaged, for example Caddy's certificates (to avoid Let's Encrypt rate limits after a wipe) or Redis files when no S3 backup is recent enough. The safe procedure attaches a volume made from the snapshot as a second disk, mounts it read-only, copies back only what you need, then deletes it. The live data volume and OpenTofu state are never touched.

Run steps 1 to 4 on your machine.

1. Find the snapshot:

   ```bash
   aws ec2 describe-snapshots --region ap-south-1 --owner-ids self \
     --filters Name=tag:Snapshot,Values=motionile-<ENV>-data Name=status,Values=completed \
     --query 'sort_by(Snapshots,&StartTime)[].[SnapshotId,StartTime,VolumeSize]' --output table
   ```

   Expected result: up to 7 rows. Note the `SnapshotId` taken before the damage as `<SNAPSHOT_ID>`.

2. Find the instance's Availability Zone:

   ```bash
   aws ec2 describe-instances --region ap-south-1 --instance-ids <INSTANCE_ID> \
     --query 'Reservations[0].Instances[0].Placement.AvailabilityZone' --output text
   ```

   Expected result: for example `ap-south-1a`; use it as `<AZ>`.

3. Create a volume from the snapshot. Do not give it the `Snapshot` tag, so the DLM policy ignores it:

   ```bash
   restore_volume_id=$(aws ec2 create-volume --region ap-south-1 \
     --snapshot-id <SNAPSHOT_ID> --availability-zone <AZ> --volume-type gp3 \
     --tag-specifications 'ResourceType=volume,Tags=[{Key=Name,Value=motionile-<ENV>-data-restore}]' \
     --query VolumeId --output text)
   aws ec2 wait volume-available --region ap-south-1 --volume-ids "$restore_volume_id"
   echo "$restore_volume_id"
   ```

   Expected result: a `vol-...` ID. The volume is encrypted because the snapshot is.

4. Attach it as `/dev/sdg`:

   ```bash
   aws ec2 attach-volume --region ap-south-1 --volume-id "$restore_volume_id" --instance-id <INSTANCE_ID> --device /dev/sdg
   aws ec2 wait volume-in-use --region ap-south-1 --volume-ids "$restore_volume_id"
   ```

On the instance, in the `ssm-user` shell (it has sudo):

5. Find the device. On Nitro instances it appears as NVMe; its by-id name contains the volume ID without the dash:

   ```bash
   ls -l /dev/disk/by-id/ | grep Elastic_Block_Store
   restore_device=/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_<VOLUME_ID_WITHOUT_DASH>
   ```

   For `vol-0abc123` use `nvme-Amazon_Elastic_Block_Store_vol0abc123`.

6. Mount read-only. `noload` skips journal replay, which would otherwise write to the device; the copy has the same file system UUID as the live volume, so always mount it by device path, never by UUID:

   ```bash
   sudo mkdir -p /mnt/restore
   sudo mount -o ro,noload "$restore_device" /mnt/restore
   sudo ls -la /mnt/restore /mnt/restore/redis /mnt/restore/caddy/data
   ```

   Expected result: the same layout as `/srv/motionile/data`: `redis/`, `caddy/data/`, `caddy/config/`.

7. Stop the services that own the directory, copy, and start them again. As `deploy` stop the services (Caddy example; for Redis use `api mcp worker-default worker-generation worker-render redis`):

   ```bash
   /srv/motionile/bundle/scripts/compose.sh stop proxy
   ```

   As `ssm-user` copy (preserves owners and modes):

   ```bash
   sudo rsync -aH --numeric-ids --delete /mnt/restore/caddy/data/ /srv/motionile/data/caddy/data/
   ```

   For Redis: `sudo rsync -aH --numeric-ids --delete /mnt/restore/redis/ /srv/motionile/data/redis/`.

   As `deploy` start everything:

   ```bash
   /srv/motionile/bundle/scripts/compose.sh up --detach --wait --wait-timeout 180
   ```

   Expected result: all services healthy; `curl -fsS https://<API_DOMAIN>/health/ready` returns `ok`.

8. Clean up. On the instance:

   ```bash
   sudo umount /mnt/restore
   ```

   On your machine:

   ```bash
   aws ec2 detach-volume --region ap-south-1 --volume-id "$restore_volume_id"
   aws ec2 wait volume-available --region ap-south-1 --volume-ids "$restore_volume_id"
   aws ec2 delete-volume --region ap-south-1 --volume-id "$restore_volume_id"
   ```

   Expected result: `aws ec2 describe-volumes --region ap-south-1 --filters Name=tag:Name,Values=motionile-<ENV>-data-restore --query 'Volumes[].VolumeId'` returns `[]`. Never reboot with the restore volume attached and mounted.

### If the live data volume itself is lost

Only when `/srv/motionile/data` is unusable (volume deleted or the file system cannot be repaired), make the restored volume the data volume. This changes OpenTofu state, so do it carefully:

1. Create the volume from the snapshot as in step 3, but with the same tags the module sets: `Name=motionile-<ENV>-data` and `Snapshot=motionile-<ENV>-data`, and the size equal to `data_volume_size_gb`.
2. Stop all services (`compose.sh down`), unmount `/srv/motionile/data`, detach the broken volume, attach the restored one as `/dev/sdf`. The `/etc/fstab` entry mounts by UUID, and a volume made from the snapshot keeps the UUID, so `sudo mount /srv/motionile/data` mounts it.
3. In `infra/aws/envs/<ENV>`, replace the state entries:

   ```bash
   tofu state rm module.environment.module.compute.aws_volume_attachment.data
   tofu state rm module.environment.module.compute.aws_ebs_volume.data
   tofu import module.environment.module.compute.aws_ebs_volume.data <NEW_VOLUME_ID>
   tofu import module.environment.module.compute.aws_volume_attachment.data /dev/sdf:<NEW_VOLUME_ID>:<INSTANCE_ID>
   tofu plan
   ```

   Expected result: the plan shows no change for the volume and the attachment. Delete the broken volume only after the plan is clean and services are healthy.

## 4. Restore a media object

The media bucket keeps every overwritten or deleted version for 30 days (objects under `tmp/` for 1 day).

1. List the versions of the key:

   ```bash
   aws s3api list-object-versions --region ap-south-1 \
     --bucket motionile-<ENV>-<ACCOUNT_ID>-media --prefix '<OBJECT_KEY>' \
     --query '{versions: Versions[].[Key,VersionId,IsLatest,LastModified,Size], deleteMarkers: DeleteMarkers[].[Key,VersionId,IsLatest,LastModified]}' \
     --output json
   ```

2. If the object was deleted, the latest entry is a delete marker. Remove the marker and the previous version becomes current:

   ```bash
   aws s3api delete-object --region ap-south-1 \
     --bucket motionile-<ENV>-<ACCOUNT_ID>-media --key '<OBJECT_KEY>' --version-id '<DELETE_MARKER_VERSION_ID>'
   ```

3. If the object was overwritten, copy the good version over the current one (works up to 5 GB):

   ```bash
   aws s3api copy-object --region ap-south-1 \
     --bucket motionile-<ENV>-<ACCOUNT_ID>-media --key '<OBJECT_KEY>' \
     --copy-source 'motionile-<ENV>-<ACCOUNT_ID>-media/<OBJECT_KEY>?versionId=<GOOD_VERSION_ID>'
   ```

4. If the CDN served the wrong content, invalidate it (`/media/...` and `/share/...` keys only):

   ```bash
   aws cloudfront create-invalidation --distribution-id <CLOUDFRONT_DISTRIBUTION_ID> --paths '/<OBJECT_KEY>'
   ```

Verify:

```bash
aws s3api head-object --region ap-south-1 --bucket motionile-<ENV>-<ACCOUNT_ID>-media --key '<OBJECT_KEY>' \
  --query '[VersionId,LastModified,ContentLength]'
```

Expected result: the restored version's size and date. Any database row that points at the key must still exist; restore it with section 1 if it does not.

## 5. Restore the OpenTofu state

Only needed if a state file was corrupted or an apply wrote a wrong state.

1. Make sure nobody runs OpenTofu, and that no lock object `<ENV>/terraform.tfstate.tflock` exists:

   ```bash
   aws s3api list-object-versions --bucket motionile-tofu-state-<ACCOUNT_ID> --prefix <ENV>/terraform.tfstate \
     --query 'Versions[].[Key,VersionId,IsLatest,LastModified]' --output table
   ```

2. Copy the good version over the current one:

   ```bash
   aws s3api copy-object --bucket motionile-tofu-state-<ACCOUNT_ID> --key <ENV>/terraform.tfstate \
     --copy-source 'motionile-tofu-state-<ACCOUNT_ID>/<ENV>/terraform.tfstate?versionId=<GOOD_VERSION_ID>'
   ```

3. Run `tofu plan` in `infra/aws/envs/<ENV>` and read it carefully. Resources created after the restored version are missing from state and must be imported, not recreated.

## 6. Quarterly restore drill

Run once per quarter on staging, and once a year on production for the Postgres part. Record the evidence in the operations log (an issue labelled `restore-drill` works well).

| Check                                                                                                      | Evidence to record                                                                           |
| ---------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Neon history window matches the plan decision                                                              | Screenshot of **Settings → Postgres → History window**                                       |
| Postgres: create a branch from a point 24 hours ago, connect, count rows in a key table, delete the branch | Timestamp used, row counts on the branch and on the root, time taken                         |
| Redis: latest S3 backup is less than 26 hours old                                                          | Output of `restore-redis.sh --list \| tail -n 3`                                             |
| Redis: full restore of `latest` on staging                                                                 | Log line `restored Redis from ...`, `DBSIZE` before and after, minutes of API downtime       |
| EBS: newest snapshot is less than 26 hours old and 7 exist                                                 | Output of the `describe-snapshots` command in section 3                                      |
| EBS: restore volume attach, read-only mount, listing, detach, delete (section 3, steps 1 to 6 and 8)       | `ls -la /mnt/restore` output, volume ID, confirmation it was deleted                         |
| Media: upload a test object under `tmp/drill/`, overwrite it, restore the first version                    | Both version IDs and the `head-object` output                                                |
| State bucket versioning is enabled                                                                         | `aws s3api get-bucket-versioning --bucket motionile-tofu-state-<ACCOUNT_ID>` shows `Enabled` |
| Secrets: every owner parameter in `deploy/parameters.csv` has a current copy in the password manager       | Checklist of names, never values                                                             |
| Alarm path: `set-alarm-state` test email received                                                          | Time sent and time received                                                                  |

Close the drill with the measured recovery times and any runbook step that did not match reality; fix the runbook in the same week.
