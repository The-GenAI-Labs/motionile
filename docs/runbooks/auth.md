# Auth operations

## Deploying Phase 4

Follow the existing infrastructure/deployment runbooks. The repository deploys staging from develop, so the phase branch targets develop; there is no staging branch. Apply 20261015_0003 before starting the API/worker. It creates seven auth/identity tables, seeds user/admin/super_admin and adds users foreign keys to audit_log and idempotency_records. Downgrade removes these additions and their auth data; follow backup and rollback procedures.

Upload owner parameters through infra/scripts/put-parameters.sh to the environment's SSM prefix. Never place secrets in OpenTofu, committed files, logs or shell history. deploy/parameters.csv is authoritative.

| Parameters                                                           | Required value                                                                       |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| AUTH_JWT_KEYS                                                        | JSON map of kid to base64 random 32-byte Ed25519 private seed                        |
| AUTH_JWT_CURRENT_KID                                                 | Entry in that ring                                                                   |
| AUTH_JWT_ISSUER, AUTH_JWT_AUDIENCE                                   | Environment-specific HTTPS API issuer and audience                                   |
| AUTH_COOKIE_DOMAIN                                                   | Shared web/API cookie domain; avoid overlap across environments                      |
| AUTH_WEB_ORIGIN, AUTH_API_ORIGIN                                     | Exact HTTPS origins with no path/trailing slash; web origin must be CORS-allowlisted |
| AUTH_OTP_PEPPER, AUTH_CSRF_SECRET                                    | Independent random secrets, at least 32 characters                                   |
| AUTH_HIBP_ENABLED                                                    | true                                                                                 |
| AUTH_GOOGLE_CLIENT_ID, AUTH_GOOGLE_CLIENT_SECRET                     | Google web OAuth client                                                              |
| AUTH_GITHUB_CLIENT_ID, AUTH_GITHUB_CLIENT_SECRET                     | GitHub OAuth app                                                                     |
| AUTH_MICROSOFT_CLIENT_ID, AUTH_MICROSOFT_CLIENT_SECRET               | Microsoft app registration                                                           |
| NOTIFICATIONS_EMAIL_BACKEND                                          | ses                                                                                  |
| NOTIFICATIONS_SENDER, NOTIFICATIONS_SES_REGION                       | Verified sender and SES region                                                       |
| NOTIFICATIONS_WHATSAPP_TOKEN, NOTIFICATIONS_WHATSAPP_PHONE_NUMBER_ID | Meta system-user token and sending number ID                                         |
| NOTIFICATIONS_WHATSAPP_TEMPLATE, NOTIFICATIONS_WHATSAPP_LANGUAGE     | Approved authentication template and language                                        |
| NOTIFICATIONS_WHATSAPP_NOTICE_TEMPLATE                               | Approved utility/security template with one body parameter                           |
| NOTIFICATIONS_WHATSAPP_API_VERSION                                   | Supported pinned Graph version                                                       |

SES_CONFIGURATION_SET is infrastructure-owned and passed to SES v2 sends. The instance role supplies AWS credentials. Confirm SES identity/configuration-set IAM scopes, domain verification/DKIM and sandbox recipient restrictions. Workers need the existing ENCRYPTION_KEYS to decrypt queued messages.

## Provider consoles

Create separate clients per environment with these exact redirects, replacing the origin:

- Google: <api-origin>/v1/auth/oauth/google/callback
- GitHub: <api-origin>/v1/auth/oauth/github/callback
- Microsoft: <api-origin>/v1/auth/oauth/microsoft/callback

Google uses openid email profile; GitHub uses read:user user:email; Microsoft uses openid email profile for organizational and personal accounts. Configure Microsoft's xms_edov optional claim when organizational automatic email linking is required. Without trustworthy email verification, sign in another way and link from settings. No offline-access or write permissions are needed.

All outbound traffic uses SafeHttpClient and per-provider host allowlists in core/resources.py. No issuer URL from an unverified token is fetched.

Approve a Meta AUTHENTICATION template with a six-digit body substitution and OTP COPY_CODE button. Sending uses body text plus a button component with sub_type=url, index=0 and the same code. The unit contract test asserts the complete request shape. Configure matching language/template names. Approve a separate utility template with one body text parameter for Motionile security notices. See [Meta's official template example](https://www.postman.com/meta/whatsapp-business-platform/request/6vkv46u/create-authentication-template-w-otp-copy-code-button). Provider acceptance does not prove recipient delivery.

## Local verification

Run the Compose development stack and migrations. Fake mode queues encrypted jobs; worker-default must run for OTP delivery. The fake inbox is available only in local/CI fake mode. Root API helpers carry Secure cookies explicitly over local HTTP; browser flows require HTTPS.

For Mailpit, use local APP_ENV and PROVIDERS_MODE=live, NOTIFICATIONS_EMAIL_BACKEND=smtp, NOTIFICATIONS_SMTP_HOST=mailpit inside containers (localhost from the host), port 1025 and STARTTLS false. Use Cloudflare dummy Turnstile credentials with matching action/hostname. SMTP username/password are optional local settings. Open http://localhost:8025 and inspect HTML and plain text for every template: readable monochrome layout, code and Motionile signature. The fake inbox is unavailable in live mode.

Run pnpm verify, pnpm test:integration and the root e2e/security suites. AUTH_LOAD_ACCOUNTS is a securely injected JSON array of preverified identifier/password objects, one per VU (five smoke, fifty full). Run bash tests/load/run-smoke.sh auth against local/CI fake mode only. The full profile needs an isolated load-environment override for the shared source IP's login quota; preserve per-session refresh limits. The scenario refreshes every three seconds and retains common p95<300ms, failure<1%, checks>99% thresholds.

## Key rotation

1. Add a new random seed under a new kid to AUTH_JWT_KEYS on every instance, retaining the old seed and current kid.
2. Switch AUTH_JWT_CURRENT_KID and roll every API instance. Confirm public JWKS contains both keys and new tokens use the new kid.
3. Wait at least 905 seconds after the last old-key issuer stops, plus the five-minute JWKS cache duration.
4. Remove the old seed and roll again. Never reuse a kid for a different seed.

OTP pepper rotation invalidates outstanding codes. CSRF secret rotation invalidates existing CSRF values until fresh sign-in. Retain AES-GCM key versions until their queued jobs drain.

## Troubleshooting and staging acceptance

Use request IDs and auth audit events. Never paste codes, tokens or passwords into logs. Access logs omit queries and use route templates; verbose third-party HTTP logging is suppressed. refresh_conflict indicates competing refresh calls; refresh_reused revokes the entire family and requires sign-in. Redis failures fail closed for auth protections.

Observe notification retries on the default queue. After-commit enqueue has the crash window described in ADR 0014; resend is the recovery path. Do not manually replay captured OTP payloads.

After staging deploys, check health/readiness, JWKS, registration with a real delivered SES code, verification, me, refresh and logout. Test each real OAuth client and security notices; inspect SES/WhatsApp delivery evidence. Record deployment SHA and results in the PR. Local tests do not replace these environment-dependent acceptance checks.

## Frontend deployment verification

Set the Vercel API and site origins, Turnstile site key, and matching AUTH_JWT_ISSUER and AUTH_JWT_AUDIENCE. Leave NEXT_PUBLIC_JWKS_URL unset to use the public API JWKS path, or configure its explicit server-reachable URL. Keep AUTH_COOKIE_DOMAIN empty on localhost and set the shared staging domain on deployed instances.

For container builds, pass NEXT_PUBLIC_TURNSTILE_SITE_KEY and the optional NEXT_PUBLIC_JWKS_URL as Docker build arguments alongside the site and API origins. Public values are compiled into the frontend; changing only runtime environment variables does not update them. Set AUTH_JWT_ISSUER and AUTH_JWT_AUDIENCE in the running web container.

Browser CI uses the HTTPS reverse proxy and AUTH_TEST_ACCESS_SECONDS=75 with fake providers. Never configure this test override on staging or production; startup rejects it. After deploying Phase 5, register a staging account through real email OTP, sign out and back in, wait for silent refresh, revoke another session, and check account linking. CI and local fakes do not replace this real-delivery acceptance check.
