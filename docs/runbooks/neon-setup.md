# Neon setup

Create the Postgres databases for staging and production on Neon and hand their connection strings to the servers through SSM. In this repository `develop` deploys to staging and `prod` to production.

Placeholders:

| Placeholder     | Meaning                                                                     |
| --------------- | --------------------------------------------------------------------------- |
| `<ENV>`         | `staging` or `production`                                                   |
| `<PASSWORD>`    | Password Neon shows for the `motionile` role                                |
| `<ENDPOINT_ID>` | Compute endpoint ID in the host name, for example `ep-cool-darkness-123456` |
| `<REGION_HOST>` | Region part of the host name, `ap-southeast-1.aws.neon.tech` for Singapore  |
| `<DIRECT_URL>`  | Direct connection string built in step 5                                    |
| `<ELASTIC_IP>`  | `tofu output -raw elastic_ip` of the environment                            |
| `<API_DOMAIN>`  | `api.<DOMAIN>` or `api.<STAGING_DOMAIN>`                                    |

## Decisions

- **Region: AWS Asia Pacific (Singapore), `aws-ap-southeast-1`.** Neon has no Mumbai (`ap-south-1`) region; its AWS regions are N. Virginia, Ohio, Oregon, Frankfurt, London, Singapore, Sydney and São Paulo. Singapore is the closest to the EC2 instance in `ap-south-1`. Expect roughly 55 to 65 ms round trip per query between Mumbai and Singapore. A request that runs five sequential queries spends about 300 ms on the network alone, so keep queries per request low and batch where possible. The region of a Neon project can never change; moving later means a new project and a data migration. If Neon adds Mumbai, plan a migration then, or switch to RDS in `ap-south-1` with `enable_rds = true`.
- **Postgres 17** for both environments, matching the local Compose and CI images.
- **One Neon project per environment.** Staging is project `motionile-staging` whose root branch is named `staging`; production is project `motionile-production` whose root branch is named `production`. A separate production project is recommended because:
  - instant restore (point-in-time restore) works only on root branches, so a `staging` child branch inside the production project could not be restored on its own, and restoring the root would roll back both;
  - the history window, IP allow list, compute settings and plan limits are per project, so production can have a 30-day window and an IP allow list without paying for them on staging;
  - console access, API keys and role passwords for staging can never reach production data, and a mistaken reset or restore in staging cannot touch production.
- **Database `motionile`, role `motionile`.** The role owns the database; console-created roles are members of `neon_superuser`, which can create the extensions the first migration needs.

## Steps

Repeat the steps for staging, then for production, replacing names as shown.

### 1. Create the project

1. In the Neon Console choose **New project**.
2. Set **Project name** `motionile-<ENV>`, **Postgres version** `17`, **Cloud provider** AWS, **Region** `AWS Asia Pacific (Singapore)`. Click **Create**.
3. Open **Branches**. On the default root branch open the menu, choose **Rename**, and name it `staging` (staging project) or `production` (production project).

Expected result: the project overview lists region `aws-ap-southeast-1` and Postgres 17, with one root branch named after the environment.

Verify: **Project** panel on the **Overview** page shows **Region** `AWS Asia Pacific (Singapore)`.

### 2. Create the role and the database

1. Select the root branch. Under **Postgres database → Roles** click **Add role**, enter `motionile`, click **Create**. Copy the password into your password manager as `motionile-<ENV> Neon motionile role`. Neon shows it only once.
2. Under **Postgres database → Databases** click **New database**, enter `motionile`, choose owner `motionile`, click **Create**.
3. Optional: delete the default `neondb` database so nothing connects to it by mistake.

Expected result: role `motionile` and database `motionile` exist on the root branch.

### 3. Set the history window and compute

1. Open **Settings → Postgres → History window**. Choose the longest your plan allows for production (Scale: 30 days; Launch: 7 days). Staging can stay at 1 day. Click **Save**.

   | Plan   | Default | Maximum                 |
   | ------ | ------- | ----------------------- |
   | Free   | 6 hours | 6 hours, capped at 1 GB |
   | Launch | 1 day   | 7 days                  |
   | Scale  | 1 day   | 30 days                 |

2. Production only: edit the compute of the `production` branch and turn **Scale to zero** off so the first request after idle time does not wait for a cold start.

Expected result: the history window shows the chosen value. Restore points older than the window are gone for good, so the window is your database recovery point limit.

### 4. Pre-create the extensions

Migration `0001` (`apps/server/migrations/versions/20261013_0001_enable_extensions_and_task_queue.py`) runs `CREATE EXTENSION IF NOT EXISTS` for `vector`, `citext` and `pgcrypto`, so the first deployment creates them anyway. Creating them now proves the role has the permission before a deployment depends on it.

Open **SQL Editor**, select branch `<ENV>`, database `motionile`, role `motionile`, and run:

```sql
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "citext";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
SELECT extname, extversion FROM pg_extension ORDER BY extname;
```

Expected result: four rows, `citext`, `pgcrypto`, `plpgsql` and `vector`.

Downgrading migration `0001` drops these extensions again; never downgrade below `0001` on a deployed database.

### 5. Build the two connection strings

1. On the project dashboard click **Connect**. Select branch `<ENV>`, database `motionile`, role `motionile`.
2. With **Connection pooling** on, copy the string. Its host contains `-pooler`, for example `<ENDPOINT_ID>-pooler.<REGION_HOST>`.
3. With **Connection pooling** off, copy the string again. Its host has no `-pooler`.
4. Keep both exactly as Neon shows them, including `sslmode=require` and `channel_binding=require`. They have these forms:

```text
DATABASE_URL=postgresql://motionile:<PASSWORD>@<ENDPOINT_ID>-pooler.<REGION_HOST>/motionile?sslmode=require&channel_binding=require
DATABASE_DIRECT_URL=postgresql://motionile:<PASSWORD>@<ENDPOINT_ID>.<REGION_HOST>/motionile?sslmode=require&channel_binding=require
```

What each one is for:

- `DATABASE_URL` is the pooled (PgBouncer, transaction mode) endpoint the API and the MCP server use through SQLAlchemy and asyncpg. asyncpg does not understand libpq parameters, so the server rewrites `sslmode` to asyncpg's `ssl` and drops `channel_binding` before connecting (`for_asyncpg` in `apps/server/src/motionile/core/config.py`).
- `DATABASE_DIRECT_URL` is the direct endpoint used by Alembic migrations and the procrastinate workers through psycopg (libpq), which uses the parameters as they are. Workers need a direct connection because procrastinate uses `LISTEN/NOTIFY`, which a transaction-mode pooler does not support.
- `DATABASE_STATEMENT_CACHE_SIZE=0` disables asyncpg's prepared statement cache behind the pooler. OpenTofu writes it as an infrastructure parameter from the `database_statement_cache_size` variable, whose default is `0`; leave it.

Verify both endpoints from your machine (psql always takes `sslmode`):

```bash
psql "postgresql://motionile:<PASSWORD>@<ENDPOINT_ID>.<REGION_HOST>/motionile?sslmode=require" -c 'select current_user, current_database(), version()'
psql "postgresql://motionile:<PASSWORD>@<ENDPOINT_ID>-pooler.<REGION_HOST>/motionile?sslmode=require" -c 'select 1'
```

Expected result: the first prints `motionile | motionile | PostgreSQL 17...`; the second prints `1`.

### 6. Upload the strings to SSM

Run from the repository root with AWS credentials for the account. `infra/parameters/` is git-ignored.

```bash
mkdir -p infra/parameters
umask 077
cat > infra/parameters/<ENV>-database.env <<'VALUES'
DATABASE_URL=postgresql://motionile:<PASSWORD>@<ENDPOINT_ID>-pooler.<REGION_HOST>/motionile?sslmode=require&channel_binding=require
DATABASE_DIRECT_URL=postgresql://motionile:<PASSWORD>@<ENDPOINT_ID>.<REGION_HOST>/motionile?sslmode=require&channel_binding=require
VALUES
AWS_REGION=ap-south-1 infra/scripts/put-parameters.sh <ENV> infra/parameters/<ENV>-database.env
```

Expected result:

```text
stored /motionile/<ENV>/DATABASE_URL
stored /motionile/<ENV>/DATABASE_DIRECT_URL
note: REDIS_PASSWORD SECURITY_PAGINATION_SECRET ENCRYPTION_KEYS TURNSTILE_SECRET_KEY were not in this file; render-env.sh fails until they exist in SSM
```

The note lists only the owner parameters that do not exist in this file; it is informational when they were uploaded earlier.

Verify without printing the values:

```bash
aws ssm get-parameters --region ap-south-1 \
  --names /motionile/<ENV>/DATABASE_URL /motionile/<ENV>/DATABASE_DIRECT_URL \
  --query 'Parameters[].[Name,Type,LastModifiedDate]' --output table
```

Both rows show `SecureString`. Delete `infra/parameters/<ENV>-database.env` once your password manager holds the password.

### 7. Restrict access to the instance (optional)

IP Allow needs the Neon Scale plan. Migrations and workers run on the EC2 instance, so its Elastic IP is the only address the application needs.

1. Get the address: `tofu -chdir=infra/aws/envs/<ENV> output -raw elastic_ip`.
2. In the Neon project open **Settings → Networking → IP Allow**, add `<ELASTIC_IP>`, click **Save**.
3. To run `psql` from your own machine later, add your address temporarily and remove it afterwards.

Expected result: connections from any other address are refused with an error saying the IP address is not allowed.

Verify from your machine (not on the list):

```bash
psql "<DIRECT_URL>" -c 'select 1'
```

It is refused. Replacing the instance keeps the Elastic IP, so the list stays valid.

### 8. Verify with the first deployment

The first deployment of `develop` (staging) or `prod` (production) runs `alembic upgrade head` through the `migrate` service against `DATABASE_DIRECT_URL`.

```bash
curl -fsS https://<API_DOMAIN>/health/ready
psql "<DIRECT_URL>" -c 'select extname from pg_extension order by 1'
psql "<DIRECT_URL>" -c 'select version_num from alembic_version'
```

Expected result: `{"status":"ok","checks":{"postgres":"ok","redis":"ok"}}`; extensions `citext`, `pgcrypto`, `plpgsql`, `vector`; and the latest revision ID from `apps/server/migrations/versions`.

## Point-in-time restore

Use instant restore when data was lost or corrupted and the bad change is inside the history window. It overwrites every database on the branch, so read [backups-and-restore.md](backups-and-restore.md) first; it covers stopping workers and Redis consistency.

Option A, restore the branch in place (connection strings stay the same):

1. Select the root branch (`staging` or `production`), open **Postgres database → Backup & Restore**, choose **Restore from history**.
2. Keep **From history** selected, enter the UTC timestamp just before the bad change (use **Time Travel Assist** to query the branch at that time first), click **Next**, review, click **Restore**.

Expected result: the branch holds the data as of the timestamp within seconds; Neon keeps the pre-restore state as a root branch named `<branch>_old_<timestamp>`; open connections drop once and the application reconnects.

Option B, restore into a new branch and repoint the application (the original stays untouched for comparison):

1. Open **Branches → New branch**, parent = the root branch, choose the option to branch from a past point in time, enter the UTC timestamp, name it `restore-<YYYYMMDDHHMM>`, click **Create**.
2. Build the two connection strings for the new branch as in step 5. Roles and passwords are copied from the parent, so only `<ENDPOINT_ID>` changes.
3. Upload them as in step 6 and redeploy as in [secrets-rotation.md](secrets-rotation.md#redeploy-with-the-current-tag).

Expected result: `/health/ready` reports `postgres: ok`, and the restored data is visible. The new branch is a child branch, so plan to restore the root branch from it with Option A ("From another branch") during a quiet period so point-in-time restore is available again.

## Other notes

- Roles are per branch. A branch created from `staging` inherits the `motionile` role and password at creation time; a later password reset on the root does not change existing child branches.
- Neon's connection limit on the pooled endpoint is far higher than on the direct one. Keep `DATABASE_POOL_SIZE` and the worker count small enough that direct connections from `worker-default`, `worker-generation`, `worker-render` and `migrate` stay within the compute's `max_connections`.
