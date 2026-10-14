# GitHub setup

This runbook configures the GitHub repository so that a push to `develop` deploys staging and a push to `prod` deploys production after approval. The branch `develop` maps to the `staging` environment and `prod` maps to `production`.

Do this after [bootstrap-aws.md](bootstrap-aws.md): every value below comes from its outputs or from files it created. Then continue with [deploy-and-rollback.md](deploy-and-rollback.md).

## Before you start

1. Check your GitHub plan. Environments, environment secrets, required reviewers and rulesets are not available for private repositories on every plan. Read GitHub's "Managing environments for deployment" and "About rulesets" pages and confirm your plan covers them for this repository.
2. Install the GitHub CLI and sign in as a repository admin:

   ```bash
   gh auth login
   gh auth status
   ```

   Expected result: `Logged in to github.com account <YOUR_LOGIN>` with the `repo` and `workflow` scopes.

3. Set the repository for the commands below and check that you are an admin:

   ```bash
   repo=<GITHUB_OWNER>/<GITHUB_REPOSITORY>
   gh api "repos/$repo" --jq '.permissions.admin'
   ```

   Expected result: `true`.

4. Run everything from the repository root with `export AWS_PROFILE=<AWS_PROFILE>` set, so `tofu output` can read the state.

GitHub Actions OIDC needs nothing extra. The deploy jobs already request `id-token: write`, and each AWS deploy role trusts only `repo:<GITHUB_OWNER>/<GITHUB_REPOSITORY>:environment:<staging|production>`. That is why the environment names must be exactly `staging` and `production`.

## Where every value comes from

| Name                     | Scope                                   | Source                                                                                                                  |
| ------------------------ | --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `DEPLOY_SSH_PRIVATE_KEY` | Environment secret, `staging`           | `~/motionile-secrets/motionile-staging-deploy` (bootstrap step 8)                                                       |
| `DEPLOY_SSH_PRIVATE_KEY` | Environment secret, `production`        | `~/motionile-secrets/motionile-production-deploy` (bootstrap step 22)                                                   |
| `AWS_REGION`             | Environment variable, both environments | `tofu -chdir=infra/aws/envs/<env> output -json github_environment_variables \| jq -r .AWS_REGION`                       |
| `AWS_DEPLOY_ROLE_ARN`    | Environment variable, both environments | `tofu -chdir=infra/aws/envs/<env> output -raw deploy_role_arn`                                                          |
| `ECR_REGISTRY`           | Environment variable, both environments | `tofu -chdir=infra/aws/envs/<env> output -raw ecr_registry`                                                             |
| `EC2_SECURITY_GROUP_ID`  | Environment variable, both environments | `tofu -chdir=infra/aws/envs/<env> output -raw security_group_id`                                                        |
| `DEPLOY_HOST`            | Environment variable, both environments | `tofu -chdir=infra/aws/envs/<env> output -raw elastic_ip`                                                               |
| `DEPLOY_SSH_KNOWN_HOSTS` | Environment variable, both environments | The line from bootstrap step 21: `<ELASTIC_IP> ssh-ed25519 <HOST_KEY>`                                                  |
| `API_URL`                | Environment variable, both environments | `tofu -chdir=infra/aws/envs/<env> output -json github_environment_variables \| jq -r .API_URL` (`https://api.<domain>`) |
| `MCP_URL`                | Environment variable, both environments | `tofu -chdir=infra/aws/envs/<env> output -json github_environment_variables \| jq -r .MCP_URL` (`https://mcp.<domain>`) |
| `WEB_URL`                | Environment variable, both environments | `tofu -chdir=infra/aws/envs/<env> output -json github_environment_variables \| jq -r .WEB_URL` (the `web_origin`)       |
| `STAGING_WEB_URL`        | Repository variable                     | `tofu -chdir=infra/aws/envs/staging output -json github_environment_variables \| jq -r .WEB_URL`                        |
| `STAGING_API_URL`        | Repository variable                     | `tofu -chdir=infra/aws/envs/staging output -json github_environment_variables \| jq -r .API_URL`                        |

The `github_environment_variables` output also contains `IMAGE_REPOSITORY_API` and `IMAGE_REPOSITORY_WORKER`. No workflow reads them, so the commands below skip them. No other secret is stored in GitHub: AWS access uses OIDC, and application secrets stay in SSM.

## Steps

### 1. Create the `staging` environment

In the browser: **Settings > Environments > New environment**, name `staging`. Under **Deployment branches and tags**, choose **Selected branches and tags** and add the branch rule `develop`. Do not add required reviewers: the staging build job also runs in this environment.

Or with the CLI:

```bash
gh api --method PUT "repos/$repo/environments/staging" --input - <<'JSON'
{"deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}}
JSON
gh api --method POST "repos/$repo/environments/staging/deployment-branch-policies" -f name=develop -f type=branch
```

Verify:

```bash
gh api "repos/$repo/environments/staging/deployment-branch-policies" --jq '.branch_policies[].name'
```

Expected result: `develop`.

### 2. Add the staging secret and variables

```bash
gh secret set DEPLOY_SSH_PRIVATE_KEY --env staging --repo "$repo" < ~/motionile-secrets/motionile-staging-deploy

tofu -chdir=infra/aws/envs/staging output -json github_environment_variables \
  | jq -r 'del(.IMAGE_REPOSITORY_API, .IMAGE_REPOSITORY_WORKER) | to_entries[] | "\(.key)\t\(.value)"' \
  | while IFS=$'\t' read -r name value; do
      gh variable set "$name" --env staging --repo "$repo" --body "$value"
    done

gh variable set DEPLOY_SSH_KNOWN_HOSTS --env staging --repo "$repo" --body '<STAGING_ELASTIC_IP> ssh-ed25519 <STAGING_HOST_KEY>'
```

Verify:

```bash
gh secret list --env staging --repo "$repo"
gh variable list --env staging --repo "$repo"
```

Expected result: the secret `DEPLOY_SSH_PRIVATE_KEY`, and the nine variables `API_URL`, `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`, `DEPLOY_HOST`, `DEPLOY_SSH_KNOWN_HOSTS`, `EC2_SECURITY_GROUP_ID`, `ECR_REGISTRY`, `MCP_URL` and `WEB_URL`. `DEPLOY_SSH_KNOWN_HOSTS` must start with the same IP as `DEPLOY_HOST`.

### 3. Create the `production` environment

In the browser: **Settings > Environments > New environment**, name `production`, then:

1. Tick **Required reviewers** and add the people who approve production deployments.
2. Tick **Prevent self-review**, so the person who pushed the release cannot approve its deployment. This needs at least two people; with only one reviewer who is also the release manager, no deployment can ever be approved.
3. Under **Deployment branches and tags**, choose **Selected branches and tags** and add the branch rule `prod`.

Or with the CLI, for one reviewer (add more objects to `reviewers` for more people or a team with `"type": "Team"`):

```bash
reviewer_id=$(gh api users/<REVIEWER_LOGIN> --jq .id)
gh api --method PUT "repos/$repo/environments/production" --input - <<JSON
{
  "prevent_self_review": true,
  "reviewers": [{"type": "User", "id": $reviewer_id}],
  "deployment_branch_policy": {"protected_branches": false, "custom_branch_policies": true}
}
JSON
gh api --method POST "repos/$repo/environments/production/deployment-branch-policies" -f name=prod -f type=branch
```

Verify:

```bash
gh api "repos/$repo/environments/production" --jq '.protection_rules[] | {type, prevent_self_review, reviewers: [.reviewers[]?.reviewer.login]}'
gh api "repos/$repo/environments/production/deployment-branch-policies" --jq '.branch_policies[].name'
```

Expected result: a `required_reviewers` rule with `prevent_self_review: true` and your reviewers, a `branch_policy` rule, and `prod`.

### 4. Add the production secret and variables

```bash
gh secret set DEPLOY_SSH_PRIVATE_KEY --env production --repo "$repo" < ~/motionile-secrets/motionile-production-deploy

tofu -chdir=infra/aws/envs/production output -json github_environment_variables \
  | jq -r 'del(.IMAGE_REPOSITORY_API, .IMAGE_REPOSITORY_WORKER) | to_entries[] | "\(.key)\t\(.value)"' \
  | while IFS=$'\t' read -r name value; do
      gh variable set "$name" --env production --repo "$repo" --body "$value"
    done

gh variable set DEPLOY_SSH_KNOWN_HOSTS --env production --repo "$repo" --body '<PRODUCTION_ELASTIC_IP> ssh-ed25519 <PRODUCTION_HOST_KEY>'
```

Verify:

```bash
gh secret list --env production --repo "$repo"
gh variable list --env production --repo "$repo"
```

Expected result: the same secret and nine variables as staging, with production values. `ECR_REGISTRY` is the same as staging because both environments share the account and region; `AWS_DEPLOY_ROLE_ARN` ends in `motionile-production-github-deploy`.

### 5. Add the repository variables for the nightly workflow

`nightly.yml` runs load tests, a ZAP full scan and full evals against staging.

```bash
gh variable set STAGING_WEB_URL --repo "$repo" \
  --body "$(tofu -chdir=infra/aws/envs/staging output -json github_environment_variables | jq -r .WEB_URL)"
gh variable set STAGING_API_URL --repo "$repo" \
  --body "$(tofu -chdir=infra/aws/envs/staging output -json github_environment_variables | jq -r .API_URL)"
gh variable list --repo "$repo"
```

Expected result: `STAGING_WEB_URL` is `https://<STAGING_DOMAIN>` and `STAGING_API_URL` is `https://api.<STAGING_DOMAIN>`.

### 6. Protect `develop` with a ruleset

The ruleset requires a pull request and the `ci-ok` check, and blocks force pushes and deletion. Nobody bypasses it.

In the browser: **Settings > Rules > Rulesets > New ruleset > New branch ruleset**, name `develop`, enforcement **Active**, target branch `develop`, and enable **Restrict deletions**, **Block force pushes**, **Require a pull request before merging** and **Require status checks to pass** with the check `ci-ok`.

Or with the CLI:

```bash
gh api --method POST "repos/$repo/rulesets" --input - <<'JSON'
{
  "name": "develop",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["refs/heads/develop"], "exclude": []}},
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [{"context": "ci-ok"}]
      }
    }
  ]
}
JSON
```

Raise `required_approving_review_count` to `1` once a second engineer reviews pull requests.

### 7. Protect `prod` with a ruleset

`prod` gets the same rules plus linear history. Repository admins (the release managers) may bypass the ruleset, because a release is a fast-forward push, not a merge button.

In the browser: as in step 6 with name `prod` and target branch `prod`, also enable **Require linear history**, and under **Bypass list** add the **Repository admin** role with **Always allow**.

Or with the CLI (`actor_id` 5 is the built-in Repository admin role):

```bash
gh api --method POST "repos/$repo/rulesets" --input - <<'JSON'
{
  "name": "prod",
  "target": "branch",
  "enforcement": "active",
  "conditions": {"ref_name": {"include": ["refs/heads/prod"], "exclude": []}},
  "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"}],
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"},
    {"type": "required_linear_history"},
    {
      "type": "pull_request",
      "parameters": {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": true,
        "require_code_owner_review": false,
        "require_last_push_approval": false,
        "required_review_thread_resolution": true
      }
    },
    {
      "type": "required_status_checks",
      "parameters": {
        "strict_required_status_checks_policy": false,
        "required_status_checks": [{"context": "ci-ok"}]
      }
    }
  ]
}
JSON
```

Keep the admin role limited to release managers.

Verify both rulesets:

```bash
gh api "repos/$repo/rulesets" --jq '.[] | [.name, .enforcement] | @tsv'
gh api "repos/$repo/rules/branches/prod" --jq '.[].type'
```

Expected result: `develop active` and `prod active`, and for `prod` the rule types `deletion`, `non_fast_forward`, `required_linear_history`, `pull_request` and `required_status_checks`. If the repository also has classic branch protection on these branches, remove it or make it match, so only one set of rules applies.

If `prod` does not exist yet, create it at your first release with the procedure below (`git push origin origin/develop:prod` creates it).

### 8. Verify with a staging deployment

The web app must already be live on Vercel at `WEB_URL`, because the deployment ends with a Playwright smoke test against it. Then start "Deploy staging" by hand on `develop`:

```bash
gh workflow run deploy-staging.yml --repo "$repo" --ref develop
sleep 5
run_id=$(gh run list --repo "$repo" --workflow deploy-staging.yml --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch "$run_id" --repo "$repo" --exit-status
```

Expected result: the jobs `build motionile-api`, `build motionile-worker` and `deploy / deploy staging` finish green, and `gh run watch` exits with status 0. In **Settings > Environments > staging** (or the repository's **Deployments** page) a successful deployment points at `WEB_URL`.

Then check the services from your machine:

```bash
curl -fsS https://api.<STAGING_DOMAIN>/health/ready
curl -fsS https://mcp.<STAGING_DOMAIN>/health/live
```

Expected result: both return HTTP 200 with a JSON body. If the run fails, open it with `gh run view "$run_id" --repo "$repo" --log-failed` and compare the error with the troubleshooting table below.

| Error in the run                                                              | Fix                                                                                       |
| ----------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| `environment variable <NAME> is not set on the staging GitHub environment`    | Set the variable from step 2.                                                             |
| `Not authorized to perform sts:AssumeRoleWithWebIdentity`                     | The environment name or `github_repository` in `terraform.tfvars` does not match exactly. |
| `... is not allowed to deploy to staging due to environment protection rules` | Run the workflow with `--ref develop`.                                                    |
| `could not reach <IP> over SSH` or `Host key verification failed`             | Recheck `DEPLOY_HOST`, `DEPLOY_SSH_KNOWN_HOSTS` and the private key secret.               |
| `missing required parameters under /motionile/staging`                        | Upload the listed parameters with `put-parameters.sh` (bootstrap step 19).                |

## Release procedure: `develop` to `prod`

Production never builds images. `deploy-production.yml` takes the commit SHA at the tip of `prod`, copies the images tagged with that SHA from the staging ECR repositories into the production repositories, and deploys them. If staging has no image for that SHA, the run stops with `staging/motionile-api has no image tagged <SHA>`. So `prod` must always point at a commit that already ran on staging, with the identical SHA.

GitHub's merge, squash and rebase buttons all create new commits with new SHAs, even when a fast-forward would be possible. Never use them for `prod`. Release with a fast-forward push instead.

1. Confirm the commit you want to release is deployed to staging:

   ```bash
   git fetch origin
   git rev-parse origin/develop
   gh run list --repo "$repo" --workflow deploy-staging.yml --branch develop --limit 1 --json headSha,conclusion
   ```

   Expected result: `headSha` equals `origin/develop` and `conclusion` is `success`. If not, wait for the staging run or fix it first.

2. Open a release pull request so CI and review run on exactly what will ship:

   ```bash
   gh pr create --repo "$repo" --base prod --head develop --title "release: <YYYY-MM-DD>" --body "Release of $(git rev-parse --short origin/develop) to production."
   ```

   Expected result: a pull request URL. Wait until `ci-ok` is green and the reviewers are satisfied. Do not press any merge button.

3. As a release manager, fast-forward `prod` to `develop`:

   ```bash
   git fetch origin
   git merge-base --is-ancestor origin/prod origin/develop && echo "fast-forward possible"
   git push origin origin/develop:prod
   ```

   Expected result: `fast-forward possible`, then a push line like `<old>..<new>  origin/develop -> prod`. Git refuses the push if it is not a fast-forward; never add `--force`. If `origin/prod` does not exist yet, skip the `merge-base` check; the push creates `prod`.

4. Confirm the result:

   ```bash
   git fetch origin
   test "$(git rev-parse origin/prod)" = "$(git rev-parse origin/develop)" && echo "prod matches develop"
   gh pr view <PR_NUMBER> --repo "$repo" --json state --jq .state
   ```

   Expected result: `prod matches develop` and `MERGED`. GitHub marks the pull request as merged on its own because its head commit is now on `prod`.

5. Approve the deployment. "Deploy production" starts and waits for approval. A reviewer other than the release manager opens the run under **Actions > Deploy production**, chooses **Review deployments**, ticks `production` and approves. Follow it as described in [deploy-and-rollback.md](deploy-and-rollback.md).

Hotfixes follow the same path: merge the fix into `develop` through a pull request, let staging deploy it, then release.

If someone merged into `prod` with a button by mistake, the production run fails at the promote step and production keeps running the previous release. To recover without force-pushing, open a pull request from `prod` into `develop` and merge it with **Create a merge commit** (not squash), so `develop` contains the stray commit; wait for staging to deploy the new `develop` tip; then release with the procedure above.
