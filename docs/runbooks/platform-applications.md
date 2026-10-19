# Runbook: platform developer applications and approvals

This runbook lists every external account, app registration and review that Motionile depends on. Many reviews take days to weeks and several need business documents, so the owner starts all of them in Phase 3, as `docs/roadmap.md` requires ("Developer applications for every publishing platform have been submitted"), even though the code that uses most of them lands in later phases.

Branches: `develop` deploys to staging and `prod` deploys to production. Everything below is registered twice, once per environment, with separate client IDs and secrets.

Requirements on these platforms change often. Every section links the official page; when this runbook and the console disagree, follow the console and update this file. Facts were checked on 2026-10-14.

## Contents

1. [Before you start](#1-before-you-start)
2. [Fixed values for every application](#2-fixed-values-for-every-application)
3. [Order of work](#3-order-of-work)
4. [Login providers](#4-login-providers)
5. [Messaging and bot protection](#5-messaging-and-bot-protection)
6. [Email: Amazon SES production access](#6-email-amazon-ses-production-access)
7. [Payments: Razorpay](#7-payments-razorpay)
8. [Publishing platforms](#8-publishing-platforms)
9. [Scope justifications to paste](#9-scope-justifications-to-paste)
10. [Reviews that need a demo video](#10-reviews-that-need-a-demo-video)
11. [Where credentials go](#11-where-credentials-go)
12. [Tracking table](#12-tracking-table)

## 1. Before you start

Reviewers open the site, read the legal pages and email the contact addresses. Finish these first, because a single dead link or placeholder is the most common reason for rejection.

1. Incorporate or confirm the legal entity and replace every placeholder in `siteConfig.legal` in `apps/web/src/config/site.ts`: `entityName`, `registeredAddress`, `jurisdictionCity`, `grievanceOfficerName`, `gstin`, `effectiveDate`, `lastUpdated`. The legal name must match the GST certificate, PAN and bank account exactly; Meta, Razorpay and LinkedIn all compare them.
2. Deploy the production web app on `<PRODUCTION_DOMAIN>` and the staging web app on `<STAGING_DOMAIN>` (see the Phase 3 infrastructure runbooks). Every URL in section 2 must return `200` over HTTPS without a login.
3. Create the mailboxes in section 2 and confirm each one receives external mail. Reviewers write to them.
4. Add a business phone number to the contact page and the grievance officer details. Razorpay and the Consumer Protection (E-Commerce) Rules expect a working phone number; the current contact page shows email and address only.
5. Make sure `/legal/data-deletion` is live (it is added in Phase 3). Meta, TikTok and Google all ask for it.
6. Verify `<PRODUCTION_DOMAIN>` and `<STAGING_DOMAIN>` in [Google Search Console](https://search.google.com/search-console) with a DNS TXT record, using the Google account that will own the Google Cloud projects.
7. Create a [Meta business portfolio](https://business.facebook.com/) in the company's legal name, a [LinkedIn Company Page](https://www.linkedin.com/company/setup/new/) for Motionile, and the YouTube channel `@motionile`. Several applications require them.
8. Store every credential in the company password manager under `Motionile / <platform> / <environment>`. Never paste a secret into an issue, chat or commit.
9. Prepare the app icon (section 2) once and reuse it everywhere.

## 2. Fixed values for every application

Use `<domain>` = `<PRODUCTION_DOMAIN>` for the production app and `<STAGING_DOMAIN>` for the staging app. The production domain is `motionile.com` until confirmed (`docs/context.md` section 11).

| Field                             | Value                                                                                                                                                    |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| App name (production)             | `Motionile`                                                                                                                                              |
| App name (staging)                | `Motionile Staging`                                                                                                                                      |
| Website / home page               | `https://<domain>`                                                                                                                                       |
| Privacy policy                    | `https://<domain>/legal/privacy`                                                                                                                         |
| Terms of service                  | `https://<domain>/legal/terms`                                                                                                                           |
| Refund and cancellation policy    | `https://<domain>/legal/refund-policy`                                                                                                                   |
| Data deletion instructions        | `https://<domain>/legal/data-deletion`                                                                                                                   |
| Pricing                           | `https://<domain>/pricing`                                                                                                                               |
| Contact                           | `https://<domain>/contact`                                                                                                                               |
| About                             | `https://<domain>/about`                                                                                                                                 |
| Login OAuth redirect URI          | `https://api.<domain>/v1/auth/oauth/<provider>/callback`, `<provider>` in `google`, `github`, `microsoft`                                                |
| Publishing OAuth redirect URI     | `https://api.<domain>/v1/publishing/oauth/<platform>/callback`, `<platform>` in `youtube`, `instagram`, `facebook`, `threads`, `linkedin`, `x`, `tiktok` |
| Razorpay webhook URL              | `https://api.<domain>/v1/webhooks/razorpay`                                                                                                              |
| Support email                     | `support@motionile.com`                                                                                                                                  |
| Privacy / data protection email   | `privacy@motionile.com`                                                                                                                                  |
| Billing email                     | `billing@motionile.com`                                                                                                                                  |
| Grievance email                   | `grievance@motionile.com`                                                                                                                                |
| Legal email                       | `legal@motionile.com`                                                                                                                                    |
| Developer contact email           | `<OWNER_EMAIL>` on the company domain (not a personal Gmail; several platforms reject free-mail addresses)                                               |
| Category                          | Productivity / Education / Video creation (pick the closest each console offers)                                                                         |
| Legal entity, address, GSTIN      | Values from `siteConfig.legal` once filled in                                                                                                            |
| Short description (80 characters) | `Motionile turns any topic into a narrated, animated explainer video.`                                                                                   |
| Long description                  | See below                                                                                                                                                |

Long description (paste as is):

> Motionile turns a topic or a question into a short animated explainer video, from 10 seconds to 2 minutes, with natural narration. The user picks a topic or types a question, reviews and approves an AI-generated storyboard, and Motionile writes the narration, records it, animates each scene in time with the audio and renders an MP4 in 16:9, 9:16 and 1:1. When the video is ready, the user can publish it to the accounts they have connected, such as YouTube, LinkedIn, Instagram, Facebook Pages, Threads, X and TikTok, using each platform's official API, with a caption written for that platform. Motionile only posts content the user has created and explicitly chosen to publish, never posts on its own, and lets users disconnect any account at any time.

### App icon

Export one master image and derive the rest from it: the Motionile mark centred on the dark brand background, square, no transparency, no text other than the mark, 1024 × 1024 px PNG. Use the same artwork as `apps/web/src/app/icon.tsx`.

| Platform                      | What the upload dialog asks for (check it, these change)                                   |
| ----------------------------- | ------------------------------------------------------------------------------------------ |
| Google Auth Platform branding | Square 120 × 120 px, PNG, JPG or BMP, at most 1 MB; showing it triggers brand verification |
| GitHub OAuth app              | Square image; upload the 1024 px master                                                    |
| Microsoft Entra branding      | Square, at most 100 KB; 215 × 215 px works                                                 |
| Meta apps                     | Square 1024 × 1024 px (the dialog accepts 512–1024 px)                                     |
| LinkedIn apps                 | Square, at least 100 × 100 px                                                              |
| X app                         | Square PNG or JPG                                                                          |
| TikTok app                    | Square 1024 × 1024 px, JPG or PNG                                                          |
| WhatsApp business profile     | Square 640 × 640 px                                                                        |
| Cloudflare, Razorpay          | Razorpay Checkout uses a square logo of at least 256 × 256 px; Cloudflare needs none       |

## 3. Order of work

Start the items with the longest lead time first. Items marked "now" do not depend on any Motionile code.

| Week  | Action                                                                                                                                          |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| 1     | Section 1 prerequisites; Meta business verification and domain verification; Razorpay sign-up and KYC; SES production access; Turnstile widgets |
| 1     | Google Cloud projects, login OAuth clients and brand verification; GitHub OAuth apps; Microsoft Entra registrations and publisher verification  |
| 1–2   | WhatsApp phone number, display name and authentication template; LinkedIn apps and Community Management Development tier request                |
| 1–2   | X developer account and apps; TikTok developer apps (submit app review with the Phase 3 site); YouTube Google Cloud projects                    |
| Later | Demo-video reviews in section 10, after the relevant phase is deployed                                                                          |

## 4. Login providers

Needed by Phase 4 (auth backend). Demo flows exist from Phase 5 (auth frontend). Every login provider uses the minimal OpenID Connect scopes; Motionile only reads the identity once at sign-in and never calls the provider's API afterwards, so no refresh tokens and no `offline_access` are requested. Account linking happens only on a provider-verified email (`docs/context.md` section 7).

### 4.1 Google sign-in

Official pages: [Google Auth Platform](https://console.cloud.google.com/auth/overview), [brand verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/brand-verification), [submitting your app for verification](https://support.google.com/cloud/answer/13461325).

Use separate Google Cloud projects for sign-in and for YouTube publishing (section 8.1), so the YouTube sensitive-scope review never blocks sign-in and YouTube quota is not shared.

1. In the [Google Cloud console](https://console.cloud.google.com/projectcreate), create two projects under the company's organisation or billing account: `motionile-login-staging` and `motionile-login-production`.
2. In each project open [Google Auth Platform › Branding](https://console.cloud.google.com/auth/branding) and fill in:
   - App name: `Motionile` (production) or `Motionile Staging`.
   - User support email: `support@motionile.com` (it must be a Google account or a Google Group the project owner manages; create a Group if needed).
   - App logo: 120 × 120 px (optional; uploading it requires brand verification).
   - Application home page, privacy policy and terms of service: the URLs from section 2.
   - Authorized domains: `<PRODUCTION_DOMAIN>` (or `<STAGING_DOMAIN>`). This covers `api.<domain>`. The domain must be verified in Search Console by a project owner or editor.
   - Developer contact information: `<OWNER_EMAIL>`.
3. [Audience](https://console.cloud.google.com/auth/audience): user type External; publishing status In production (press "Publish app").
4. [Data access](https://console.cloud.google.com/auth/scopes): add only `openid`, `.../auth/userinfo.email` and `.../auth/userinfo.profile`. All three are non-sensitive, so no data-access review or demo video is needed.
5. [Clients](https://console.cloud.google.com/auth/clients) › Create client › Web application, name `motionile-web-<env>`:
   - Authorized JavaScript origins: none (the code exchange happens on the API).
   - Authorized redirect URIs: `https://api.<domain>/v1/auth/oauth/google/callback`.
   - Save the client ID and client secret to the password manager.
6. Submit for brand verification from [Verification Center](https://console.cloud.google.com/auth/verification) (production first; staging only if you uploaded a logo).

Reviewer requires: verified domain ownership, a home page that describes the app and links the privacy policy, a privacy policy on the same domain that describes Google user data use, and an app name and logo that do not impersonate Google.

Timeline: brand verification usually takes 2–3 business days.

Verify: Verification Center shows "Verified" for branding; signing in shows "Motionile" and the logo on the Google consent screen.

### 4.2 GitHub sign-in

Official pages: [creating an OAuth app](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app), [OAuth scopes](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps).

No review. GitHub OAuth apps accept one callback URL, so one app per environment is required anyway.

1. Create a GitHub organisation for the company if you have not, then open [organisation settings › Developer settings › OAuth apps](https://github.com/organizations/<GITHUB_ORG>/settings/applications) › New OAuth app. Owning the app in the organisation keeps it independent of any one person.
2. Fill in:
   - Application name: `Motionile` or `Motionile Staging`.
   - Homepage URL: `https://<domain>`.
   - Application description: the short description.
   - Authorization callback URL: `https://api.<domain>/v1/auth/oauth/github/callback`.
   - Enable Device Flow: off.
3. Register, then "Generate a new client secret". Save the client ID and secret.
4. Upload the logo.

Scope requested at runtime: `user:email` only. Without it the API cannot read the verified primary email from `GET /user/emails`, which account linking needs.

Verify: `https://github.com/login/oauth/authorize?client_id=<CLIENT_ID>&scope=user:email` shows the consent page with the Motionile name and logo.

### 4.3 Microsoft sign-in (Entra ID)

Official pages: [register an application](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app), [publisher verification](https://learn.microsoft.com/en-us/entra/identity-platform/publisher-verification-overview), [optional claims](https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims).

1. Sign in to the [Microsoft Entra admin center](https://entra.microsoft.com/) with a company work account (create a free Entra tenant if the company has none) and open Identity › Applications › [App registrations](https://entra.microsoft.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade) › New registration.
2. Fill in:
   - Name: `Motionile` or `Motionile Staging`.
   - Supported account types: "Accounts in any organizational directory (Any Microsoft Entra ID tenant - Multitenant) and personal Microsoft accounts (e.g. Skype, Xbox)".
   - Redirect URI: platform Web, `https://api.<domain>/v1/auth/oauth/microsoft/callback`.
3. Certificates & secrets › New client secret, description `motionile-<env>`, longest allowed expiry (24 months). Add a calendar reminder one month before expiry. Save the secret value immediately; it is shown once.
4. API permissions: Microsoft Graph delegated `openid`, `email`, `profile`. Remove `User.Read` if it was added by default; Motionile reads identity from the ID token only. Do not add `offline_access`.
5. Token configuration › Add optional claim › ID token: `email` and `xms_edov`. The `email` claim from Microsoft is not guaranteed to be verified; Phase 4 must link accounts only when `xms_edov` is true or the account is a personal Microsoft account.
6. Branding & properties: logo, home page, terms and privacy URLs from section 2, publisher domain `<domain>`.
7. Publisher verification (production app): join the free [Microsoft AI Cloud Partner Program](https://partner.microsoft.com/dashboard/account/v3/enrollment/introduction/partnership) to get a Partner ID, verify the company's email domain there, then in Branding & properties choose "Add Partner ID to verify publisher". Without it, many organisational tenants block users from consenting to an unverified multitenant app.

Publisher domain verification needs `https://<domain>/.well-known/microsoft-identity-association.json` served by the web app with the application ID. Raise this as a small Phase 4 web task; the portal shows the exact file contents.

Timeline: registration is immediate; Partner Program enrolment and email verification take a few days; publisher verification is immediate once the Partner ID is verified.

Verify: the consent screen shows "Motionile" with a blue verified badge; signing in with both a personal account (outlook.com) and a work account succeeds.

## 5. Messaging and bot protection

### 5.1 Meta business verification and domain verification

Needed by: WhatsApp OTP (Phase 4) and every Meta publishing permission (Phase 11). Start now; it blocks everything Meta.

Official pages: [business verification](https://www.facebook.com/business/help/2058515294227817), [domain verification](https://www.facebook.com/business/help/286768115176155).

1. In [Meta Business Suite settings](https://business.facebook.com/settings/), make sure the business portfolio name, legal name, address, phone and website match the company documents exactly.
2. Domain verification: Brand safety › [Domains](https://business.facebook.com/settings/owned-domains) › Add `<PRODUCTION_DOMAIN>` › choose DNS TXT verification, add the TXT record at the DNS provider, then press Verify. DNS is preferred because it needs no web app change.
3. Security Center › Start verification. Upload one document for legal name and one for address or phone. For an Indian private limited company, any of these is commonly accepted (Meta shows the current list for India in the form):
   - Legal name: Certificate of Incorporation, GST registration certificate, company PAN card.
   - Address or phone: GST certificate (shows the principal place of business), a utility bill (electricity, landline) in the company name dated within the last three months, or a business bank statement.
4. Choose a verification method for the contact (email on the company domain, phone call or SMS to the business number). Use the company domain email because the domain is verified.

Reviewer requires: documents in the exact legal name, legible, not expired, and an address that matches the portfolio. Rejections usually come from name mismatches or cropped scans.

Timeline: commonly 2 days to 2 weeks.

Verify: Security Center shows "Verified" next to the business, and the developer apps owned by the portfolio show "Business verification: Verified" in App Settings › Basic.

### 5.2 WhatsApp Cloud API for OTP

Needed by Phase 4 (OTP to phone numbers via the WhatsApp authentication template, `docs/context.md` section 7).

Official pages: [Cloud API get started](https://developers.facebook.com/documentation/business-messaging/whatsapp/get-started), [authentication templates](https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/authentication-templates/authentication-templates), [copy code templates](https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/authentication-templates/copy-code-button-authentication-templates), [display name guidelines](https://www.facebook.com/business/help/757569725593362), [messaging limits](https://developers.facebook.com/documentation/business-messaging/whatsapp/messaging-limits).

Use a dedicated Meta app for messaging, separate from the publishing apps, so its permissions and reviews stay independent. Staging and production may share one WhatsApp Business Account with two phone numbers, or use two accounts; one account with two numbers is simpler.

1. Get a phone number per environment that is not registered on the WhatsApp or WhatsApp Business app and can receive an SMS or voice call for verification. A landline works with voice verification.
2. Create the app at [developers.facebook.com/apps/creation](https://developers.facebook.com/apps/creation/): use case "Connect with customers through WhatsApp", app name `Motionile Messaging`, business portfolio = the verified company portfolio.
3. WhatsApp › API Setup › Add phone number. Enter:
   - Display name: `Motionile` (production) and `Motionile Staging` (staging). The name must match the brand on the website; the review compares it with `https://<domain>`.
   - Category: Education or Professional services.
   - Business description: the short description.
   - Website: `https://<domain>`; email `support@motionile.com`; profile picture 640 × 640 px.
4. Verify the number with the code, then register it for Cloud API with a two-step verification PIN; save the PIN in the password manager.
5. Create a system user in Business settings › Users › System users (role Admin), assign the app and the WhatsApp Business Account with full control, and generate a permanent token with `whatsapp_business_messaging` and `whatsapp_business_management`. Save the token, the phone number ID and the WhatsApp Business Account ID.
6. Create the authentication template in WhatsApp Manager › [Message templates](https://business.facebook.com/wa/manage/message-templates/) › Create template, or with the API:

```json
{
  "name": "motionile_otp",
  "language": "en",
  "category": "AUTHENTICATION",
  "message_send_ttl_seconds": 300,
  "components": [
    { "type": "BODY", "add_security_recommendation": true },
    { "type": "FOOTER", "code_expiration_minutes": 5 },
    {
      "type": "BUTTONS",
      "buttons": [{ "type": "OTP", "otp_type": "COPY_CODE", "text": "Copy code" }]
    }
  ]
}
```

Post it to `https://graph.facebook.com/<GRAPH_API_VERSION>/<WHATSAPP_BUSINESS_ACCOUNT_ID>/message_templates` with the system user token. Authentication templates use Meta's fixed wording, so the delivered message reads: "`<code>` is your verification code. For your security, do not share this code." with the footer "This code expires in 5 minutes." and a "Copy code" button. Five minutes and the 300-second time to live match the OTP lifetime in `docs/context.md` section 7. Add `en_US` or Hindi (`hi`) variants later if needed.

App Review is not required while the app sends only from the company's own WhatsApp Business Account; confirm on the app's App Review page, because Meta asks for Advanced Access when an app serves other businesses.

Timeline: display name review usually 1–2 days; authentication templates are usually approved within minutes to a day. Low messaging limits apply until business verification and display name approval are complete.

Verify: WhatsApp Manager shows the number as Connected with the display name Approved and quality rating High, and the template status Active. Send a test with the template to your own number from the API Setup page.

### 5.3 Cloudflare Turnstile

Needed now: staging and production refuse to start without `TURNSTILE_SECRET_KEY` (Phase 2 Turnstile verification, `docs/context.md` section 11).

Official pages: [Turnstile get started](https://developers.cloudflare.com/turnstile/get-started/), [widget modes](https://developers.cloudflare.com/turnstile/concepts/widget/), [testing keys](https://developers.cloudflare.com/turnstile/troubleshooting/testing/).

1. In the [Cloudflare dashboard](https://dash.cloudflare.com/?to=/:account/turnstile) › Turnstile › Add widget, once per environment:
   - Widget name: `motionile-staging` or `motionile-production`.
   - Hostnames: the host of the web origin only, `<STAGING_DOMAIN>` or `<PRODUCTION_DOMAIN>`. This must equal `TURNSTILE_EXPECTED_HOSTNAMES`, which OpenTofu writes from `web_origin`. `www` redirects to the apex and needs no entry.
   - Widget mode: Managed.
   - Pre-clearance: No.
2. Copy the site key and secret key.
3. Secret key: add `TURNSTILE_SECRET_KEY=<SECRET_KEY>` to `infra/parameters/<env>.env` and run `AWS_REGION=ap-south-1 infra/scripts/put-parameters.sh <env> infra/parameters/<env>.env`.
4. Site key: it is public. Keep it in the password manager entry; it goes into the Vercel environment variable `NEXT_PUBLIC_TURNSTILE_SITE_KEY` when the auth frontend adds the widget (Phase 5) and that variable is added to `apps/web/src/config/env-schema.ts`.
5. CI keeps Cloudflare's dummy keys (always-pass site key `1x00000000000000000000AA`, always-pass secret `1x0000000000000000000000000000000AA`); never put real keys in CI.

Timeline: immediate. Verify: the widget's analytics page shows solves once Phase 5 renders it; before that, `render-env.sh` no longer lists `TURNSTILE_SECRET_KEY` as missing.

## 6. Email: Amazon SES production access

Needed by Phase 4 (OTP and password reset to any address). New accounts start in the SES sandbox, which only sends to verified addresses. Production access is per AWS account and per region; request it in `ap-south-1` for every account that sends (staging and production, if they are separate accounts).

Official pages: [request production access](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html), [suppression list](https://docs.aws.amazon.com/ses/latest/dg/sending-email-suppression-list.html).

Prerequisites: the domain identity is verified (DKIM CNAMEs, MAIL FROM MX and SPF, DMARC from `tofu output -json dns_records`), and the website and legal pages are live.

1. Open [SES › Account dashboard in ap-south-1](https://ap-south-1.console.aws.amazon.com/ses/home?region=ap-south-1#/account) › Request production access, or run the CLI below.
2. Values:
   - Mail type: Transactional.
   - Website URL: `https://<PRODUCTION_DOMAIN>`.
   - Additional contacts: `<OWNER_EMAIL>`; language English.
   - Use case description:

> Motionile (https://<PRODUCTION_DOMAIN>) is an Indian web application that turns a topic into a narrated, animated explainer video. We use Amazon SES only for transactional email that a user triggers: one-time verification codes at registration and login, password reset links, receipts and billing notices for purchases, and notices that a video has finished rendering or publishing. We do not send marketing or bulk email, and we never send to purchased or scraped lists; every recipient is a user who entered the address in our sign-up form and proved control of it with a one-time code. We expect fewer than 1,000 messages per day at launch, growing gradually. Email is sent from no-reply@<PRODUCTION_DOMAIN> with Easy DKIM, a custom MAIL FROM domain (mail.<PRODUCTION_DOMAIN>), SPF and a DMARC policy. Every message uses a configuration set that requires TLS and publishes bounce, complaint, reject and rendering-failure events to an Amazon SNS topic. Our application processes those events: a hard bounce or a complaint marks the address as undeliverable and we stop sending to it, and the configuration set also adds bounced and complaining addresses to the SES account-level suppression list. Users can change their email address in account settings, and our privacy policy (https://<PRODUCTION_DOMAIN>/legal/privacy) explains how we use their data. We monitor bounce and complaint rates with CloudWatch alarms and keep them well below 5% and 0.1%.

CLI alternative (replace the placeholders, keep the text above in a file):

```sh
aws sesv2 put-account-details \
  --region ap-south-1 \
  --production-access-enabled \
  --mail-type TRANSACTIONAL \
  --website-url https://<PRODUCTION_DOMAIN> \
  --use-case-description file://ses-use-case.txt \
  --additional-contact-email-addresses <OWNER_EMAIL> \
  --contact-language EN
```

Timeline: AWS usually answers within 24 hours; answer follow-up questions in the support case quickly.

Verify: `aws sesv2 get-account --region ap-south-1 --query '{production:ProductionAccessEnabled,quota:SendQuota}'` returns `production: true` and a quota above 200 messages per day.

## 7. Payments: Razorpay

Needed by Phase 7 (credits and billing). Start KYC now because activation depends on documents and a website review.

Official pages: [account activation](https://razorpay.com/docs/payments/account-activation-support/?preferred-country=IN), [business types and KYC documents](https://razorpay.com/docs/payments/business-types-kyc-documents/?preferred-country=IN), [business website details](https://razorpay.com/docs/payments/dashboard/account-settings/business-website-details/?preferred-country=IN), [API keys](https://razorpay.com/docs/payments/dashboard/account-settings/api-keys/?preferred-country=IN), [webhooks](https://razorpay.com/docs/webhooks/?preferred-country=IN), [subscriptions](https://razorpay.com/docs/payments/subscriptions/?preferred-country=IN).

### 7.1 Website requirements

Razorpay's pages disagree on which policy pages are mandatory at onboarding (one India FAQ says policies are no longer required at onboarding, while the business-website page and the Payment Aggregator rules still expect them at website review). Have all of these live and linked from the footer before submitting:

| Requirement                                          | Motionile page                | Status to check                                                                                                                                 |
| ---------------------------------------------------- | ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Terms and conditions                                 | `/legal/terms`                | Live                                                                                                                                            |
| Privacy policy                                       | `/legal/privacy`              | Live                                                                                                                                            |
| Cancellation and refund policy with timelines        | `/legal/refund-policy`        | Live                                                                                                                                            |
| Contact us with registered address, phone and email  | `/contact`                    | Phone number missing; add it (section 1)                                                                                                        |
| Grievance officer name, designation, email and phone | `/contact` and `/legal/terms` | Name is a placeholder until `siteConfig.legal` is filled                                                                                        |
| Pricing in INR with product descriptions             | `/pricing`                    | Must show real INR prices and what each pack or plan includes before review                                                                     |
| Shipping or delivery policy                          | None yet                      | Add a short "Delivery" section or page: credits and videos are delivered digitally to the account immediately after payment, nothing is shipped |
| About us                                             | `/about`                      | Live                                                                                                                                            |
| Legal entity name and GSTIN on the site              | Footer, terms                 | Placeholders until filled                                                                                                                       |
| HTTPS and no "coming soon" or broken pages           | Whole site                    | Check with a crawler before submitting                                                                                                          |

### 7.2 Steps

1. Sign up at [dashboard.razorpay.com/signup](https://dashboard.razorpay.com/signup) with `billing@motionile.com` and the business phone.
2. Business type: Private Limited (or the company's actual constitution). Category: Software / SaaS (IT and software services). Description: the long description from section 2 plus "Customers buy prepaid credit packs and monthly subscriptions in INR; credits are spent to generate videos."
3. Upload KYC documents for a private limited company: Certificate of Incorporation, company PAN, GST certificate, Memorandum and Articles of Association, board resolution authorising the signatory, PAN and address proof of the authorised signatory and directors. Razorpay may also ask for a utility bill dated within three months.
4. Settlement account: a current account in the company's exact legal name; provide a cancelled cheque or bank statement showing account number, IFSC and name. Razorpay verifies it with a penny drop.
5. Website details: `https://<PRODUCTION_DOMAIN>` and the links in 7.1.
6. Test mode works immediately: Account & Settings › API keys › Generate test key. Staging always uses test keys.
7. After activation, switch to Live mode and generate live keys. Production only uses live keys.
8. Subscriptions: open Subscriptions in the dashboard; if live mode shows it as not enabled, raise a request from the dashboard support widget asking to enable Subscriptions for recurring card and UPI Autopay mandates. Plans are not created by hand: the admin console creates and links them (**Sync plan** on each subscription product, see [razorpay-setup.md](razorpay-setup.md#25-products-and-plans)).
9. Webhooks (Account & Settings › Webhooks), one per mode:
   - Test mode: `https://api.<STAGING_DOMAIN>/v1/webhooks/razorpay`.
   - Live mode: `https://api.<PRODUCTION_DOMAIN>/v1/webhooks/razorpay`.
   - Secret: `openssl rand -hex 32`, different per mode; save it.
   - Alert email: `billing@motionile.com`.
   - Events: `payment.captured`, `payment.failed`, `order.paid`, `subscription.authenticated`, `subscription.activated`, `subscription.charged`, `subscription.pending`, `subscription.halted`, `subscription.cancelled`, `subscription.completed`, `subscription.paused`, `subscription.resumed`, `subscription.updated`, `refund.created`, `refund.processed`, `refund.failed`.
   - Create each webhook after the API with the endpoint is deployed in that environment; Razorpay disables a webhook that keeps failing. Step by step, with the SSM upload and the verification, in [razorpay-setup.md](razorpay-setup.md).

Webhooks live under `/v1/webhooks/`, the prefix the API's Origin guard exempts (`CORS_ORIGIN_GUARD_EXEMPT_PREFIXES`), so the Razorpay endpoint is `/v1/webhooks/razorpay`. The URL can be edited in the dashboard at any time. The three values this section produces (key ID, key secret, webhook secret) go to SSM as `BILLING_RAZORPAY_KEY_ID`, `BILLING_RAZORPAY_KEY_SECRET` and `BILLING_RAZORPAY_WEBHOOK_SECRET`; rotate them with [secrets-rotation.md](secrets-rotation.md#9-razorpay-key-and-webhook-secret).

Timeline: KYC review typically takes 3–7 working days after complete documents; website review issues restart the clock.

Verify: the dashboard banner disappears, Live mode is selectable, live API keys can be generated and Settlements shows the bank account as verified.

## 8. Publishing platforms

Needed by Phase 11 (publishing connectors). Phase 3 creates the developer accounts and apps, completes business verification and submits every request that does not need a working flow. Reviews that need a screencast follow in section 10.

The staging app on every platform stays in development or testing mode with the team added as testers; only the production app goes through review. Reviewers need to see the app they are reviewing, so record demo videos against the production deployment with publishing enabled only for the reviewer test account (a feature flag), not against staging.

### 8.1 YouTube (Google)

Official pages: [YouTube Data API overview](https://developers.google.com/youtube/v3/getting-started), [quota and compliance audits](https://developers.google.com/youtube/v3/guides/quota_and_compliance_audits), [quota costs](https://developers.google.com/youtube/v3/determine_quota_cost), [videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert), [YouTube API Services Terms](https://developers.google.com/youtube/terms/api-services-terms-of-service), [Developer Policies](https://developers.google.com/youtube/terms/developer-policies), [sensitive scope verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification), [Audit and Quota Extension Form](https://support.google.com/youtube/contact/yt_api_form).

Scopes (minimal):

- `https://www.googleapis.com/auth/youtube.upload` to upload videos and set thumbnails.
- `https://www.googleapis.com/auth/youtube.readonly` to identify the connected channel (`channels.list?mine=true`) and to read upload processing status for `fetch_status` (`videos.list` with `status` and `processingDetails`), which `youtube.upload` does not allow.

Both are sensitive (not restricted), so verification needs a demo video but no third-party security assessment. Do not request `youtube` or `youtube.force-ssl`; they are broader than needed.

Quota: as of the June 2026 change, each project gets 100 `videos.insert` calls per day in a separate Video Uploads bucket (1 unit per call), 100 `search.list` calls, and 10,000 units per day for all other methods (`videos.list` and `channels.list` cost 1 unit each). Quota belongs to the project, so every Motionile user shares the 100 uploads a day. More quota requires the compliance audit. Google has changed these numbers twice since December 2025; check the quota cost page before planning capacity.

Unverified projects: historically, videos uploaded by unaudited API projects created after 28 July 2020 were locked to private. The current `videos.insert` page no longer shows that notice clearly; treat public uploads as requiring the audit until a test from the production project proves otherwise.

1. Create projects `motionile-youtube-staging` and `motionile-youtube-production` and enable YouTube Data API v3 in each ([API library](https://console.cloud.google.com/apis/library/youtube.googleapis.com)).
2. Branding, audience and authorized domains exactly as in 4.1, with app name `Motionile`. Staging can stay in Testing with up to 100 test users (refresh tokens of testing apps with sensitive scopes expire after 7 days, which is acceptable for staging).
3. Data access: add the two scopes above.
4. Client: Web application, redirect URI `https://api.<domain>/v1/publishing/oauth/youtube/callback`.
5. Before submitting, make the legal pages satisfy the YouTube Developer Policies; the audit checks them:
   - The privacy policy must say Motionile uses YouTube API Services, link the [Google Privacy Policy](https://policies.google.com/privacy), explain what YouTube data is accessed, stored and shared, and explain how to revoke access through [Google security settings](https://myaccount.google.com/connections).
   - The terms must tell users that by connecting YouTube they agree to the [YouTube Terms of Service](https://www.youtube.com/t/terms).
   - Phase 11 must delete stored YouTube data within the policy's limits after revocation. These additions are a web task for whoever owns the legal pages.
6. Phase 3: submit brand verification for the production project.
7. After Phase 11 is deployed: submit data-access verification with the scope justifications in section 9 and the demo video in section 10.
8. After data-access verification: submit the [Audit and Quota Extension Form](https://support.google.com/youtube/contact/yt_api_form) for the production project. It asks for the organisation, project number, the API client's purpose and user flow, links to the site and legal pages, screenshots or a video of every screen that uses YouTube data, expected upload volume and the requested quota. Ask for a modest increase (for example 500 uploads per day) with a usage forecast.

Timeline: sensitive-scope verification is usually a few business days to a few weeks; the compliance audit has no published turnaround and commonly takes several weeks with follow-up questions.

Verify: Verification Center shows Data access "Verified"; the Google Cloud console [quotas page](https://console.cloud.google.com/apis/api/youtube.googleapis.com/quotas) shows the increased limits; the audit team confirms by email.

### 8.2 Meta: Facebook Pages and Instagram

Official pages: [app creation](https://developers.facebook.com/apps/creation/), [App Review](https://developers.facebook.com/documentation/resp-plat-initiatives/individual-processes/app-review), [Instagram content publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing), [Instagram App Review](https://developers.facebook.com/documentation/instagram-platform/app-review), [Instagram Platform overview](https://developers.facebook.com/documentation/instagram-platform/overview), [permissions reference](https://developers.facebook.com/docs/permissions/), [data deletion callback](https://developers.facebook.com/docs/development/create-an-app/app-dashboard/data-deletion-callback).

Recommended design: one Meta app `Motionile` (staging: `Motionile Staging`) that uses Facebook Login for Business for both Facebook Pages and Instagram (Instagram API with Facebook Login), so the user connects once and one review covers both. Meta's Instagram API with Instagram Login is the alternative; it supports Instagram professional accounts without a linked Facebook Page but cannot be combined with Facebook Login in the same app for Instagram. That choice is an owner decision (see the final note).

Permissions (Advanced Access, because Motionile serves many businesses):

| Permission                  | Why                                                                                                                         |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `pages_show_list`           | List the Pages the user manages so they can pick one, and find the Instagram account linked to it                           |
| `pages_read_engagement`     | Read Page metadata and the Page access token; required by both Page video publishing and Instagram publishing               |
| `pages_manage_posts`        | Publish videos and reels to the chosen Facebook Page                                                                        |
| `instagram_basic`           | Read the Instagram professional account ID, username and profile picture                                                    |
| `instagram_content_publish` | Create and publish Reels on the user's Instagram professional account                                                       |
| `business_management`       | Only if testing shows Pages owned through a business portfolio are missing from `pages_show_list`; otherwise do not request |

1. Create the app: type Business, business portfolio = verified company portfolio, use cases "Manage everything on your Page" and "Manage messaging & content on Instagram" (Facebook Login for Business).
2. App Settings › Basic: display name, contact email `support@motionile.com`, privacy URL, terms URL, app icon 1024 px, category, app domains `<domain>`, and "User data deletion": choose "Data deletion instructions URL" = `https://<domain>/legal/data-deletion` now. Phase 11 replaces it with a data deletion callback URL when the callback endpoint exists.
3. Facebook Login for Business › Settings: Valid OAuth Redirect URIs `https://api.<domain>/v1/publishing/oauth/facebook/callback` and `https://api.<domain>/v1/publishing/oauth/instagram/callback`; Enforce HTTPS on; Use Strict Mode for redirect URIs on.
4. Create a Facebook Login for Business configuration with the permissions above and token type User access token.
5. App Roles: add the team as developers and testers; create a test Facebook Page and link a test Instagram professional account for the reviewer.
6. Phase 3: complete business verification (5.1) and App Settings; leave the app in Development mode.
7. After Phase 11: App Review › Permissions and features › request Advanced Access for each permission, with the justification from section 9, step-by-step reviewer instructions, test credentials, and a screencast per permission (section 10). Then switch the app to Live.

Reviewer requires: business verification, a working privacy policy URL, a data deletion URL or callback, an app icon, a screencast for every permission showing the Meta login, the permission being granted and the exact feature that uses it, and test credentials that work.

Timeline: App Review is often 3–10 days per submission; rejections are common on the first try, usually for an unclear screencast.

Verify: App Review › Permissions and features shows each permission with "Advanced access"; App Mode is Live; a non-tester account can connect and publish.

Annual: Meta's Data Use Checkup must be completed every year or the permissions are removed.

### 8.3 Meta: Threads

Official pages: [Threads API get started](https://developers.facebook.com/documentation/threads/get-started), [Threads use case](https://developers.facebook.com/documentation/development/create-an-app/threads-use-case).

Create a separate Meta app `Motionile Threads` (staging `Motionile Threads Staging`) with the use case "Access the Threads API"; Meta does not let the Threads use case share an app with other use cases in most configurations.

1. Permissions: `threads_basic` (identify the connected Threads profile) and `threads_content_publish` (publish the video post).
2. Threads use case settings: Redirect callback URL `https://api.<domain>/v1/publishing/oauth/threads/callback`. Uninstall and delete callback URLs are required; Phase 11 owns the endpoints. If the console requires them before Phase 11, use `https://api.<domain>/v1/publishing/callbacks/threads/uninstall` and `https://api.<domain>/v1/publishing/callbacks/threads/delete` and record that Phase 11 must implement exactly these paths.
3. App Settings › Basic as in 8.2.
4. Add Threads testers (the tester accepts the invitation in the Threads app under Settings › Account › Website permissions).
5. After Phase 11: App Review for both permissions with a screencast; then publish the app.

Timeline and verification as in 8.2.

### 8.4 LinkedIn

Official pages: [create an app](https://www.linkedin.com/developers/apps/new), [Share on LinkedIn](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/share-on-linkedin), [Sign In with LinkedIn using OpenID Connect](https://learn.microsoft.com/en-us/linkedin/consumer/integrations/self-serve/sign-in-with-linkedin-v2), [Increasing access](https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access), [Community Management overview](https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview), [Community Management app review](https://learn.microsoft.com/en-us/linkedin/marketing/community-management-app-review).

LinkedIn requires the Community Management API to be requested on a new app that has no other products, so Motionile needs two LinkedIn apps per environment.

App A, personal profiles (self-serve, no vetting):

1. Create the app at [linkedin.com/developers/apps/new](https://www.linkedin.com/developers/apps/new): name `Motionile`, LinkedIn Page = the Motionile Company Page, privacy policy URL, logo. A Page admin must verify the association from the Settings tab.
2. Products: add "Share on LinkedIn" (`w_member_social`) and "Sign In with LinkedIn using OpenID Connect" (`openid`, `profile`), which the connector needs to read the member ID used as the post author. Both are granted instantly.
3. Auth tab: redirect URL `https://api.<domain>/v1/publishing/oauth/linkedin/callback`.

App B, organisation Pages (vetted):

1. Create a second app `Motionile Pages` associated with the same Company Page, with no other products.
2. Products › Community Management API › Request access. The form asks for the legal entity, registered address, a company email on the company domain, website, the use case and the permissions. Request the Development tier with: `w_organization_social` (post on Pages the member administers), `r_organization_social` (read those posts back to confirm status), `rw_organization_admin` (list the Pages the member administers so they can pick one; confirm in the form that this is the narrowest permission LinkedIn offers for listing administered organisations).
3. Auth tab: redirect URL `https://api.<domain>/v1/publishing/oauth/linkedin/callback` as well; the connector tells the two apps apart through the OAuth `state`.
4. After Phase 11, request the Standard tier from My Apps › Products: it needs a screen recording of each use case and test credentials. Development tier access must be used and the integration completed within 12 months.

Reviewer requires: a registered legal entity (individuals are rejected), a verified Company Page, a business email, a website describing the product, and for Standard tier a recording that matches the use cases in the form.

Timeline: Development tier vetting usually takes days to a few weeks; Standard tier review several weeks.

Verify: the Products tab lists "Community Management API" with "Development tier" and later "Standard tier"; the Auth tab lists the granted scopes.

### 8.5 X

Official pages: [X Developer Console](https://developer.x.com/), [pricing](https://docs.x.com/x-api/getting-started/pricing), [OAuth 2.0 authorization code with PKCE](https://docs.x.com/resources/fundamentals/authentication/oauth-2-0/authorization-code), [create post](https://docs.x.com/x-api/posts/create-post), [chunked media upload](https://docs.x.com/x-api/media/quickstart/media-upload-chunked), [rate limits](https://docs.x.com/x-api/fundamentals/rate-limits).

Access tier: X moved every new developer to pay-per-use in February 2026; the Free, Basic and Pro subscriptions are no longer available to new sign-ups (legacy Basic and Pro subscribers were migrated in June and September 2026). Pay-per-use supports post creation and v2 chunked media upload. Recommendation: pay-per-use with prepaid credits and a monthly spend cap, because Motionile only writes posts and reads almost nothing, and Enterprise is priced for data buyers.

Cost at the 2026-10-14 rate card: `Post: Create` $0.015 per request, but $0.20 when the post contains a URL. Phase 11 should keep links out of X captions (or accept the higher price); media upload has no separate line on the rate card, so check the console's usage page after the first test. Prices change often; read the pricing page before budgeting.

1. Sign up at [developer.x.com](https://developer.x.com/) with the company's `@motionile` X account and accept the developer agreement. Describe the use case:

> Motionile is a web app that turns a topic into a short narrated explainer video. Users connect their own X account with OAuth 2.0 and choose to publish a finished video to it with a caption they review. Motionile uploads the video with the v2 media upload endpoints and creates one post per explicit user action. We do not read timelines, search, follow, like, send direct messages, or post automatically, and we do not analyse or resell X data.

2. Buy a small credit balance and set a spend cap.
3. Create one app per environment (`Motionile`, `Motionile Staging`) and open User authentication settings:
   - App permissions: Read and write.
   - Type of app: Web App, Automated App or Bot (confidential client).
   - Callback URI: `https://api.<domain>/v1/publishing/oauth/x/callback`.
   - Website URL, terms and privacy URLs from section 2; organisation name `Motionile`.
4. Save the OAuth 2.0 client ID and client secret.

Scopes at runtime: `tweet.read`, `tweet.write`, `users.read` (all three are required by `POST /2/tweets`), `media.write` (v2 media upload) and `offline.access` (refresh token, so scheduled and retried publishes work after the two-hour access token expires).

Timeline: immediate; there is no app review. Verify: the app's Keys and tokens page shows the OAuth 2.0 client, and a test post with a video from a tester account succeeds and appears in the usage dashboard.

### 8.6 TikTok

Official pages: [TikTok for Developers apps](https://developers.tiktok.com/apps), [Content Posting API get started](https://developers.tiktok.com/doc/content-posting-api-get-started), [Direct Post reference](https://developers.tiktok.com/doc/content-posting-api-reference-direct-post), [content sharing guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines), [app review guidelines](https://developers.tiktok.com/doc/app-review-guidelines).

Content posted by an unaudited client is restricted to private (`SELF_ONLY`) viewing, and unaudited clients are also limited in how many users can post per day (third-party reports say 5 users per 24 hours; read the sharing guidelines for the current number). Public posting needs two separate approvals: app review, then the Direct Post audit.

1. Register at [developers.tiktok.com](https://developers.tiktok.com/) with the company account and create an organisation `Motionile`.
2. Create one app per environment. App details:
   - Icon 1024 px, name `Motionile`, category Productivity or Education, the short and long descriptions.
   - Terms of Service URL and Privacy Policy URL from section 2.
   - Platform: Web, website URL `https://<domain>`. TikTok reviews the site; it must be live and match the app name.
3. Products: Login Kit (redirect URI `https://api.<domain>/v1/publishing/oauth/tiktok/callback`) and Content Posting API with Direct Post enabled.
4. Scopes: `user.info.basic` (show the creator's nickname and avatar, required by the posting UX guidelines) and `video.publish` (Direct Post). Do not request `video.upload`; it sends drafts to the TikTok inbox, which Motionile does not use.
5. Upload method: use `FILE_UPLOAD` from the worker. `PULL_FROM_URL` would require verifying `cdn.<domain>` as a URL prefix in the app; skip it unless Phase 11 needs it.
6. Use the sandbox for staging; it needs no review.
7. Submit the production app for review after Phase 11 with a demo video (section 10). TikTok rejects demos that are not recorded on the registered website domain.
8. After the app is approved, submit the Direct Post audit from the app's Content Posting API page. The audit checks that the posting screen follows the content sharing guidelines: it shows the creator's TikTok nickname and avatar from `creator_info`, lets the user pick the privacy level from the allowed options with no default, shows the comment, duet and stitch toggles allowed for the creator, offers the commercial content disclosure toggles, shows the music usage and branded content declarations, previews the video, and posts only after an explicit user action. Phase 11 must build the TikTok publish screen to match these points.

Timeline: app review commonly takes several days to two weeks; the Direct Post audit commonly takes several weeks and is often rejected on the first attempt for UX gaps.

Verify: the app shows Live in production; the Content Posting API product shows the audit as passed; a post from a non-team account with privacy "Everyone" is publicly visible.

## 9. Scope justifications to paste

Each text is written for the reviewer's "How will your app use this permission?" field. Replace `<domain>` before pasting.

| Platform  | Permission                                     | Justification                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| --------- | ---------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Google    | `openid`, `userinfo.email`, `userinfo.profile` | Motionile offers "Sign in with Google". We read the user's Google account ID, verified email address, name and profile picture once at sign-in to create or find their Motionile account. We do not call any other Google API with this client.                                                                                                                                                                                                                         |
| GitHub    | `user:email`                                   | Motionile offers "Sign in with GitHub". We read the user's verified primary email address once at sign-in to create or link their Motionile account. We do not access repositories or any other data.                                                                                                                                                                                                                                                                   |
| Microsoft | `openid`, `email`, `profile`                   | Motionile offers "Sign in with Microsoft". We read the user's account ID, email address and name from the ID token at sign-in to create or find their Motionile account. We do not call Microsoft Graph and do not request offline access.                                                                                                                                                                                                                              |
| YouTube   | `youtube.upload`                               | Motionile creates short explainer videos for the user. When the user clicks "Publish to YouTube" on a finished video and confirms the title, description, privacy status and thumbnail, Motionile uploads that one video to the user's channel with videos.insert and sets the thumbnail with thumbnails.set. We never upload without an explicit user action, and we cannot delete or edit other videos, which is why the narrower upload scope is enough for posting. |
| YouTube   | `youtube.readonly`                             | After the user connects YouTube, we call channels.list (mine=true) to show which channel is connected so they can confirm it before publishing. After an upload we call videos.list for that video only, to show the user whether YouTube has finished processing it and to get its public link. youtube.upload does not allow these read calls, and we read no other channel data, playlists or analytics.                                                             |
| Meta      | `pages_show_list`                              | When a user connects Facebook, Motionile lists the Pages they manage so they can choose which Page receives their videos, and finds the Instagram professional account linked to that Page. We store only the selected Page's ID and name.                                                                                                                                                                                                                              |
| Meta      | `pages_read_engagement`                        | Required to obtain the Page access token and Page metadata (name, picture, linked Instagram account) for the Page the user selected, so we can publish their video there and show them the published post's link. We do not read followers, comments or insights.                                                                                                                                                                                                       |
| Meta      | `pages_manage_posts`                           | When the user clicks "Publish to Facebook" on a finished video and reviews the caption, Motionile uploads the video as a post or reel on the Page they selected. We only post content the user created in Motionile and explicitly chose to publish.                                                                                                                                                                                                                    |
| Meta      | `instagram_basic`                              | We read the connected Instagram professional account's ID, username and profile picture so the user can confirm which account will receive the reel, and to address the content publishing endpoints.                                                                                                                                                                                                                                                                   |
| Meta      | `instagram_content_publish`                    | When the user clicks "Publish to Instagram" on a finished 9:16 video and reviews the caption, Motionile creates a Reels media container and publishes it to their Instagram professional account, then shows the user the permalink. One publish per user action.                                                                                                                                                                                                       |
| Meta      | `business_management` (only if requested)      | Some users manage their Page through a business portfolio, and their Pages are returned only with this permission. We use it solely to list those Pages for selection; we do not read or change any other business assets.                                                                                                                                                                                                                                              |
| Threads   | `threads_basic`                                | We read the connected Threads profile's ID, username and picture so the user can confirm which profile will receive the post.                                                                                                                                                                                                                                                                                                                                           |
| Threads   | `threads_content_publish`                      | When the user clicks "Publish to Threads" on a finished video and reviews the caption, Motionile creates a video container and publishes one post to their Threads profile, then shows the link.                                                                                                                                                                                                                                                                        |
| LinkedIn  | `openid`, `profile`                            | We read the member's ID and name to show which LinkedIn account is connected and to set the member as the author of the post they publish.                                                                                                                                                                                                                                                                                                                              |
| LinkedIn  | `w_member_social`                              | When the member clicks "Publish to LinkedIn" on a finished video and reviews the text, Motionile uploads the video and creates one post on their own profile.                                                                                                                                                                                                                                                                                                           |
| LinkedIn  | `rw_organization_admin`                        | Used only to list the LinkedIn Pages on which the member has an administrator role, so they can choose the Page that receives their video. We do not change Page settings or roles.                                                                                                                                                                                                                                                                                     |
| LinkedIn  | `w_organization_social`                        | When a Page administrator clicks "Publish to LinkedIn Page" on a finished video and reviews the text, Motionile uploads the video and creates one post as that Page.                                                                                                                                                                                                                                                                                                    |
| LinkedIn  | `r_organization_social`                        | After publishing, we read back the post we created to confirm it was published and to show the administrator its link and status.                                                                                                                                                                                                                                                                                                                                       |
| X         | `tweet.read`, `users.read`                     | Required by X for creating posts; we read the connected account's username to show which account is connected and read back the post we created to give the user its link.                                                                                                                                                                                                                                                                                              |
| X         | `tweet.write`                                  | When the user clicks "Publish to X" on a finished video and reviews the text, Motionile creates one post with the uploaded video.                                                                                                                                                                                                                                                                                                                                       |
| X         | `media.write`                                  | Upload the user's finished video with the v2 chunked media upload before creating the post.                                                                                                                                                                                                                                                                                                                                                                             |
| X         | `offline.access`                               | Keep the connection working after the two-hour access token expires, so a publish the user started still completes when a retry runs later. Users can disconnect at any time, which revokes the token.                                                                                                                                                                                                                                                                  |
| TikTok    | `user.info.basic`                              | Show the creator's TikTok nickname and avatar on the posting screen, as the Content Sharing Guidelines require, so they know which account will receive the video.                                                                                                                                                                                                                                                                                                      |
| TikTok    | `video.publish`                                | When the creator reviews the caption, chooses the privacy level and interaction settings, and clicks "Post to TikTok", Motionile uploads that video with Direct Post. One post per explicit user action; nothing is posted automatically.                                                                                                                                                                                                                               |

## 10. Reviews that need a demo video

These reviews cannot be finished in Phase 3, because the flow they show does not exist yet. Phase 3 submits everything else (business verification, accounts, apps, brand verification, LinkedIn Development tier) and records the planned dates in the tracking table.

| Review                                         | Earliest phase                          | What the video must show                                                                                                                                                                                                                                                                                                                     |
| ---------------------------------------------- | --------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Google sign-in brand verification              | None needed                             | No video for non-sensitive scopes. Google may ask for one if it doubts the branding; record the Phase 5 sign-in flow then.                                                                                                                                                                                                                   |
| Microsoft publisher verification               | None needed                             | No video.                                                                                                                                                                                                                                                                                                                                    |
| YouTube sensitive scopes (Google verification) | After Phase 11 (publishing) is deployed | In English: the Motionile sign-in, clicking Connect YouTube, the Google consent screen with "Motionile" and the OAuth client ID visible in the address bar, granting both scopes, the connected channel name (readonly), publishing a finished video (upload), and the processing status and link (readonly). Upload to YouTube as Unlisted. |
| YouTube compliance audit                       | After Phase 11 and data-access approval | Every screen that uses YouTube data, the disconnect flow, and the privacy policy section about YouTube API Services; screenshots are accepted when asked.                                                                                                                                                                                    |
| Meta App Review (Pages and Instagram)          | After Phase 11                          | One screencast per permission: logging in to Motionile, connecting Facebook, the Meta permission dialog, selecting the Page, then publishing a video to the Page and a Reel to Instagram, ending on the live post. Show captions and the English UI.                                                                                         |
| Meta App Review (Threads)                      | After Phase 11                          | Connecting Threads, the permission dialog, the connected profile, publishing a video post and the live post.                                                                                                                                                                                                                                 |
| LinkedIn Community Management Standard tier    | After Phase 11                          | Each use case in the form: connecting LinkedIn, choosing an administered Page, publishing a video to the Page, and the status read-back.                                                                                                                                                                                                     |
| TikTok app review                              | After Phase 11                          | Recorded on `https://<PRODUCTION_DOMAIN>`: TikTok login, the posting screen with creator info, privacy picker, interaction toggles and disclosures, posting, and the result.                                                                                                                                                                 |
| TikTok Direct Post audit                       | After TikTok app approval               | The same flow in more detail; the audit form also asks for the post IDs of test posts.                                                                                                                                                                                                                                                       |
| WhatsApp, Razorpay, SES, X, GitHub, Turnstile  | None needed                             | No video.                                                                                                                                                                                                                                                                                                                                    |

Sign-in demos depend on Phase 4 (auth backend) and Phase 5 (auth frontend); publishing demos depend on Phase 11 (publishing connectors) and a rendered video from Phases 8 and 9.

## 11. Where credentials go

| Credential                                                  | Until its phase lands | Destination once the code reads it                                                                                                                                                                         |
| ----------------------------------------------------------- | --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Turnstile secret key                                        | Now                   | SSM `/motionile/<env>/TURNSTILE_SECRET_KEY` via `infra/scripts/put-parameters.sh`                                                                                                                          |
| Turnstile site key                                          | Password manager      | Vercel `NEXT_PUBLIC_TURNSTILE_SITE_KEY` (Phase 5)                                                                                                                                                          |
| Google, GitHub, Microsoft client IDs and secrets            | Password manager      | SSM SecureString parameters added to `deploy/parameters.csv` in Phase 4                                                                                                                                    |
| WhatsApp token, phone number ID, business account ID        | Password manager      | SSM parameters added in Phase 4                                                                                                                                                                            |
| Razorpay key ID, key secret, webhook secret (test and live) | Password manager      | SSM `/motionile/<env>/BILLING_RAZORPAY_KEY_ID`, `BILLING_RAZORPAY_KEY_SECRET` and `BILLING_RAZORPAY_WEBHOOK_SECRET` via `infra/scripts/put-parameters.sh`; test keys for staging, live keys for production |
| Publishing client IDs and secrets (all platforms)           | Password manager      | SSM parameters added in Phase 11                                                                                                                                                                           |

Every new owner parameter must be added to `deploy/parameters.csv` and to `Settings.deployment_problems()` in the phase that introduces it.

## 12. Tracking table

Fill in one row per environment where the item is per environment. Status values: Not started, Submitted, Changes requested, Approved, Blocked.

| Item                                             | Environment | Owner action                                                       | Needed by phase | Submitted on | Status      | Approved on |
| ------------------------------------------------ | ----------- | ------------------------------------------------------------------ | --------------- | ------------ | ----------- | ----------- |
| Legal placeholders, phone, delivery policy       | Both        | Fill `siteConfig.legal`, add phone and delivery section, deploy    | 3               |              | Not started |             |
| Search Console domain verification               | Both        | Add DNS TXT, verify                                                | 3               |              | Not started |             |
| Meta domain verification                         | Production  | Add DNS TXT in Business settings                                   | 3               |              | Not started |             |
| Meta business verification                       | Production  | Upload documents in Security Center                                | 3               |              | Not started |             |
| Cloudflare Turnstile widget                      | Staging     | Create widget, upload secret to SSM                                | 3               |              | Not started |             |
| Cloudflare Turnstile widget                      | Production  | Create widget, upload secret to SSM                                | 3               |              | Not started |             |
| SES production access                            | Production  | Submit request in ap-south-1                                       | 4               |              | Not started |             |
| SES production access (if separate account)      | Staging     | Submit request in ap-south-1                                       | 4               |              | Not started |             |
| Google sign-in client and brand verification     | Staging     | Create project and client                                          | 4               |              | Not started |             |
| Google sign-in client and brand verification     | Production  | Create project and client, submit branding                         | 4               |              | Not started |             |
| GitHub OAuth app                                 | Staging     | Register app                                                       | 4               |              | Not started |             |
| GitHub OAuth app                                 | Production  | Register app                                                       | 4               |              | Not started |             |
| Microsoft Entra app                              | Staging     | Register app                                                       | 4               |              | Not started |             |
| Microsoft Entra app and publisher verification   | Production  | Register app, Partner ID, verify publisher                         | 4               |              | Not started |             |
| WhatsApp number and display name                 | Staging     | Add number, submit display name                                    | 4               |              | Not started |             |
| WhatsApp number and display name                 | Production  | Add number, submit display name                                    | 4               |              | Not started |             |
| WhatsApp `motionile_otp` template                | Both        | Create AUTHENTICATION template                                     | 4               |              | Not started |             |
| Razorpay account and KYC                         | Production  | Sign up, upload KYC, bank account, website details                 | 7               |              | Not started |             |
| Razorpay Subscriptions enablement                | Production  | Request enablement in live mode                                    | 7               |              | Not started |             |
| Razorpay webhooks                                | Both        | Create test and live webhooks with the 16 events (razorpay-setup)  | 7               |              | Not started |             |
| YouTube projects and clients                     | Both        | Create projects, enable API, create clients                        | 11              |              | Not started |             |
| YouTube brand verification                       | Production  | Submit branding                                                    | 11              |              | Not started |             |
| YouTube sensitive scope verification             | Production  | Submit with demo video                                             | 11              |              | Not started |             |
| YouTube audit and quota extension                | Production  | Submit the audit form                                              | 11              |              | Not started |             |
| Meta app (Pages and Instagram)                   | Staging     | Create app, add testers                                            | 11              |              | Not started |             |
| Meta app (Pages and Instagram) App Review        | Production  | Create app now; submit permissions with screencasts after Phase 11 | 11              |              | Not started |             |
| Meta Threads app                                 | Staging     | Create app, add testers                                            | 11              |              | Not started |             |
| Meta Threads app App Review                      | Production  | Create app now; submit after Phase 11                              | 11              |              | Not started |             |
| LinkedIn app A (Share on LinkedIn)               | Both        | Create app, add products                                           | 11              |              | Not started |             |
| LinkedIn app B Community Management, Development | Production  | Create app, request Development tier                               | 11              |              | Not started |             |
| LinkedIn app B Community Management, Standard    | Production  | Request Standard tier with recording                               | 11              |              | Not started |             |
| X developer account, credits and apps            | Both        | Sign up, set spend cap, create apps                                | 11              |              | Not started |             |
| TikTok apps                                      | Both        | Create apps, configure products                                    | 11              |              | Not started |             |
| TikTok app review                                | Production  | Submit with demo video                                             | 11              |              | Not started |             |
| TikTok Direct Post audit                         | Production  | Submit after app approval                                          | 11              |              | Not started |             |

## Decisions for the owner

1. Instagram connection method: Facebook Login for Business (recommended here: one app and one review for Facebook Pages and Instagram, but the user's Instagram professional account must be linked to a Facebook Page) or Instagram Login (no Page needed, better for solo creators, but a separate app and review).
2. Whether to request `business_management` up front (fewer review rounds) or only if testing shows missing Pages (smaller permission set, which Meta prefers).
3. X links: keep URLs out of X captions to stay at $0.015 per post, or accept $0.20 per post with a link.
4. The production domain, which every application above embeds; changing it later means re-verifying domains and re-submitting several reviews.
