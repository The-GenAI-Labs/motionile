# Bootstrap AWS

This runbook takes an empty AWS account to a running Motionile staging environment and then a production environment. Follow the steps in order. Every step says what you should see and how to check it before you move on.

The branch `develop` deploys to the `staging` environment and the branch `prod` deploys to the `production` environment. Everything runs in `ap-south-1`, except the CloudFront certificate and the WAF web ACL, which live in `us-east-1`.

When you finish this runbook, continue with [github-setup.md](github-setup.md), then [deploy-and-rollback.md](deploy-and-rollback.md).

## What this creates

| Stack                                          | Resources                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `infra/aws/bootstrap`                          | One S3 bucket for OpenTofu state (versioned, encrypted, TLS only, public access blocked). Its own state stays on your machine.                                                                                                                                                                                                                                                                                                                                                      |
| `infra/aws/envs/staging` and `envs/production` | A VPC with public and private subnets (no NAT gateway); one EC2 instance with an Elastic IP, an encrypted root volume and a separate encrypted data volume with daily snapshots; ECR repositories `<env>/motionile-api` and `<env>/motionile-worker`; media and backup buckets; CloudFront and WAF for `cdn.<domain>`; an SES domain identity; SSM parameters under `/motionile/<env>`; a CloudWatch log group, alarms and an encrypted SNS alert topic; a GitHub OIDC deploy role. |

Each environment uses three host names under its domain: `api.<domain>` and `mcp.<domain>` (served by Caddy on the instance) and `cdn.<domain>` (CloudFront). The web app itself runs on Vercel at the domain apex and is not created here.

## Approximate monthly cost drivers

Exact prices change; estimate them with the [AWS Pricing Calculator](https://calculator.aws/) for `ap-south-1`. The main drivers are:

- **EC2:** one on-demand instance running all month, `c7i.xlarge` for staging and `c7i.2xlarge` for production, with detailed monitoring on. This is the largest cost.
- **EBS:** gp3 root volume (50 GB) and data volume (100 GB staging, 200 GB production), plus up to 7 daily snapshots of the data volume.
- **Public IPv4:** the Elastic IP is billed hourly.
- **CloudFront:** requests and data transfer out from `cdn.<domain>`.
- **WAF:** one web ACL, its rules and per-request charges.
- **KMS:** one customer managed key per environment (the alert topic key).
- **CloudWatch:** log ingestion and storage (container logs, host logs, VPC flow logs, WAF logs), custom agent metrics and alarms.
- **Smaller items:** S3 storage and requests, ECR storage, SES messages, data transfer out of the instance.

RDS is off by default (`enable_rds = false`); Postgres runs on Neon and is billed by Neon.

## Conventions

- Run every command from the repository root on macOS or Linux, unless a step says you are inside a Session Manager shell on the instance.
- Replace every `<PLACEHOLDER>` with your value. Commands that use `$(...)` read values from OpenTofu outputs for you.
- Keep private keys and generated secrets in `~/motionile-secrets`, outside the repository, and copy each one into your password manager. Never commit them. The deploy key files have no extension, so `.gitignore` would not catch them inside the repository.
- The provider lock files `.terraform.lock.hcl` are already committed with hashes for Linux, macOS and Windows. Run `tofu init` with `-lockfile=readonly` so they never change.

## Part A: prerequisites

### 1. Prepare the AWS account and an admin identity with MFA

1. Sign in to the new AWS account as root once. Turn on MFA for the root user (IAM > Security credentials > Assign MFA device). Never create access keys for the root user.
2. Create an admin identity for daily work. Use IAM Identity Center:
   1. Open IAM Identity Center and choose **Enable**.
   2. Under **Users**, create a user for yourself and finish the email invitation. Register an MFA device when you first sign in (Identity Center requires MFA by default; confirm under **Settings > Authentication**).
   3. Under **Permission sets**, create a predefined permission set `AdministratorAccess`.
   4. Under **AWS accounts**, select the account, choose **Assign users or groups**, pick your user and the `AdministratorAccess` permission set.
   5. Copy the **AWS access portal URL** from the Identity Center dashboard.

   If you cannot use Identity Center, create an IAM user with the `AdministratorAccess` policy, assign it an MFA device, and use a profile that requires MFA. Do not use long-lived access keys without MFA.

Expected result: you can sign in to the access portal URL with your password and MFA, and you see the account with the `AdministratorAccess` role.

### 2. Install the tools

| Tool                   | Version                    | Check                    | Expected output                                            |
| ---------------------- | -------------------------- | ------------------------ | ---------------------------------------------------------- |
| OpenTofu               | exactly 1.13.x, use 1.13.1 | `tofu version`           | `OpenTofu v1.13.1`                                         |
| AWS CLI                | v2                         | `aws --version`          | `aws-cli/2.`...                                            |
| Session Manager plugin | latest                     | `session-manager-plugin` | `The Session Manager plugin was installed successfully...` |
| OpenSSL (or LibreSSL)  | any current                | `openssl version`        | a version string                                           |
| OpenSSH `ssh-keygen`   | ships with macOS and Linux | `command -v ssh-keygen`  | a path such as `/usr/bin/ssh-keygen`                       |
| jq                     | 1.6 or later               | `jq --version`           | `jq-1.`...                                                 |
| Bash                   | 4 or later                 | `bash --version`         | `GNU bash, version 4.`... or `5.`...                       |
| dig                    | any                        | `dig -v`                 | a version string                                           |

Install OpenTofu 1.13.1 with the official installer (the versions file requires `~> 1.13.1`, so 1.14 does not work):

```bash
curl --proto '=https' --tlsv1.2 -fsSL https://get.opentofu.org/install-opentofu.sh -o install-opentofu.sh
chmod +x install-opentofu.sh
./install-opentofu.sh --install-method standalone --opentofu-version 1.13.1
rm -f install-opentofu.sh
tofu version
```

If the installer does not work on your machine, download the `tofu_1.13.1_<os>_<arch>.zip` asset from the [OpenTofu v1.13.1 release](https://github.com/opentofu/opentofu/releases/tag/v1.13.1) and put `tofu` on your `PATH`.

Install the AWS CLI v2 and the Session Manager plugin by following the AWS guides: [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) and [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html). On macOS with Homebrew:

```bash
brew install awscli jq bash
brew install --cask session-manager-plugin
```

On Debian or Ubuntu:

```bash
sudo apt-get update && sudo apt-get install -y jq openssl dnsutils
```

macOS ships Bash 3.2, which cannot run `infra/scripts/put-parameters.sh` (it uses `mapfile` and associative arrays). After `brew install bash`, open a new terminal and check that `bash --version` reports 5.x.

Expected result: every check in the table prints the expected output.

### 3. Decide the domains and addresses

Write these down; later steps use them as placeholders.

| Placeholder                          | Meaning                                                                         | Example                                                         |
| ------------------------------------ | ------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `<STAGING_DOMAIN>`                   | Registrable domain for staging, separate from production so cookies never cross | `motionile-staging.com`                                         |
| `<PRODUCTION_DOMAIN>`                | Registrable domain for production                                               | `motionile.com`                                                 |
| `<ALERT_EMAIL>`                      | Mailbox that receives CloudWatch alarms                                         | `alerts@motionile.com`                                          |
| `<ACME_EMAIL>`                       | Address Caddy registers with Let's Encrypt                                      | `ops@motionile.com`                                             |
| `<GITHUB_OWNER>/<GITHUB_REPOSITORY>` | The repository exactly as GitHub spells it (the OIDC trust is case-sensitive)   | output of `gh repo view --json nameWithOwner -q .nameWithOwner` |

You need access to the DNS zone of both domains at your DNS provider. The web app runs on Vercel at `https://<STAGING_DOMAIN>` and `https://<PRODUCTION_DOMAIN>`; those apex records are configured in Vercel, not here.

### 4. Configure an AWS CLI profile and sign in

With IAM Identity Center:

```bash
aws configure sso
```

Answer the prompts:

- **SSO session name:** `motionile`
- **SSO start URL:** the access portal URL from step 1
- **SSO region:** the region where you enabled Identity Center
- **SSO registration scopes:** accept the default `sso:account:access`
- Pick the account and the `AdministratorAccess` role.
- **Default client Region:** `ap-south-1`
- **CLI default output format:** `json`
- **Profile name:** `<AWS_PROFILE>`, for example `motionile-admin`

Then sign in and select the profile for this shell:

```bash
aws sso login --profile <AWS_PROFILE>
export AWS_PROFILE=<AWS_PROFILE>
aws sts get-caller-identity
```

Expected result: JSON with `"Account": "<ACCOUNT_ID>"` and an `Arn` that contains `AWSReservedSSO_AdministratorAccess`. Run `export AWS_PROFILE=<AWS_PROFILE>` in every new terminal you use for this runbook, and `aws sso login` again when the session expires.

### 5. Create the local secrets directory

```bash
mkdir -p ~/motionile-secrets
chmod 700 ~/motionile-secrets
ls -ld ~/motionile-secrets
```

Expected result: `drwx------` for `~/motionile-secrets`.

## Part B: state bucket

### 6. Apply the bootstrap stack

```bash
cp infra/aws/bootstrap/terraform.tfvars.example infra/aws/bootstrap/terraform.tfvars
tofu -chdir=infra/aws/bootstrap init -lockfile=readonly
tofu -chdir=infra/aws/bootstrap plan -out=bootstrap.tfplan
```

Expected result: `OpenTofu has been successfully initialized!`, then `Plan: 7 to add, 0 to change, 0 to destroy.` With `state_bucket_name = ""`, the bucket is named `motionile-tofu-state-<ACCOUNT_ID>`.

```bash
tofu -chdir=infra/aws/bootstrap apply bootstrap.tfplan
tofu -chdir=infra/aws/bootstrap output -raw state_bucket_name
```

Expected result: `Apply complete! Resources: 7 added, 0 changed, 0 destroyed.` and the bucket name. This value is `<STATE_BUCKET_NAME>` from now on.

Verify:

```bash
aws s3api get-bucket-versioning --bucket <STATE_BUCKET_NAME>
```

Expected result: `"Status": "Enabled"`.

### 7. Back up the bootstrap state

The bootstrap state lives only in `infra/aws/bootstrap/terraform.tfstate` on your machine (git ignores it). Copy it into the state bucket and into your password manager:

```bash
aws s3 cp infra/aws/bootstrap/terraform.tfstate s3://<STATE_BUCKET_NAME>/bootstrap/terraform.tfstate
aws s3 ls s3://<STATE_BUCKET_NAME>/bootstrap/
```

Expected result: `upload: ...` and a listing that shows `terraform.tfstate`. Repeat the copy after every future apply of `infra/aws/bootstrap`. To restore it on another machine:

```bash
aws s3 cp s3://<STATE_BUCKET_NAME>/bootstrap/terraform.tfstate infra/aws/bootstrap/terraform.tfstate
```

## Part C: staging

### 8. Generate the CI deploy SSH key

GitHub Actions uses this key to reach the instance as the `deploy` user.

```bash
ssh-keygen -t ed25519 -N '' -C motionile-staging-deploy -f ~/motionile-secrets/motionile-staging-deploy
ls ~/motionile-secrets/motionile-staging-deploy ~/motionile-secrets/motionile-staging-deploy.pub
```

Expected result: two files. `motionile-staging-deploy.pub` starts with `ssh-ed25519`. The private key goes into GitHub in [github-setup.md](github-setup.md); store a copy in your password manager.

### 9. Generate the CloudFront key pair

CloudFront verifies signed cookies and URLs with the public key; the API signs them with the private key.

```bash
openssl genrsa -out ~/motionile-secrets/cloudfront-staging-private.pem 2048
openssl rsa -pubout -in ~/motionile-secrets/cloudfront-staging-private.pem -out ~/motionile-secrets/cloudfront-staging-public.pem
head -n 1 ~/motionile-secrets/cloudfront-staging-public.pem
```

Expected result: `-----BEGIN PUBLIC KEY-----`. Store the private key in your password manager.

CloudFront accepts only 2048-bit RSA keys, so do not change the size. Step 19 stores the private key base64-encoded on one line, which fits in a Standard SSM parameter; the API reads it as `CLOUDFRONT_PRIVATE_KEY`. Rotation is in [secrets-rotation.md](secrets-rotation.md#5-cloudfront-signing-key-pair).

### 10. Create `terraform.tfvars`

This writes `infra/aws/envs/staging/terraform.tfvars` from the example with your values and the two public keys. It contains no secrets, and git ignores it.

```bash
cat > infra/aws/envs/staging/terraform.tfvars <<EOF
domain                  = "<STAGING_DOMAIN>"
web_origin              = "https://<STAGING_DOMAIN>"
additional_cors_origins = []
instance_type           = "c7i.xlarge"
alert_email             = "<ALERT_EMAIL>"
acme_email              = "<ACME_EMAIL>"
github_repository       = "<GITHUB_OWNER>/<GITHUB_REPOSITORY>"
ci_ssh_public_key       = "$(cat ~/motionile-secrets/motionile-staging-deploy.pub)"
enable_cdn              = false
manage_dns              = false
route53_zone_id         = null
enable_rds              = false
create_oidc_provider    = true

cloudfront_active_key = "initial"
cloudfront_public_keys = {
  initial = <<-EOT
$(cat ~/motionile-secrets/cloudfront-staging-public.pem)
EOT
}
EOF
cat infra/aws/envs/staging/terraform.tfvars
```

Expected result: the file shows your domain, a `ssh-ed25519 ...` line and the PEM between `<<-EOT` and `EOT` inside `cloudfront_public_keys`. `web_origin` must be a lowercase `https://` origin with no path and no trailing slash. Add `"https://www.<STAGING_DOMAIN>"` to `additional_cors_origins` only if the web app is also served on `www`.

If you host the zone in Route 53 in this account, set `manage_dns = true` and `route53_zone_id = "<ZONE_ID>"`; OpenTofu then creates every record in steps 13 and 17 for you.

### 11. Initialise the staging stack

```bash
tofu -chdir=infra/aws/envs/staging init -lockfile=readonly -backend-config=bucket=<STATE_BUCKET_NAME>
```

Expected result: `Successfully configured the backend "s3"!` and `OpenTofu has been successfully initialized!`. State is stored at `s3://<STATE_BUCKET_NAME>/staging/terraform.tfstate` with S3 lockfile locking.

### 12. First apply with the CDN disabled

```bash
tofu -chdir=infra/aws/envs/staging plan -out=staging.tfplan
tofu -chdir=infra/aws/envs/staging apply staging.tfplan
```

Expected result: `Apply complete! Resources: <n> added, 0 changed, 0 destroyed.` This creates the network, the instance, ECR, both buckets, the CDN certificate (not yet validated), the CloudFront public key and key group, the SES identity, observability, the OIDC provider and deploy role, and the infrastructure SSM parameters. It does not create the CloudFront distribution or the WAF yet.

Verify:

```bash
tofu -chdir=infra/aws/envs/staging output elastic_ip
tofu -chdir=infra/aws/envs/staging output instance_id
tofu -chdir=infra/aws/envs/staging output -json ecr_repository_urls
```

Expected result: an IP address, an `i-...` ID, and two URLs ending in `/staging/motionile-api` and `/staging/motionile-worker`.

### 13. Create the DNS records

Print every record the environment needs:

```bash
tofu -chdir=infra/aws/envs/staging output -json dns_records \
  | jq -r 'to_entries[] | [.key, .value.type, .value.name, .value.value] | @tsv'
```

Each line is `label  type  name  value`. Create each one at your DNS provider:

| Label                        | Type  | Name                                  | Value                                       |
| ---------------------------- | ----- | ------------------------------------- | ------------------------------------------- |
| `api`                        | A     | `api.<STAGING_DOMAIN>`                | the Elastic IP                              |
| `mcp`                        | A     | `mcp.<STAGING_DOMAIN>`                | the Elastic IP                              |
| `cdn-certificate-validation` | CNAME | `_<hash>.cdn.<STAGING_DOMAIN>.`       | `_<hash>.<...>.acm-validations.aws.`        |
| `ses-dkim-1`, `-2`, `-3`     | CNAME | `<token>._domainkey.<STAGING_DOMAIN>` | `<token>.dkim.amazonses.com`                |
| `ses-mail-from-mx`           | MX    | `mail.<STAGING_DOMAIN>`               | `10 feedback-smtp.ap-south-1.amazonses.com` |
| `ses-mail-from-spf`          | TXT   | `mail.<STAGING_DOMAIN>`               | `v=spf1 include:amazonses.com -all`         |
| `dmarc`                      | TXT   | `_dmarc.<STAGING_DOMAIN>`             | `v=DMARC1; p=quarantine; adkim=s; aspf=s`   |

Rules for entering them:

- Many providers want the name without the zone suffix: enter `api` rather than `api.<STAGING_DOMAIN>`, and drop a trailing dot. Copy the ACM validation name and value exactly, apart from that.
- For the MX record, enter priority `10` and host `feedback-smtp.ap-south-1.amazonses.com` if your provider has a separate priority field.
- If the provider can proxy traffic (for example Cloudflare), set every record to DNS only. Caddy needs direct traffic on ports 80 and 443 to obtain certificates.
- If the domain already has a DMARC record, keep a single `_dmarc` TXT record.
- The `cdn` CNAME is not in this list yet; you add it in step 17.

Verify after a few minutes:

```bash
dig +short A api.<STAGING_DOMAIN>
dig +short A mcp.<STAGING_DOMAIN>
dig +short TXT _dmarc.<STAGING_DOMAIN>
dig +short MX mail.<STAGING_DOMAIN>
tofu -chdir=infra/aws/envs/staging output -json dns_records \
  | jq -r '.["cdn-certificate-validation"].name' \
  | xargs dig +short CNAME
```

Expected result: the Elastic IP twice, the DMARC text, `10 feedback-smtp.ap-south-1.amazonses.com.` and the ACM validation target.

### 14. Confirm the alert email subscription

AWS sends a message titled "AWS Notification - Subscription Confirmation" to `<ALERT_EMAIL>`. Open it and choose **Confirm subscription**.

Verify:

```bash
aws sns list-subscriptions-by-topic --region ap-south-1 \
  --topic-arn "$(tofu -chdir=infra/aws/envs/staging output -raw alert_topic_arn)" \
  --query 'Subscriptions[].[Endpoint,SubscriptionArn]' --output text
```

Expected result: your address followed by a subscription ARN. `PendingConfirmation` means you have not confirmed yet.

### 15. Wait for the CDN certificate

```bash
certificate_arn=$(aws acm list-certificates --region us-east-1 \
  --certificate-statuses PENDING_VALIDATION ISSUED \
  --query "CertificateSummaryList[?DomainName=='cdn.<STAGING_DOMAIN>'].CertificateArn" --output text)
echo "$certificate_arn"
aws acm wait certificate-validated --region us-east-1 --certificate-arn "$certificate_arn"
aws acm describe-certificate --region us-east-1 --certificate-arn "$certificate_arn" --query Certificate.Status --output text
```

Expected result: an `arn:aws:acm:us-east-1:...` ARN, then the wait returns and the status is `ISSUED`. Validation usually takes a few minutes after the CNAME resolves; the wait gives up after 40 minutes. If it gives up, check the validation record from step 13 and run the wait again.

### 16. Second apply with the CDN enabled

```bash
sed -i.bak 's/^enable_cdn *= *false/enable_cdn              = true/' infra/aws/envs/staging/terraform.tfvars
rm infra/aws/envs/staging/terraform.tfvars.bak
grep '^enable_cdn' infra/aws/envs/staging/terraform.tfvars
tofu -chdir=infra/aws/envs/staging plan -out=staging.tfplan
tofu -chdir=infra/aws/envs/staging apply staging.tfplan
```

Expected result: `enable_cdn              = true`, then an apply that adds the CloudFront distribution, the WAF web ACL and its log group in `us-east-1`, the CloudFront log delivery, the `CLOUDFRONT_KEY_PAIR_ID` parameter and the media bucket read grant. Creating the distribution takes several minutes.

### 17. Add the `cdn` CNAME

```bash
tofu -chdir=infra/aws/envs/staging output -json dns_records | jq -r '.cdn | [.type, .name, .value] | @tsv'
```

Expected result: `CNAME  cdn.<STAGING_DOMAIN>  d<...>.cloudfront.net`. Create that record at your DNS provider (DNS only, not proxied).

Verify once it resolves:

```bash
dig +short CNAME cdn.<STAGING_DOMAIN>
curl -sI https://cdn.<STAGING_DOMAIN>/media/anything | head -n 1
curl -sI https://cdn.<STAGING_DOMAIN>/anything-else | head -n 1
```

Expected result: the `cloudfront.net` name, then `HTTP/2 403` twice. Media needs a signed cookie, and every path outside `/media/*` and `/share/*` is refused.

### 18. Check the SES identity

```bash
aws sesv2 get-email-identity --region ap-south-1 --email-identity <STAGING_DOMAIN> \
  --query '{verified: VerifiedForSendingStatus, dkim: DkimAttributes.Status, mailFrom: MailFromAttributes.MailFromDomainStatus}'
```

Expected result: `"verified": true`, `"dkim": "SUCCESS"` and `"mailFrom": "SUCCESS"`. `PENDING` means the DKIM or MAIL FROM records from step 13 have not propagated yet; check again later. `FAILED` means a record is wrong.

New accounts start in the SES sandbox and can only send to verified addresses. Request production access once, for the account and region, when you are ready to send to real users:

```bash
aws sesv2 put-account-details --region ap-south-1 \
  --production-access-enabled \
  --mail-type TRANSACTIONAL \
  --website-url https://<PRODUCTION_DOMAIN> \
  --use-case-description "<HOW_MOTIONILE_SENDS_EMAIL>" \
  --additional-contact-email-addresses <ALERT_EMAIL> \
  --contact-language EN
aws sesv2 get-account --region ap-south-1 --query '{productionAccess: ProductionAccessEnabled, review: Details.ReviewDetails.Status}'
```

Expected result: `review` is `PENDING` until AWS answers by email, then `productionAccess` is `true`.

### 19. Store the secrets in SSM

OpenTofu already wrote the non-secret parameters. You upload the secret ones (`source` is `owner` in `deploy/parameters.csv`) as SecureString parameters with `infra/scripts/put-parameters.sh`. Each value must be one line and must not contain a single quote.

Gather the external values first. [neon-setup.md](neon-setup.md) explains how to create the Neon project, databases and both connection strings.

- **`DATABASE_URL`**: the Neon **pooled** connection string of the staging database (the host contains `-pooler`), pasted exactly as Neon shows it, including `?sslmode=require` and any `channel_binding=require`. The server translates these for asyncpg.
- **`DATABASE_DIRECT_URL`**: the Neon **direct** connection string (no `-pooler`), also pasted as shown. Migrations and the job queue use it through psycopg.
- **`TURNSTILE_SECRET_KEY`**: in the Cloudflare dashboard, open Turnstile, add a widget for the host name `<STAGING_DOMAIN>`, and copy its secret key.
- **`ELEVENLABS_API_KEY`**: in the ElevenLabs dashboard, create an API key named `motionile-staging` for narration, alignment and voice cloning. Add `OPENAI_API_KEY` the same way only if you select OpenAI with `AUDIO_TTS_PROVIDER` or `AUDIO_TRANSCRIBER`.

Create the values file. Generated values come from OpenSSL; the external values are written with single quotes so the shell never expands them:

```bash
mkdir -p infra/parameters
(
  umask 077
  {
    printf 'DATABASE_URL=%s\n' '<NEON_STAGING_POOLED_URL_WITH_SSL_REQUIRE>'
    printf 'DATABASE_DIRECT_URL=%s\n' '<NEON_STAGING_DIRECT_URL>'
    printf 'TURNSTILE_SECRET_KEY=%s\n' '<TURNSTILE_STAGING_SECRET_KEY>'
    printf 'ELEVENLABS_API_KEY=%s\n' '<ELEVENLABS_STAGING_API_KEY>'
    printf 'REDIS_PASSWORD=%s\n' "$(openssl rand -hex 32)"
    printf 'SECURITY_PAGINATION_SECRET=%s\n' "$(openssl rand -hex 32)"
    printf 'ENCRYPTION_KEYS={"1":"%s"}\n' "$(openssl rand -base64 32)"
  } > infra/parameters/staging.env
)
```

Add the CloudFront private key, base64-encoded on one line. On Linux:

```bash
printf 'CLOUDFRONT_PRIVATE_KEY=%s\n' "$(base64 -w0 ~/motionile-secrets/cloudfront-staging-private.pem)" >> infra/parameters/staging.env
```

On macOS:

```bash
printf 'CLOUDFRONT_PRIVATE_KEY=%s\n' "$(base64 -i ~/motionile-secrets/cloudfront-staging-private.pem | tr -d '\n')" >> infra/parameters/staging.env
```

Check the file without printing values:

```bash
ls -l infra/parameters/staging.env
cut -d= -f1 infra/parameters/staging.env
git status --short infra/parameters
```

Expected result: mode `-rw-------`, the eight names `DATABASE_URL`, `DATABASE_DIRECT_URL`, `TURNSTILE_SECRET_KEY`, `ELEVENLABS_API_KEY`, `REDIS_PASSWORD`, `SECURITY_PAGINATION_SECRET`, `ENCRYPTION_KEYS`, `CLOUDFRONT_PRIVATE_KEY`, and no output from `git status` (the directory is ignored).

Upload:

```bash
AWS_REGION=ap-south-1 infra/scripts/put-parameters.sh staging infra/parameters/staging.env
```

Expected result: one `stored /motionile/staging/<NAME>` line per value and no `note:` line. The script refuses names that are not owner parameters and never prints values.

Verify:

```bash
aws ssm get-parameters-by-path --region ap-south-1 --path /motionile/staging \
  --query 'Parameters[].[Type,Name]' --output text | sort
```

Expected result: 8 `SecureString` lines (the names above) and the `String` lines written by OpenTofu, including `MEDIA_DELIVERY_MODE` (`presigned` until the CDN is enabled, then `cloudfront`) and, once the CDN is enabled, `CLOUDFRONT_KEY_PAIR_ID`.

Copy the contents of `infra/parameters/staging.env` into your password manager, then delete the local file. `ENCRYPTION_KEYS` must never be lost: without it, stored third-party credentials cannot be decrypted.

```bash
rm infra/parameters/staging.env
```

To change one value later, put only that line in a new file and run the script again; it overwrites the parameter. The next deployment picks it up.

### 20. Confirm cloud-init finished and Session Manager works

```bash
instance_id=$(tofu -chdir=infra/aws/envs/staging output -raw instance_id)
aws ssm describe-instance-information --region ap-south-1 \
  --filters "Key=InstanceIds,Values=$instance_id" \
  --query 'InstanceInformationList[].PingStatus' --output text
```

Expected result: `Online`. If the output is empty, wait a few minutes; the SSM agent registers after boot.

Open a shell on the instance:

```bash
aws ssm start-session --region ap-south-1 --target "$instance_id"
```

Inside the Session Manager shell, run:

```bash
cloud-init status --wait
sudo tail -n 30 /var/log/cloud-init-output.log
findmnt /srv/motionile/data
ls -ld /srv/motionile/bundle /srv/motionile/state /srv/motionile/logs
cat /etc/motionile/environment
systemctl list-timers 'motionile-*'
sudo -iu deploy docker compose version
sudo -iu deploy aws --version
```

Expected result:

- `status: done` (`status: error` means read the full `/var/log/cloud-init-output.log`).
- `/srv/motionile/data` mounted from an `nvme` device with `ext4`.
- The three directories owned by `deploy`.
- `MOTIONILE_ENVIRONMENT=staging` and `AWS_REGION=ap-south-1`.
- `motionile-redis-backup.timer` and `motionile-docker-prune.timer` listed.
- A Docker Compose version and an AWS CLI version for the `deploy` user.

Stay in the session for the next step.

### 21. Read the SSH host key for GitHub

The deploy workflow pins the instance host key. In the Session Manager shell, print the `known_hosts` line, replacing `<ELASTIC_IP>` with the output of `tofu -chdir=infra/aws/envs/staging output -raw elastic_ip`:

```bash
printf '%s %s\n' '<ELASTIC_IP>' "$(cut -d ' ' -f 1,2 /etc/ssh/ssh_host_ed25519_key.pub)"
exit
```

Expected result: one line such as `203.0.113.10 ssh-ed25519 AAAAC3Nza...`. This is the value of the `DEPLOY_SSH_KNOWN_HOSTS` variable in [github-setup.md](github-setup.md). Save it with your notes.

Cross-check it from your machine with the console output, which cloud-init writes on first boot:

```bash
aws ec2 get-console-output --region ap-south-1 --instance-id "$instance_id" --latest --output text \
  | sed -n '/BEGIN SSH HOST KEY KEYS/,/END SSH HOST KEY KEYS/p' | grep ssh-ed25519
```

Expected result: the same `ssh-ed25519 AAAA...` key. Port 22 stays closed; it opens only for the GitHub runner during a deployment.

If you ever replace the instance, first turn off its termination protection with `aws ec2 modify-instance-attribute --region ap-south-1 --instance-id <INSTANCE_ID> --no-disable-api-termination`, then run `tofu apply -replace=module.environment.module.compute.aws_instance.this`. The Elastic IP and the data volume stay, but the host key changes: repeat steps 20 and 21 and update `DEPLOY_SSH_KNOWN_HOSTS`. OpenTofu turns termination protection back on for the new instance.

Staging is ready. Continue with [github-setup.md](github-setup.md) to deploy it, or build production first with Part D.

## Part D: production

Production lives in the same AWS account and reuses the GitHub OIDC provider created by staging. Its deploy role may read the staging ECR repositories so it can promote images instead of rebuilding them. Finish Part C first; this part reads staging outputs.

### 22. Generate the production keys

```bash
ssh-keygen -t ed25519 -N '' -C motionile-production-deploy -f ~/motionile-secrets/motionile-production-deploy
openssl genrsa -out ~/motionile-secrets/cloudfront-production-private.pem 2048
openssl rsa -pubout -in ~/motionile-secrets/cloudfront-production-private.pem -out ~/motionile-secrets/cloudfront-production-public.pem
ls ~/motionile-secrets
```

Expected result: `motionile-production-deploy`, `motionile-production-deploy.pub`, `cloudfront-production-private.pem` and `cloudfront-production-public.pem` next to the staging files. Never reuse staging keys in production. Store the private keys in your password manager.

### 23. Create the production `terraform.tfvars`

This reads `oidc_provider_arn` and both ECR repository ARNs from the staging outputs.

```bash
cat > infra/aws/envs/production/terraform.tfvars <<EOF
domain                  = "<PRODUCTION_DOMAIN>"
web_origin              = "https://<PRODUCTION_DOMAIN>"
additional_cors_origins = []
instance_type           = "c7i.2xlarge"
alert_email             = "<ALERT_EMAIL>"
acme_email              = "<ACME_EMAIL>"
github_repository       = "<GITHUB_OWNER>/<GITHUB_REPOSITORY>"
ci_ssh_public_key       = "$(cat ~/motionile-secrets/motionile-production-deploy.pub)"
enable_cdn              = false
manage_dns              = false
route53_zone_id         = null
enable_rds              = false
create_oidc_provider    = false
oidc_provider_arn       = "$(tofu -chdir=infra/aws/envs/staging output -raw oidc_provider_arn)"
promotion_source_repository_arns = $(tofu -chdir=infra/aws/envs/staging output -json ecr_repository_arns | jq -c '[.["motionile-api"], .["motionile-worker"]]')

cloudfront_active_key = "initial"
cloudfront_public_keys = {
  initial = <<-EOT
$(cat ~/motionile-secrets/cloudfront-production-public.pem)
EOT
}
EOF
cat infra/aws/envs/production/terraform.tfvars
```

Expected result: `oidc_provider_arn` ends in `oidc-provider/token.actions.githubusercontent.com`, and `promotion_source_repository_arns` lists two ARNs ending in `repository/staging/motionile-api` and `repository/staging/motionile-worker`.

### 24. Initialise and apply production with the CDN disabled

```bash
tofu -chdir=infra/aws/envs/production init -lockfile=readonly -backend-config=bucket=<STATE_BUCKET_NAME>
tofu -chdir=infra/aws/envs/production plan -out=production.tfplan
tofu -chdir=infra/aws/envs/production apply production.tfplan
```

Expected result: the same messages as steps 11 and 12. State goes to `s3://<STATE_BUCKET_NAME>/production/terraform.tfstate`. The plan must not create an `aws_iam_openid_connect_provider`; if it does, `create_oidc_provider` is not `false`.

### 25. Finish production with the staging steps

Repeat these staging steps with production values. Replace `envs/staging` with `envs/production`, `<STAGING_DOMAIN>` with `<PRODUCTION_DOMAIN>`, `staging` with `production` in file, key and parameter names:

1. Step 13: create the DNS records from `tofu -chdir=infra/aws/envs/production output -json dns_records`.
2. Step 14: confirm the production alert subscription (a second confirmation email arrives).
3. Step 15: wait until `cdn.<PRODUCTION_DOMAIN>` is `ISSUED`.
4. Step 16: set `enable_cdn = true` in `infra/aws/envs/production/terraform.tfvars` and apply again.
5. Step 17: add the `cdn` CNAME and check the two `403` responses.
6. Step 18: check the SES identity for `<PRODUCTION_DOMAIN>`, and request SES production access if you have not yet.
7. Step 19: build `infra/parameters/production.env` with **new** values (production Neon database, a production Turnstile widget for `<PRODUCTION_DOMAIN>`, new random values, `cloudfront-production-private.pem`), then run `AWS_REGION=ap-south-1 infra/scripts/put-parameters.sh production infra/parameters/production.env` and verify `/motionile/production`.
8. Steps 20 and 21: confirm cloud-init on the production instance and record its `DEPLOY_SSH_KNOWN_HOSTS` line.

Expected result: every check passes for production as it did for staging.

## What must never be committed

Before every commit, run `git status --short` and confirm none of these appear. Git already ignores them, but check anyway:

- `infra/aws/bootstrap/terraform.tfstate` and any `*.tfstate*` file.
- `infra/aws/envs/*/terraform.tfvars` and `*.tfplan` files.
- `infra/parameters/` and its `.env` files.
- `.terraform/` directories.
- Anything from `~/motionile-secrets`: SSH deploy keys and CloudFront private keys.

The `.terraform.lock.hcl` files are committed on purpose. If `tofu init` ever reports that it needs to change one, stop: you are on the wrong OpenTofu version or someone changed a provider version.
