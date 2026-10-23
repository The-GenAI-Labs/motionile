# Secrets rotation

How to rotate every Motionile secret without guessing. Each environment has its own values; rotate staging (`develop`) first, verify, then production (`prod`).

Placeholders:

| Placeholder             | Meaning                                                                                                  |
| ----------------------- | -------------------------------------------------------------------------------------------------------- |
| `<ENV>`                 | `staging` or `production`                                                                                |
| `<GITHUB_OWNER>/<REPO>` | GitHub repository                                                                                        |
| `<API_DOMAIN>`          | `api.<DOMAIN>` or `api.<STAGING_DOMAIN>`                                                                 |
| `<INSTANCE_ID>`         | EC2 instance ID, see [access-and-operations.md](access-and-operations.md#1-open-a-shell-on-the-instance) |
| `<YYYYMM>`              | Year and month of the rotation, used to label new keys                                                   |

## Schedule

| Secret                                                                      | Where it lives                                                                                   | Rotate every | Downtime                                       |
| --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ------------ | ---------------------------------------------- |
| Neon `motionile` role password                                              | SSM `DATABASE_URL`, `DATABASE_DIRECT_URL`                                                        | 180 days     | Minutes, between reset and redeploy            |
| `REDIS_PASSWORD`                                                            | SSM                                                                                              | 365 days     | Seconds, while containers are recreated        |
| JWT signing key (from Phase 4)                                              | SSM, parameter added to `deploy/parameters.csv` in Phase 4                                       | 180 days     | None with the overlap procedure                |
| `ENCRYPTION_KEYS`                                                           | SSM                                                                                              | 365 days     | None                                           |
| CloudFront signing key pair                                                 | Public key in OpenTofu, private key in SSM `CLOUDFRONT_PRIVATE_KEY`                              | 365 days     | None with the overlap procedure                |
| SSH deploy key                                                              | `ci_ssh_public_key`, `/home/deploy/.ssh/authorized_keys`, GitHub secret `DEPLOY_SSH_PRIVATE_KEY` | 180 days     | None                                           |
| `TURNSTILE_SECRET_KEY`                                                      | SSM and Cloudflare                                                                               | 365 days     | None if done within 2 hours                    |
| `SECURITY_PAGINATION_SECRET`                                                | SSM                                                                                              | 365 days     | None; open cursors become invalid              |
| Razorpay API key (`BILLING_RAZORPAY_KEY_ID`, `BILLING_RAZORPAY_KEY_SECRET`) | SSM and the Razorpay dashboard                                                                   | 365 days     | Minutes of failed checkouts at most            |
| Razorpay webhook secret (`BILLING_RAZORPAY_WEBHOOK_SECRET`)                 | SSM and the Razorpay dashboard                                                                   | 365 days     | None with the two-webhook procedure            |
| Speech provider keys (`ELEVENLABS_API_KEY`, `OPENAI_API_KEY`)               | SSM and the provider dashboards                                                                  | 180 days     | None; both providers allow several active keys |

Rotate any secret immediately when it may have leaked, when someone with access leaves, or when a laptop holding a copy is lost. After each rotation, update the password manager entry and record the date in the operations log.

## Common procedures

### Upload owner parameters

`infra/scripts/put-parameters.sh` uploads `NAME=value` lines as SecureString parameters under `/motionile/<ENV>/`. It accepts only names whose source is `owner` in `deploy/parameters.csv`, rejects empty values and values containing a single quote, and never prints values. A file may hold just the parameters you rotate; the closing `note:` line only lists required owner names that were not in this file.

```bash
mkdir -p infra/parameters
umask 077
AWS_REGION=ap-south-1 infra/scripts/put-parameters.sh <ENV> infra/parameters/<ENV>-rotation.env
rm infra/parameters/<ENV>-rotation.env
```

Expected result: one `stored /motionile/<ENV>/<NAME>` line per parameter.

Verify the change date without printing values:

```bash
aws ssm describe-parameters --region ap-south-1 \
  --parameter-filters 'Key=Path,Values=/motionile/<ENV>' \
  --query 'Parameters[].[Name,Type,LastModifiedDate]' --output table
```

### Redeploy with the current tag

Containers read SSM values only when `deploy.sh` renders `/srv/motionile/.env`. `deploy.sh` then runs migrations and `docker compose up --wait`, which recreates every container whose configuration changed.

Option A, through GitHub Actions (also runs the HTTPS health checks and the Playwright smoke project). The image for the branch head already exists, so the build is skipped:

```bash
gh workflow run deploy-staging.yml --repo <GITHUB_OWNER>/<REPO> --ref develop
gh workflow run deploy-production.yml --repo <GITHUB_OWNER>/<REPO> --ref prod
gh run watch --repo <GITHUB_OWNER>/<REPO> "$(gh run list --repo <GITHUB_OWNER>/<REPO> --workflow deploy-staging.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
```

Production waits for a reviewer to approve the `production` environment. This deploys the current head of the branch, which equals the running tag unless a merge is pending.

Option B, on the instance as `deploy` (fastest, no SSH window needed):

```bash
/srv/motionile/bundle/scripts/deploy.sh "$(cat /srv/motionile/state/current-tag)"
curl -fsS https://<API_DOMAIN>/health/ready
```

Expected result: the log ends with `deployed <tag>`, and readiness returns `{"status":"ok","checks":{"postgres":"ok","redis":"ok"}}`. `deploy.sh` also waits for `/health/ready` before it records the tag, so a wrong credential fails the deployment. When the tag is redeployed onto itself there is no older tag to roll back to: if it fails, fix the parameter and run it again.

## 1. Database password (Neon)

Resetting the password invalidates the old one immediately, so new connections fail until the redeploy finishes. Do it in a quiet period.

1. Prepare the rotation file template with the hosts you already use (see [neon-setup.md](neon-setup.md#5-build-the-two-connection-strings)):

   ```text
   DATABASE_URL=postgresql://motionile:<NEW_PASSWORD>@<ENDPOINT_ID>-pooler.<REGION_HOST>/motionile?sslmode=require&channel_binding=require
   DATABASE_DIRECT_URL=postgresql://motionile:<NEW_PASSWORD>@<ENDPOINT_ID>.<REGION_HOST>/motionile?sslmode=require&channel_binding=require
   ```

2. In the Neon Console select project `motionile-<ENV>`, branch `<ENV>`, open **Postgres database → Roles**, open the menu of `motionile`, choose **Reset password**, click **Reset**. Copy the new password.

   Expected result: a modal with the new password. Running requests keep their open connections; new connections fail with `password authentication failed`.

3. Put the password into the file as `infra/parameters/<ENV>-rotation.env` and upload it ([Upload owner parameters](#upload-owner-parameters)).
4. Redeploy with Option B ([Redeploy with the current tag](#redeploy-with-the-current-tag)), because it is faster than waiting for a workflow.
5. Verify:

   ```bash
   curl -fsS https://<API_DOMAIN>/health/ready
   /srv/motionile/bundle/scripts/compose.sh logs --since 5m worker-default worker-render | grep -i -c 'authentication failed'
   ```

   Expected result: readiness `ok` and a count of `0` for log lines after the redeploy. Update the password manager entry.

## 2. Redis password

`REDIS_PASSWORD` appears in the Redis `command` (`--requirepass`), in its `REDISCLI_AUTH` environment and in every application container's `REDIS_URL`. Changing it changes the configuration of `redis`, `api`, `mcp`, `worker-default`, `worker-render` and `migrate`, so Compose recreates all of them together; the data on `/srv/motionile/data/redis` stays. Requests fail for a few seconds while the containers are recreated.

1. Take a fresh backup on the instance (as `ssm-user`): `sudo systemctl start motionile-redis-backup.service`.
2. Create `infra/parameters/<ENV>-rotation.env`:

   ```bash
   umask 077
   printf 'REDIS_PASSWORD=%s\n' "$(openssl rand -hex 32)" > infra/parameters/<ENV>-rotation.env
   ```

   Copy the value into the password manager, then upload ([Upload owner parameters](#upload-owner-parameters)).

3. Optional check of what Compose will do, on the instance as `deploy`:

   ```bash
   /srv/motionile/bundle/scripts/render-env.sh
   /srv/motionile/bundle/scripts/compose.sh --dry-run up --detach
   ```

   Expected result: `Recreate` lines for the `redis`, `api`, `mcp`, `worker-default` and `worker-render` containers. If `redis` is not listed, the parameter did not change; stop and check SSM.

4. Redeploy with Option A or B ([Redeploy with the current tag](#redeploy-with-the-current-tag)).
5. Verify:

   ```bash
   /srv/motionile/bundle/scripts/compose.sh ps --format 'table {{.Service}}\t{{.CreatedAt}}\t{{.Status}}'
   /srv/motionile/bundle/scripts/compose.sh exec redis redis-cli ping
   curl -fsS https://<API_DOMAIN>/health/ready
   ```

   Expected result: every service was created in the last minutes and is running, `PONG`, and readiness `ok`. The next nightly `motionile-redis-backup` run succeeds (it authenticates through the container's `REDISCLI_AUTH`).

## 3. JWT signing key (Phase 4)

Phase 4 introduces EdDSA access tokens (15-minute lifetime, `docs/context.md` section 7), the JWKS endpoint `/v1/auth/jwks.json` and the signing key parameter. That phase adds the parameter to `deploy/parameters.csv` as an `owner` parameter and must update this section with its exact name and format. Refresh tokens are opaque random values whose SHA-256 hash is stored; they are not signed and are unaffected by key rotation.

Each key has a key ID (`kid`) carried in the JWT header. Rotation keeps two keys published so no valid token is ever rejected:

1. Generate the new Ed25519 key with a new `kid`, for example `<YYYYMM>`:

   ```bash
   openssl genpkey -algorithm ed25519 -out jwt-<ENV>-<YYYYMM>.pem
   ```

2. Add it to the signing key parameter next to the current key, still marked as not signing, upload and redeploy. `/v1/auth/jwks.json` now lists both `kid` values.

   Verify: `curl -fsS https://<API_DOMAIN>/v1/auth/jwks.json | jq -r '.keys[].kid'` prints both IDs.

3. Wait at least as long as the JWKS cache lifetime of the verifiers (the Next.js server caches the JWKS), so every verifier knows the new key.
4. Switch signing to the new `kid`, upload and redeploy. New tokens carry the new `kid`; tokens signed with the old key stay valid because the old public key is still published.
5. Wait at least the maximum access-token lifetime (15 minutes) plus clock skew. After that no unexpired token signed by the old key exists.
6. Remove the old key from the parameter, upload and redeploy.

   Verify: the JWKS lists only the new `kid`; logging in and refreshing on the web app works; the API logs show no token verification failures.

Delete the old private key file and update the password manager.

## 4. Encryption key ring (`ENCRYPTION_KEYS`)

`ENCRYPTION_KEYS` is a JSON object mapping a positive integer version to a base64-encoded 32-byte AES-256-GCM key, for example `{"1":"<base64>","2":"<base64>"}`. `motionile.core.security.encryption.KeyRing` encrypts with the highest version and decrypts any version present; every stored value records its `key_version`. Removing a version that rows still use makes those rows fail with `unknown key version`. Never reuse a version number.

1. Build the new value from the current one without printing either:

   ```bash
   umask 077
   current=$(aws ssm get-parameter --region ap-south-1 --with-decryption \
     --name /motionile/<ENV>/ENCRYPTION_KEYS --query Parameter.Value --output text)
   next_version=$(jq -r 'keys | map(tonumber) | max + 1' <<<"$current")
   printf 'ENCRYPTION_KEYS=%s\n' "$(jq -c --arg version "$next_version" --arg key "$(openssl rand -base64 32)" '. + {($version): $key}' <<<"$current")" \
     > infra/parameters/<ENV>-rotation.env
   unset current
   echo "new active version: $next_version"
   ```

   Copy the file content into the password manager, then upload ([Upload owner parameters](#upload-owner-parameters)) and redeploy ([Redeploy with the current tag](#redeploy-with-the-current-tag)).

2. Verify the loaded versions (prints version numbers only):

   ```bash
   /srv/motionile/bundle/scripts/compose.sh exec api python -c 'from motionile.core.config import get_settings; print(sorted(get_settings().encryption_keys))'
   ```

   Expected result: for example `[1, 2]`. New values are encrypted with the highest version.

3. Re-encrypt existing values in the background. `KeyRing.needs_reencryption(value)` tells whether a stored value uses an older version and `KeyRing.reencrypt(value, associated_data=...)` returns it encrypted with the active version. No table stores encrypted values yet and no re-encryption task exists; the first module that stores encrypted values must ship a procrastinate task that walks its rows in small batches with `key_version < <ACTIVE_VERSION>`, re-encrypts them and commits per batch. Run that task after step 2.
4. Check progress on every table that holds encrypted values:

   ```sql
   SELECT key_version, count(*) FROM <TABLE> GROUP BY key_version ORDER BY key_version;
   ```

5. When no row in any table uses an old version, remove it:

   ```bash
   umask 077
   current=$(aws ssm get-parameter --region ap-south-1 --with-decryption \
     --name /motionile/<ENV>/ENCRYPTION_KEYS --query Parameter.Value --output text)
   printf 'ENCRYPTION_KEYS=%s\n' "$(jq -c 'del(.["<OLD_VERSION>"])' <<<"$current")" > infra/parameters/<ENV>-rotation.env
   unset current
   ```

   Upload, redeploy and repeat the verification in step 2.

## 5. CloudFront signing key pair

Signed cookies (`/media/*`) and signed URLs (`/share/*`) are issued with `CLOUDFRONT_PRIVATE_KEY` and `CLOUDFRONT_KEY_PAIR_ID` when `MEDIA_DELIVERY_MODE` is `cloudfront`. CloudFront accepts any public key in the distribution's trusted key group (at most five), so a rotation adds the new key to the group, switches signing, waits until nothing signed with the old key can still be valid, then removes the old key. During the rotation the group holds two keys.

The private key must be a 2048-bit RSA key, the only size CloudFront accepts. The SSM value is the PEM base64-encoded on one line (about 2.3 KB, inside the 4 KB Standard parameter limit), because `render-env.sh` cannot store newlines.

`infra/aws/modules/cdn` trusts every key in the `cloudfront_public_keys` map (label to PEM) and writes the ID of the key labelled by `cloudfront_active_key` to `CLOUDFRONT_KEY_PAIR_ID` and the `cloudfront_public_key_id` output. CloudFront public keys are immutable, so a rotation always adds a new label rather than editing a key.

1. Generate the new pair:

   ```bash
   openssl genrsa -out cloudfront-<ENV>-<YYYYMM>-private.pem 2048
   openssl rsa -pubout -in cloudfront-<ENV>-<YYYYMM>-private.pem -out cloudfront-<ENV>-<YYYYMM>-public.pem
   ```

2. Add the new public key to `cloudfront_public_keys` in `infra/aws/envs/<ENV>/terraform.tfvars`, leave `cloudfront_active_key` unchanged, and apply.

   Expected result: the plan creates one `aws_cloudfront_public_key` and updates the key group in place. Verify: `aws cloudfront get-key-group --id "$(tofu output -raw cloudfront_key_group_id)" --query 'KeyGroup.KeyGroupConfig.Items'` lists two IDs.

3. Switch signing in one step: set `cloudfront_active_key = "<YYYYMM>"` and apply (this updates the `CLOUDFRONT_KEY_PAIR_ID` parameter), upload the new private key, and redeploy right away:

   ```bash
   umask 077
   printf 'CLOUDFRONT_PRIVATE_KEY=%s\n' "$(base64 -w0 cloudfront-<ENV>-<YYYYMM>-private.pem)" > infra/parameters/<ENV>-rotation.env
   ```

   On macOS use `base64 -i cloudfront-<ENV>-<YYYYMM>-private.pem | tr -d '\n'` instead of `base64 -w0 ...`. Then upload ([Upload owner parameters](#upload-owner-parameters)) and redeploy ([Redeploy with the current tag](#redeploy-with-the-current-tag)).

   Verify: after signing in on the web app, `GET /v1/media/session` answers with `CloudFront-Policy`, `CloudFront-Signature` and `CloudFront-Key-Pair-Id` cookies, the `CloudFront-Key-Pair-Id` value equals `tofu output -raw cloudfront_public_key_id`, and a rendition on the web app plays and seeks.

4. Wait for the longest lifetime of anything signed with the old key: `MEDIA_COOKIE_TTL_SECONDS` for cookies (default and maximum 3600 seconds) and `MEDIA_SIGNED_URL_TTL_SECONDS` for signed and presigned URLs (default 900, at most 3600). Use the values in SSM if they are set. A browser holding an old cookie keeps playing until it expires, because the old public key is still in the group; the player refreshes the cookie through `GET /v1/media/session` before expiry and receives one signed with the new key.
5. Remove the old label from `cloudfront_public_keys` and apply. Expected result: the plan removes one public key and updates the key group.
6. Store the new private key in the password manager and delete local copies of both private keys.

If the private key leaked, skip the wait: do steps 1 to 3, then step 5 immediately. Every cookie and URL signed with the old key stops working at once, and users get new cookies on their next page load.

## 6. SSH deploy key

GitHub Actions connects as `deploy` with the private key in the environment secret `DEPLOY_SSH_PRIVATE_KEY`. The public key reached the instance through cloud-init from `ci_ssh_public_key`, but the instance ignores later `user_data` changes (`ignore_changes = [ami, user_data]`), so updating `terraform.tfvars` alone changes nothing on the running instance.

1. Generate the new key on your machine:

   ```bash
   ssh-keygen -t ed25519 -N '' -C motionile-<ENV>-deploy-<YYYYMM> -f motionile-<ENV>-deploy-<YYYYMM>
   cat motionile-<ENV>-deploy-<YYYYMM>.pub
   ```

2. Add the public key on the instance next to the old one. Open a Session Manager shell and as `ssm-user` run (paste the full `.pub` line):

   ```bash
   echo '<NEW_PUBLIC_KEY_LINE>' | sudo -u deploy tee -a /home/deploy/.ssh/authorized_keys >/dev/null
   sudo ssh-keygen -lf /home/deploy/.ssh/authorized_keys
   ```

   Expected result: two fingerprints, the old comment and `motionile-<ENV>-deploy-<YYYYMM>`.

3. Update the GitHub secret:

   ```bash
   gh secret set DEPLOY_SSH_PRIVATE_KEY --repo <GITHUB_OWNER>/<REPO> --env <ENV> < motionile-<ENV>-deploy-<YYYYMM>
   ```

4. Run a deployment through GitHub Actions (Option A in [Redeploy with the current tag](#redeploy-with-the-current-tag)). Expected result: the `Run deploy.sh` step succeeds.
5. Remove the old key. Check which line holds the old key before deleting, then delete by its exact comment:

   ```bash
   sudo grep -n -F ' motionile-<ENV>-deploy' /home/deploy/.ssh/authorized_keys
   sudo sed -i '/ motionile-<ENV>-deploy$/d' /home/deploy/.ssh/authorized_keys
   sudo ssh-keygen -lf /home/deploy/.ssh/authorized_keys
   ```

   Expected result: only the `motionile-<ENV>-deploy-<YYYYMM>` fingerprint is left. Adjust the pattern if the old key had a different comment.

6. Set `ci_ssh_public_key` in `infra/aws/envs/<ENV>/terraform.tfvars` to the new public key so a rebuilt instance gets it. `tofu plan` shows no change for this, which is expected.
7. Run another deployment to prove the remaining key works, then delete the private key file from your machine.

## 7. Turnstile secret key

1. In the Cloudflare dashboard open **Turnstile**, select the widget of this environment's web host, open its settings and choose **Rotate secret key**. Do not choose to invalidate the old secret immediately; Cloudflare keeps it valid for two hours.
2. Write the new secret to `infra/parameters/<ENV>-rotation.env` as `TURNSTILE_SECRET_KEY=<NEW_SECRET>`, upload ([Upload owner parameters](#upload-owner-parameters)) and redeploy ([Redeploy with the current tag](#redeploy-with-the-current-tag)) within those two hours. The site key does not change.
3. Verify: readiness `ok`. From Phase 4, register or log in on the web app (Turnstile protects those routes) and confirm the API logs show no Turnstile verification failures.

## 8. Pagination cursor secret

`SECURITY_PAGINATION_SECRET` signs list cursors. Rotating it only invalidates cursors already handed out: a client that requests the next page with an old cursor gets `422` with code `invalid_cursor` and starts again from the first page. Nothing stored depends on it.

```bash
umask 077
printf 'SECURITY_PAGINATION_SECRET=%s\n' "$(openssl rand -hex 32)" > infra/parameters/<ENV>-rotation.env
```

Upload ([Upload owner parameters](#upload-owner-parameters)) and redeploy ([Redeploy with the current tag](#redeploy-with-the-current-tag)). The server refuses to start with fewer than 32 characters; the command produces 64.

Verify: readiness `ok`, and a paginated list on the web app loads its first and second pages.

## 9. Razorpay key and webhook secret

Three values connect an environment to Razorpay ([razorpay-setup.md](razorpay-setup.md#1-what-goes-where)): the key ID and key secret (a pair, used for API calls and for verifying Checkout signatures) and the webhook secret (verifies every webhook body). Staging uses Razorpay test mode and production uses live mode, so each environment has its own values; rotate staging first. Keep the new values in the password manager under `Motionile / Razorpay / <ENV>` before touching anything.

The pair and the webhook secret are independent: rotate them separately, and never reuse one as the other.

### 9.1 API key and secret

Regenerating a key creates a new key ID and a new secret. Until the new pair is deployed, API calls made with the old pair may start failing, depending on how long Razorpay keeps the old key valid after regeneration; read the dialog's wording and do the steps back to back.

1. Pick a quiet period. While the old key is rejected, `POST /v1/billing/orders` and `POST /v1/billing/subscriptions` return `502 payment_provider_error`. Nothing is lost: no money moves, webhooks are unaffected (they use the webhook secret) and checkouts that were already paid are settled by webhooks and reconciliation.
2. In the Razorpay dashboard, switch to the mode of the environment (Test for staging, Live for production), open **Account & Settings**, then **API keys**, and choose **Regenerate key**. Copy the new key ID and secret; the secret is shown once.
3. Write both to the rotation file and upload ([Upload owner parameters](#upload-owner-parameters)):

   ```bash
   umask 077
   cat > infra/parameters/<ENV>-rotation.env <<'EOF'
   BILLING_RAZORPAY_KEY_ID=<NEW_KEY_ID>
   BILLING_RAZORPAY_KEY_SECRET=<NEW_KEY_SECRET>
   EOF
   ```

4. Redeploy with Option B ([Redeploy with the current tag](#redeploy-with-the-current-tag)).
5. Verify:

   ```bash
   curl -fsS https://<API_DOMAIN>/health/ready
   ```

   Then sign in to the web app, open `/pricing` and start a checkout for the smallest credit pack. Expected result: Razorpay Checkout opens with the new key ID (on staging, complete a test payment and confirm the order becomes `paid`). In CloudWatch Logs Insights confirm no Razorpay authentication failures after the redeploy:

   ```text
   fields @timestamp, method, path, error
   | filter event = "razorpay.request_failed" and error = "RazorpayAuthenticationError"
   | sort @timestamp desc
   | limit 20
   ```

   Expected result: no rows after the redeploy time.

6. A customer who opened Checkout with the old key before the redeploy cannot pass the browser-side signature check, because the signature uses the key secret. Their payment still settles through the webhook or the 15-minute reconciliation, so no action is needed. Mention it in the change ticket if you rotated in business hours.
7. After the Razorpay dialog's overlap period has ended and the query above stays empty, revoke or delete the old key if the dashboard still lists it, and update the password manager.

### 9.2 Webhook secret

Razorpay signs each webhook with the secret of the webhook that sends it, and the API verifies against exactly one secret (`BILLING_RAZORPAY_WEBHOOK_SECRET`). To rotate without losing events, run two webhooks side by side for a short time: events are then delivered by both, whichever webhook the API currently accepts succeeds, and the other is retried by Razorpay or dropped as a duplicate. Event deduplication by event ID and idempotent handlers make the duplicates harmless.

1. Generate the new secret and store it in the password manager:

   ```bash
   openssl rand -hex 32
   ```

2. Add the new secret in Razorpay: in the same mode, open **Account & Settings**, then **Webhooks**, and add a second webhook with the same URL (`https://<API_DOMAIN>/v1/webhooks/razorpay`), the same alert email and exactly the same 16 events as the existing one ([razorpay-setup.md](razorpay-setup.md#22-create-the-test-webhook)), with the new secret. Leave the existing webhook untouched.

   If the dashboard refuses a second webhook on the same URL, use the single-webhook variant at the end of this section.

3. Add the new secret to SSM and deploy:

   ```bash
   umask 077
   printf 'BILLING_RAZORPAY_WEBHOOK_SECRET=%s\n' '<NEW_WEBHOOK_SECRET>' > infra/parameters/<ENV>-rotation.env
   ```

   Upload ([Upload owner parameters](#upload-owner-parameters)) and redeploy with Option B ([Redeploy with the current tag](#redeploy-with-the-current-tag)). From this point the API accepts only the new secret: the new webhook's deliveries succeed and the old webhook's deliveries are answered with `401 invalid_webhook_signature` and are not stored.

4. Verify:
   - In the Razorpay dashboard the new webhook's recent deliveries show HTTP 200 and the old webhook's show 401.
   - In the admin console, **Billing**, then **Webhooks** shows new events arriving with status `processed` (make a test purchase on staging, or wait for traffic on production).
   - Nothing sits `received` or `failed` for more than a few minutes.

5. Remove the old webhook in the Razorpay dashboard. Keep the new one active and confirm it still lists all 16 events.
6. Update the password manager and delete the rotation file (`rm infra/parameters/<ENV>-rotation.env`).

If anything goes wrong between steps 3 and 5, put the old secret back in SSM, upload and redeploy: the old webhook then succeeds again and the new one fails until you correct it. Events rejected during any window are redelivered by Razorpay, and the periodic reconciliation repairs gaps after that ([billing.md](../billing.md#dropped-webhooks)).

Single-webhook variant (only if a second webhook cannot be created). There is a window of a few minutes in which every delivery fails, so do it when traffic is lowest:

1. Upload the new secret to SSM first, then edit the existing webhook's secret in the Razorpay dashboard, then redeploy immediately. Deliveries between the edit and the end of the redeploy get `401` and are redelivered by Razorpay.
2. Verify as in step 4 and keep an eye on **Reconciliation** the next morning; the settlement check will list any payment whose events were lost.

## 10. Speech provider API keys

`ELEVENLABS_API_KEY` and `OPENAI_API_KEY` pay for narration, alignment and consent transcription. Each environment has its own key so that staging usage and limits never touch production. Both are SecureString parameters (`owner`). The server refuses to start in a deployed environment without the key of every provider selected by `AUDIO_TTS_PROVIDER` and `AUDIO_TRANSCRIBER`; the other key may be absent.

Keep the new values in the password manager under `Motionile / Speech providers / <ENV>` before touching anything. Both providers accept several active keys, so rotation has no gap.

1. Create the new key at the provider. In the ElevenLabs dashboard open **Developers**, then **API Keys**, create a key named `motionile-<ENV>-<YYYYMM>` and, when the dashboard offers it, restrict it to text-to-speech, speech-to-text and voice management with a monthly character quota. In the OpenAI dashboard open **API keys**, create a key named `motionile-<ENV>-<YYYYMM>` in the project of this environment and restrict its permissions to the audio endpoints when the project allows it.
2. Write only the rotated name to the rotation file and upload ([Upload owner parameters](#upload-owner-parameters)):

   ```bash
   umask 077
   printf 'ELEVENLABS_API_KEY=%s\n' '<NEW_ELEVENLABS_KEY>' > infra/parameters/<ENV>-rotation.env
   ```

3. Redeploy with Option B ([Redeploy with the current tag](#redeploy-with-the-current-tag)). Compose recreates every service whose environment changed, which includes `api`, `worker-default` and `worker-render`.
4. Verify with a synthesized render: sign in to the admin console as a user with `render.testbed`, open **Render test bed**, render a golden composition with a built-in voice and text that is not cached yet, and confirm the render finishes. A cached narration does not call the provider, so use fresh text. In CloudWatch Logs Insights confirm no authentication failures after the redeploy time:

   ```text
   fields @timestamp, event, provider, error
   | filter event like /provider/ and error like /401|403|unauthorized/
   | sort @timestamp desc
   | limit 20
   ```

   Expected result: no rows after the redeploy.

5. Revoke the old key at the provider and update the password manager.
6. Delete the rotation file: `rm infra/parameters/<ENV>-rotation.env`.

Rotate immediately if a key appears in a log, a screenshot or a repository. After the provider has revoked the key, review its usage page for calls you did not make and compare with `usage_records` in the admin console.
