# Vercel setup

Set up the Motionile web app (`apps/web`) on Vercel as one project that serves production from branch `prod` and staging from branch `develop`. In this repository `develop` is staging and `prod` is production.

Placeholders:

| Placeholder             | Meaning                                                                         |
| ----------------------- | ------------------------------------------------------------------------------- |
| `<GITHUB_OWNER>/<REPO>` | GitHub repository of Motionile                                                  |
| `<VERCEL_TEAM>`         | Vercel team (scope) that owns the project                                       |
| `<PROJECT_NAME>`        | Vercel project name, for example `motionile-web`                                |
| `<DOMAIN>`              | Production registrable domain, for example `motionile.com`                      |
| `<STAGING_DOMAIN>`      | Staging registrable domain; it is separate so production cookies never reach it |

The API, MCP and CDN hosts (`api.`, `mcp.`, `cdn.` under each domain) are created by OpenTofu; see [docs/infrastructure.md](../infrastructure.md). Finish that first or at least know the domains, because the web build bakes the API and CDN URLs into the bundle and the Content-Security-Policy.

## How the build is configured

`apps/web/vercel.json` holds the build settings, so the dashboard values for these fields are overridden by the file:

| Field            | Value                                                            | What it does                                                                                                                                                                                                                                                                    |
| ---------------- | ---------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `framework`      | `nextjs`                                                         | Uses the Next.js builder and output handling.                                                                                                                                                                                                                                   |
| `installCommand` | `cd ../.. && pnpm install --frozen-lockfile`                     | Installs the whole pnpm workspace from the repository root with the committed lockfile, so workspace packages such as `@motionile/api-contract` and `@motionile/config` resolve. Fails if `pnpm-lock.yaml` is out of date.                                                      |
| `buildCommand`   | `cd ../.. && pnpm turbo run build --filter=@motionile/web`       | Builds `@motionile/web` and its workspace dependencies with Turborepo from the root. `next build` runs inside `apps/web`, so the output lands in `apps/web/.next` where Vercel expects it.                                                                                      |
| `ignoreCommand`  | `npx --yes turbo-ignore@2.11.7 @motionile/web --fallback=HEAD^1` | Runs before install. Exits `0` (skip the build) when neither `@motionile/web`, its workspace dependencies nor the Turborepo global dependencies changed since the last successful deployment of the branch; exits `1` (build) otherwise. See [Skipped builds](#skipped-builds). |

Both commands `cd ../..`, so Vercel must ship the files outside `apps/web` into the build container. Keep **Include files outside the root directory in the Build Step** enabled; turning it off breaks the install.

Node.js and pnpm versions:

- The root `package.json` pins `"packageManager": "pnpm@10.34.7"` and `engines` `node >=24 <25`, `pnpm >=10 <11`; `.npmrc` sets `engine-strict=true`, so a wrong pnpm or Node.js major fails the install.
- `ENABLE_EXPERIMENTAL_COREPACK=1` makes Vercel enable Corepack, which reads `packageManager` and runs exactly pnpm 10.34.7.
- Vercel reads the Node.js version from the project setting (or `engines` in `apps/web/package.json`, which does not set one), not from `.node-version`. Set it to **24.x**.

## Steps

### 1. Import the repository

1. Open <https://vercel.com/new>, choose the team `<VERCEL_TEAM>`, and under **Import Git Repository** select `<GITHUB_OWNER>/<REPO>`. Install or extend the Vercel GitHub App for that repository if Vercel asks.
2. On **Configure Project**:
   - **Project Name**: `<PROJECT_NAME>`.
   - **Root Directory**: click **Edit**, select `apps/web`, click **Continue**.
   - **Framework Preset**: Next.js (detected from `vercel.json`).
   - Leave **Build and Output Settings** untouched; `vercel.json` overrides them.
   - Leave **Environment Variables** empty; you add them per environment in step 3.
3. Click **Deploy**.

Expected result: the project exists. The first deployment builds the repository's default branch and is expected to fail with `Invalid public environment variables` and `NEXT_PUBLIC_SITE_URL` because no variables exist yet. Ignore that failure.

Verify: the project page shows the GitHub repository under **Git Repository**.

### 2. Set the build and branch settings

1. Open **Settings → Build and Deployment**.
   - **Root Directory**: `apps/web`.
   - **Include files outside the root directory in the Build Step**: **Enabled**.
   - **Skip deployments when there are no changes to the root directory or its dependencies**: **Disabled**. The `ignoreCommand` already does this, and one mechanism is easier to reason about.
   - **Node.js Version**: **24.x**. Click **Save**.
   - **Framework Settings**: confirm the install and build commands show the `vercel.json` values and are marked as overridden.
2. Open **Settings → Environments → Production → Branch Tracking** and set the branch to `prod`. Click **Save**.
3. Open **Settings → Git** and confirm **Ignored Build Step** shows that the setting is overridden by `vercel.json`.
4. Open **Settings → Deployment Protection**. Set **Vercel Authentication** to **Disabled** (or, if your plan requires it, keep it only for generated `*.vercel.app` URLs). Under the default **Standard Protection**, preview deployments, including the staging domain on `develop`, require a Vercel login, which blocks the Playwright smoke project in `_deploy.yml` and the nightly k6 and ZAP runs against `WEB_URL`.

Expected result: production deploys only from `prod`; every other branch makes preview deployments.

Verify: **Settings → Environments → Production** shows `prod` as the tracked branch.

### 3. Add environment variables

Variable names are defined in `apps/web/src/config/env-schema.ts` (public, inlined at build time) and `apps/web/src/config/server-env.ts` (server only). Values are https origins without a trailing slash.

| Variable                       | Production (branch `prod`)                   | Preview, branch `develop` (staging)                  | Notes                                                                                                                                                                      |
| ------------------------------ | -------------------------------------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `NEXT_PUBLIC_SITE_URL`         | `https://<DOMAIN>`                           | `https://<STAGING_DOMAIN>`                           | Required; the build fails without it. Used for canonical URLs, metadata and the CSP.                                                                                       |
| `NEXT_PUBLIC_API_URL`          | `https://api.<DOMAIN>`                       | `https://api.<STAGING_DOMAIN>`                       | Must be set; it silently defaults to `http://localhost:8000`. Feeds the Axios base URL and the CSP `connect-src`.                                                          |
| `NEXT_PUBLIC_CDN_URL`          | `https://cdn.<DOMAIN>`                       | `https://cdn.<STAGING_DOMAIN>`                       | Optional until the CDN is enabled; feeds the CSP `img-src` and `media-src`.                                                                                                |
| `NEXT_PUBLIC_MEDIA_ORIGIN`     | `https://<bucket>.s3.<REGION>.amazonaws.com` | `https://<staging-bucket>.s3.<REGION>.amazonaws.com` | Optional; the storage origin of presigned media and admin music previews. Feeds the CSP `img-src` and `media-src`. Leave unset when every video is served through the CDN. |
| `API_INTERNAL_URL`             | `https://api.<DOMAIN>`                       | `https://api.<STAGING_DOMAIN>`                       | Optional and server only; on Vercel it equals `NEXT_PUBLIC_API_URL`. Never prefix it with `NEXT_PUBLIC_`.                                                                  |
| `CATALOG_REVALIDATION_SECRET`  | Random 32+ character secret                  | Separate random 32+ character secret                 | Required and server only. Use the same environment-specific value uploaded to the API's SSM parameter.                                                                     |
| `ENABLE_EXPERIMENTAL_COREPACK` | `1`                                          | `1`                                                  | Makes Vercel use pnpm 10.34.7 from `packageManager`. Add it to Preview without a branch so every preview builds with it too.                                               |

In the dashboard:

1. Open **Settings → Environment Variables**.
2. For each production value: enter the **Key** and **Value**, tick only **Production**, click **Save**.
3. For each staging value: enter the **Key** and **Value**, tick only **Preview**, choose the Git branch `develop` in the branch selector, click **Save**.
4. Add `ENABLE_EXPERIMENTAL_COREPACK` = `1` with **Production** and **Preview** (all branches) ticked.

Or with the Vercel CLI from the repository root, after `vercel link --yes --project <PROJECT_NAME> --scope <VERCEL_TEAM>`:

```bash
printf '%s' 'https://<DOMAIN>' | vercel env add NEXT_PUBLIC_SITE_URL production
printf '%s' 'https://api.<DOMAIN>' | vercel env add NEXT_PUBLIC_API_URL production
printf '%s' 'https://cdn.<DOMAIN>' | vercel env add NEXT_PUBLIC_CDN_URL production
printf '%s' 'https://api.<DOMAIN>' | vercel env add API_INTERNAL_URL production
printf '%s' '<PRODUCTION_REVALIDATION_SECRET>' | vercel env add CATALOG_REVALIDATION_SECRET production
printf '%s' '1' | vercel env add ENABLE_EXPERIMENTAL_COREPACK production

printf '%s' 'https://<STAGING_DOMAIN>' | vercel env add NEXT_PUBLIC_SITE_URL preview develop
printf '%s' 'https://api.<STAGING_DOMAIN>' | vercel env add NEXT_PUBLIC_API_URL preview develop
printf '%s' 'https://cdn.<STAGING_DOMAIN>' | vercel env add NEXT_PUBLIC_CDN_URL preview develop
printf '%s' 'https://api.<STAGING_DOMAIN>' | vercel env add API_INTERNAL_URL preview develop
printf '%s' '<STAGING_REVALIDATION_SECRET>' | vercel env add CATALOG_REVALIDATION_SECRET preview develop
printf '%s' '1' | vercel env add ENABLE_EXPERIMENTAL_COREPACK preview
```

Expected result: each variable is listed once per environment, the staging ones with the label `develop`.

Verify:

```bash
vercel env ls production
vercel env ls preview develop
```

`NEXT_PUBLIC_*` values are inlined at build time. After changing any of them, redeploy (step 5); a running deployment never picks them up.

### 4. Add the domains

Keep DNS at your current provider. The `api`, `mcp` and `cdn` records and the SES and ACM records already live there, so do not move the nameservers to Vercel.

1. Open **Settings → Domains → Add Domain**, enter `<DOMAIN>`, connect it to **Production**, click **Save**. When Vercel offers to add `www.<DOMAIN>` and redirect it, accept with `<DOMAIN>` as the target. Otherwise add `www.<DOMAIN>` separately, choose **Redirect to Another Domain**, target `<DOMAIN>`, status **308 Permanent Redirect**. The apex is canonical and `www` redirects to it, as `docs/context.md` section 11 requires.
2. Add `<STAGING_DOMAIN>`, connect it to **Preview**, and set **Git Branch** to `develop`. Click **Save**.
3. For every domain Vercel shows as **Invalid Configuration**, open it and create exactly the records it displays at your DNS provider. Typically:

   | Host                                     | Type    | Value                                       |
   | ---------------------------------------- | ------- | ------------------------------------------- |
   | `<DOMAIN>` (apex, `@`)                   | `A`     | The IP address Vercel shows for the project |
   | `www.<DOMAIN>`                           | `CNAME` | The `*.vercel-dns*.com` target Vercel shows |
   | `<STAGING_DOMAIN>` (apex, `@`)           | `A`     | The IP address Vercel shows for the project |
   | `_vercel.<DOMAIN>` (only if Vercel asks) | `TXT`   | The verification value Vercel shows         |

   Remove any older `A` or `AAAA` record on the same names. If the zone has `CAA` records, they must allow `letsencrypt.org` (Vercel and Caddy) and `amazon.com` (ACM for the CDN certificate).

Expected result: within minutes of DNS propagation every domain shows **Valid Configuration** and a certificate is issued.

Verify:

```bash
dig +short A <DOMAIN>
dig +short CNAME www.<DOMAIN>
dig +short A <STAGING_DOMAIN>
```

Each answer matches the value in the Vercel domain panel.

### 5. Deploy both branches

1. Trigger staging: open **Deployments**, find the latest deployment of `develop`, open its menu (`⋯`), choose **Redeploy**. Or push a commit that changes `apps/web` to `develop`.
2. Trigger production after the first release has reached `prod`: redeploy the latest `prod` deployment the same way.

Expected result: the build log shows `pnpm install --frozen-lockfile` using pnpm 10.34.7, `turbo run build --filter=@motionile/web`, and **Ready**. The staging domain points at the newest `develop` deployment and `<DOMAIN>` at the newest `prod` deployment.

### 6. Verify the deployments

```bash
curl -sI https://<DOMAIN> | grep -i -E '^(HTTP|strict-transport-security|content-security-policy|x-frame-options|referrer-policy)'
curl -sI https://www.<DOMAIN> | grep -i -E '^(HTTP|location)'
curl -sI https://<STAGING_DOMAIN> | grep -i -E '^(HTTP|strict-transport-security|content-security-policy)'
```

Expected result:

- `HTTP/2 200` for `<DOMAIN>` and `<STAGING_DOMAIN>` (not `401`; a `401` means Vercel Authentication still protects the staging domain).
- `strict-transport-security: max-age=63072000; includeSubDomains; preload`.
- `content-security-policy:` starting with `default-src 'self'`, whose `connect-src` contains `https://api.<DOMAIN>` (staging: `https://api.<STAGING_DOMAIN>`), and, once `NEXT_PUBLIC_CDN_URL` is set, whose `img-src` and `media-src` contain the CDN origin. `http://localhost:8000` in `connect-src` means `NEXT_PUBLIC_API_URL` was missing at build time.
- `x-frame-options: DENY` and `referrer-policy: strict-origin-when-cross-origin`.
- `www.<DOMAIN>` answers `HTTP/2 308` with `location: https://<DOMAIN>/`.

These headers come from `apps/web/next.config.ts` and `apps/web/src/config/security-headers.ts`.

Finally open `https://<DOMAIN>` and `https://<STAGING_DOMAIN>` in a browser: the home page renders in the dark theme, the browser console shows no CSP violations, and the page source has a `<link rel="canonical">` whose `href` starts with `https://<DOMAIN>` (staging: `https://<STAGING_DOMAIN>`).

## Skipped builds

`turbo-ignore` compares `HEAD` with `VERCEL_GIT_PREVIOUS_SHA`, the commit of the last successful deployment of the same branch, and falls back to `HEAD^1` on a branch's first deployment. It builds when any of these changed:

- files under `apps/web` (task inputs exclude tests and coverage),
- workspace packages `@motionile/web` depends on, such as `packages/api-contract` and `packages/config`,
- Turborepo global dependencies from `turbo.json`: `.node-version`, `.python-version`, `.npmrc`, `packages/config/typescript/*.json`,
- the lockfile entries of those packages.

A push that only touches `apps/server`, `infra`, `deploy`, `docs` or `tests` is skipped. The deployment then shows as canceled with a message that the Ignored Build Step decided not to build. This is expected and leaves the current deployment live.

To force a build without a code change, include `[vercel deploy]` in the commit message, or redeploy the last deployment from the dashboard.

## Troubleshooting

| Symptom                                          | Cause and fix                                                                                                     |
| ------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------- |
| `ERR_PNPM_UNSUPPORTED_ENGINE` or a pnpm 9 banner | `ENABLE_EXPERIMENTAL_COREPACK=1` is missing for that environment, or Node.js Version is not 24.x.                 |
| `Cannot find module` for a workspace package     | **Include files outside the root directory in the Build Step** is disabled.                                       |
| `ERR_PNPM_OUTDATED_LOCKFILE`                     | `pnpm-lock.yaml` was not committed after a dependency change. Run `pnpm install` locally and commit the lockfile. |
| `Invalid public environment variables`           | `NEXT_PUBLIC_SITE_URL` missing or not an http(s) URL for that environment or branch.                              |
| Staging builds use production values             | The Preview variables were not scoped to `develop`, or the Production variables were ticked for Preview as well.  |
