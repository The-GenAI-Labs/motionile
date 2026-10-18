# Razorpay setup

How to connect an environment to Razorpay: API keys, the webhook, dashboard settings, plans, a full test-mode verification and the go-live checklist. Staging always uses Razorpay test mode and production always uses live mode. For how billing works, see [billing.md](../billing.md); for day-to-day operations, see [billing-operations.md](billing-operations.md).

The account itself (sign-up, KYC documents, bank account, website review) is covered in [platform-applications.md](platform-applications.md#7-payments-razorpay). Start that KYC early; it takes days.

Razorpay's dashboard changes labels often. Where this page and the console disagree, follow the console and update this file. Official references: [API keys](https://razorpay.com/docs/payments/dashboard/account-settings/api-keys/?preferred-country=IN), [webhooks](https://razorpay.com/docs/webhooks/?preferred-country=IN), [subscriptions](https://razorpay.com/docs/payments/subscriptions/?preferred-country=IN), [test card details](https://razorpay.com/docs/payments/payments/test-card-details/?preferred-country=IN).

Placeholders:

| Placeholder        | Meaning                                                                      |
| ------------------ | ---------------------------------------------------------------------------- |
| `<ENV>`            | `staging` or `production`                                                    |
| `<MODE>`           | `Test` for staging, `Live` for production                                    |
| `<API_DOMAIN>`     | `api.<STAGING_DOMAIN>` for staging, `api.<PRODUCTION_DOMAIN>` for production |
| `<KEY_ID>`         | Razorpay key ID: `rzp_test_...` or `rzp_live_...`                            |
| `<KEY_SECRET>`     | The matching key secret                                                      |
| `<WEBHOOK_SECRET>` | The secret you choose for the webhook of this mode                           |

## 1. What goes where

| Value          | Environment variable / SSM parameter | Source in `deploy/parameters.csv` | Used for                                                                                  |
| -------------- | ------------------------------------ | --------------------------------- | ----------------------------------------------------------------------------------------- |
| Key ID         | `BILLING_RAZORPAY_KEY_ID`            | `owner`                           | Basic auth to the Razorpay API; sent to Checkout so the browser opens the right account   |
| Key secret     | `BILLING_RAZORPAY_KEY_SECRET`        | `owner`                           | Basic auth to the Razorpay API; verifies the Checkout payment and subscription signatures |
| Webhook secret | `BILLING_RAZORPAY_WEBHOOK_SECRET`    | `owner`                           | Verifies `X-Razorpay-Signature` on every webhook body                                     |

All three are required in staging and production: the API and workers refuse to start without them. They are SecureString parameters under `/motionile/<ENV>/`, uploaded with `infra/scripts/put-parameters.sh`, never committed, never placed in OpenTofu and never printed. The web app needs no Razorpay value: the API returns the key ID with the checkout data.

Rules that prevent the usual mistakes:

- The key ID and key secret must be from the same mode, and the webhook secret must belong to the webhook of that same mode. A test key with a live webhook secret fails silently: every webhook is rejected with `401 invalid_webhook_signature`.
- The webhook secret is not the key secret. Choose a fresh random value for each webhook.
- Staging uses test keys, production uses live keys. Plans and customers do not exist across modes, so the two databases never share Razorpay IDs.
- Optional tuning variables (`BILLING_ORDER_EXPIRY_SECONDS` and so on) are listed in [billing.md](../billing.md#9-settings-and-runtime-flags). Leave them at their defaults.

## 2. Staging: test mode

### 2.1 Generate test API keys

1. Sign in at [dashboard.razorpay.com](https://dashboard.razorpay.com) and switch the mode toggle to **Test Mode**.
2. Open **Account & Settings** and then **API keys**, choose **Generate Test Key**.
3. Copy the key ID and the key secret into the password manager under `Motionile / Razorpay / staging`. The secret is shown once; if you lose it, regenerate the key (this invalidates the old one).

Expected result: a key ID starting with `rzp_test_`.

### 2.2 Create the test webhook

1. Generate the webhook secret on your machine and store it in the password manager:

   ```bash
   openssl rand -hex 32
   ```

2. In Test Mode open **Account & Settings** and then **Webhooks**, choose **Add New Webhook** and fill in:

   | Field         | Value                                       |
   | ------------- | ------------------------------------------- |
   | Webhook URL   | `https://<API_DOMAIN>/v1/webhooks/razorpay` |
   | Secret        | `<WEBHOOK_SECRET>`                          |
   | Alert Email   | `billing@motionile.com`                     |
   | Active Events | exactly the 16 events below                 |

   Select these events and no others:

   ```text
   payment.captured
   payment.failed
   order.paid
   refund.created
   refund.processed
   refund.failed
   subscription.authenticated
   subscription.activated
   subscription.charged
   subscription.pending
   subscription.halted
   subscription.cancelled
   subscription.completed
   subscription.paused
   subscription.resumed
   subscription.updated
   ```

   All sixteen are handled. Leaving one out breaks a specific behavior: without `subscription.authenticated` the state stays `created` until the verify call or the nightly sync, without `subscription.charged` a renewal grants no credits, without `refund.processed` refunds wait for the 15-minute reconciliation, and without `payment.captured` and `order.paid` purchases rely on the browser handler and reconciliation alone. Events you do not subscribe to (for example `payment.authorized`) would only be stored as `ignored`.

3. Save and keep the webhook **Active**.

The URL must be reachable from the internet over HTTPS with a valid certificate (Caddy provides it on the API domain). The route reads the raw body, so nothing in front of it may rewrite the body. Razorpay redelivers events that did not get a 2xx response and disables a webhook that keeps failing, so create the webhook only after the API with the endpoint is deployed.

### 2.3 Upload the values to SSM

Create the values file outside git (the directory is ignored) and upload it as described in [secrets-rotation.md](secrets-rotation.md#upload-owner-parameters):

```bash
mkdir -p infra/parameters
umask 077
cat > infra/parameters/staging-razorpay.env <<'EOF'
BILLING_RAZORPAY_KEY_ID=<KEY_ID>
BILLING_RAZORPAY_KEY_SECRET=<KEY_SECRET>
BILLING_RAZORPAY_WEBHOOK_SECRET=<WEBHOOK_SECRET>
EOF
AWS_REGION=ap-south-1 infra/scripts/put-parameters.sh staging infra/parameters/staging-razorpay.env
rm infra/parameters/staging-razorpay.env
```

Expected result: three `stored /motionile/staging/BILLING_RAZORPAY_...` lines. Values containing a single quote are rejected by the script; Razorpay values never contain one.

Redeploy so the containers read the new parameters ([Redeploy with the current tag](secrets-rotation.md#redeploy-with-the-current-tag)), then verify:

```bash
curl -fsS https://<API_DOMAIN>/health/ready
```

Expected result: `{"status":"ok","checks":{"postgres":"ok","redis":"ok"}}`. A missing billing parameter fails the deployment before this point.

### 2.4 Dashboard settings

Check these in Test Mode now and again in Live Mode before go-live:

| Setting                      | Where                                    | Value                                                                                                                                                                                                       |
| ---------------------------- | ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Payment capture              | **Account & Settings**, payment capture  | **Automatic.** Motionile grants credits only for `captured` payments and never captures by itself. A payment left `authorized` is not settled and Razorpay refunds it after its capture window.             |
| Subscriptions                | **Subscriptions** menu                   | Enabled. In Live Mode this may need a request to Razorpay support ([platform-applications.md](platform-applications.md#72-steps) step 8).                                                                   |
| Subscription payment retries | **Subscriptions**, settings              | Keep Razorpay's default retry schedule. Motionile reacts to `subscription.pending` (a charge failed, a retry is scheduled) and `subscription.halted` (retries exhausted); it never retries a charge itself. |
| Customer notifications       | **Subscriptions**, settings, and the API | Motionile creates subscriptions with `customer_notify` off and sends its own emails. Do not turn on Razorpay's duplicate customer emails unless you want both.                                              |
| Webhook alert email          | The webhook form                         | `billing@motionile.com`, so a disabled webhook reaches a person.                                                                                                                                            |
| Website details              | **Account & Settings**, business website | Production only; see section 4.                                                                                                                                                                             |

### 2.5 Products and plans

Plans live in Razorpay and are linked from `products.razorpay_plan_id`. Create them through Motionile, never by hand in the dashboard.

Staging can use the sample products. On the instance, as `deploy` ([access-and-operations.md](access-and-operations.md#1-open-a-shell-on-the-instance)):

```bash
/srv/motionile/bundle/scripts/compose.sh exec -T api python -m motionile.scripts.seed_products --env staging
```

Expected result: `Saved 7 products, created 4 plans, activated 4, skipped 0.` on the first run. It creates three credit packs (Starter, Creator, Studio) and the Pro and Team plans, monthly and yearly, in the connected Razorpay account, and is safe to run again (`skipped` counts rows it left alone). The script refuses `--env production`.

For real products, use the admin console (`https://<WEB_DOMAIN>/admin/billing/products`, permission `billing.products.manage`):

1. **New product.** Credit pack: name, code (for example `pack_starter`), price in INR, credits, features. Subscription: also the `plan_key` (for example `pro`) and the interval (month or year). A subscription product is created inactive.
2. For a subscription product, open it and choose **Sync plan**. This creates the plan in Razorpay (monthly or yearly, with the product price) and stores `razorpay_plan_id`.

   Expected result: the product detail shows a plan ID starting with `plan_`. If the call returns `503` saying a plan may exist unlinked, look in the Razorpay dashboard under **Subscriptions**, **Plans** before retrying; a retry creates another plan.

3. **Activate.** A subscription needs a synced plan (`plan_not_synced`) and a free `plan_key` plus interval slot (`active_plan_exists` names the product to deactivate first).
4. Open `https://<WEB_DOMAIN>/pricing`.

   Expected result: the active products appear within a minute (the products cache lasts 60 seconds), priced "incl. GST".

Prices and credits of a product that has been used cannot change; see [price changes](billing-operations.md#price-changes).

## 3. Verify in test mode

Run all of this on staging with a real signed-in account whose email you can read. Keep the admin console open in a second tab: **Billing**, then **Webhooks**, **Payments**, **Orders**, **Subscriptions** and **Refunds**.

Test payment methods change; check Razorpay's [test card details](https://razorpay.com/docs/payments/payments/test-card-details/?preferred-country=IN). At the time of writing, Visa `4111 1111 1111 1111` with any future expiry and any CVV succeeds, and the UPI ID `success@razorpay` succeeds while `failure@razorpay` fails. The test bank page has explicit Success and Failure buttons.

### 3.1 Credit pack purchase

1. On `/billing/plans` or `/pricing`, buy the smallest credit pack and pay with a success method.
2. The status page `/billing/status/<orderId>` should show the order as paid within seconds.
3. Check:
   - `/billing/credits` shows the new balance and one non-expiring lot of the pack size.
   - `/billing/history` lists the order and the payment.
   - The receipt email arrived.
   - In the admin console, **Orders** shows the order `paid` and **Payments** shows the payment `captured` with `creditsGranted` equal to the pack.
   - **Webhooks** shows `payment.captured` and `order.paid` with status `processed` for this payment.

Expected result: exactly one credit lot and one receipt, even though three paths (the browser, `payment.captured` and `order.paid`) settled the order.

### 3.2 Failed payment and abandoned checkout

1. Start another purchase and use `failure@razorpay` (or the Failure button). The order stays `pending` (Razorpay allows retries on the same order), the `payment.failed` webhook is `processed`, **Payments** lists the attempt as `failed`, and no credits are granted.
2. Start a third purchase and close Checkout without paying. The order stays `pending` and is expired by reconciliation after its expiry (two hours by default and at least 30 minutes old). You do not need to wait for that on staging; check the next day that **Billing**, then **Reconciliation** shows `pending_orders` runs completing.

### 3.3 Subscription

1. Subscribe to a plan with a test card on `/billing/plans`. Complete the authorization.
2. Check within a minute:
   - `/billing` shows the subscription `active` with a period end and the plan's credits as a lot expiring at the period end (unless `billing.subscription_rollover` is on).
   - **Webhooks** shows `subscription.authenticated`, `subscription.activated` and `subscription.charged` as `processed`.
   - **Subscriptions** shows the subscription `active` with `paidCount` 1, and **Orders** shows the subscription order `paid`.
   - The activation email arrived.
3. Change plan from `/billing/plans`: the subscription shows the pending plan for the next cycle.
4. Cancel from `/billing`: the subscription shows it ends at the period end, `cancel_at_period_end` is true, and the cancellation email arrived. The status becomes `cancelled` when the paid period ends (or immediately if you cancel a subscription that is not `active`).

Renewals cannot be triggered on demand in Razorpay test mode. The renewal path (`charged` for a later cycle, `pending`, `halted`, `paused`, `resumed`) is covered by the fake-Razorpay tests; here, verify the first charge and confirm the daily sync runs (**Reconciliation**, type `subscriptions`).

### 3.4 Refund

1. In the admin console open the purchase payment and choose **Refund** (permission `billing.refunds.create`). Read the clawback preview, enter a reason and refund part of the amount.
2. Check:
   - The refund shows `pending`, then `processed` once `refund.processed` arrives (test mode is fast).
   - **Webhooks** shows `refund.created` and `refund.processed` as `processed`.
   - The payment becomes `partially_refunded` with the refunded amount; the credit ledger shows a `refund_clawback` row of the previewed size, taken from the pack's lot.
   - The refund email arrived.
3. Refund the remainder. The payment becomes `refunded` and the total clawed back never exceeds the credits granted.

### 3.5 Webhook delivery and failure handling

1. In the Razorpay dashboard open the webhook and its delivery log; every delivery should show HTTP 200.
2. In **Webhooks** in the admin console there should be no `failed` event and none stuck `received`.
3. Optional check of the signature gate:

   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' -X POST https://<API_DOMAIN>/v1/webhooks/razorpay \
     -H 'Content-Type: application/json' -H 'X-Razorpay-Event-Id: manual_check' --data '{"event":"payment.captured"}'
   ```

   Expected result: `401`. Nothing is stored.

To inspect events directly in the database (Neon SQL editor), without reading payloads:

```sql
SELECT event_type, status, attempts, ignored_reason, received_at
FROM webhook_events
ORDER BY received_at DESC
LIMIT 30;
```

### 3.6 Next morning

After 04:00 UTC the daily settlement check has compared the previous day's payments. **Billing**, then **Reconciliation** should show a `settlement` run `completed` with zero mismatches and a downloadable report. The roadmap's done criteria for Phase 7 include a real test-mode purchase, subscription and refund on staging; record the date and the results in the pull request.

## 4. Go-live checklist (production)

Do not start before section 3 passed on staging. Work through the list in order and tick each line in the change ticket.

### 4.1 Website and business readiness

Razorpay reviews the live website before activating payments, and customers expect these pages. Every URL must return `200` over HTTPS without a login, be linked from the footer and contain no placeholder text:

- [ ] Pricing: `https://<PRODUCTION_DOMAIN>/pricing`, real INR prices "incl. GST" and what each pack or plan includes.
- [ ] Terms and conditions: `https://<PRODUCTION_DOMAIN>/legal/terms`.
- [ ] Privacy policy: `https://<PRODUCTION_DOMAIN>/legal/privacy`.
- [ ] Cancellation and refund policy with timelines: `https://<PRODUCTION_DOMAIN>/legal/refund-policy`. It must match what Motionile does: refunds are issued by an administrator, cancellation of a subscription takes effect at the end of the paid period, and credits already spent are not recovered.
- [ ] Contact: `https://<PRODUCTION_DOMAIN>/contact` with the registered address, phone number and `support@motionile.com`, plus the grievance officer details.
- [ ] A delivery statement: credits and videos are delivered digitally to the account right after payment; nothing is shipped.
- [ ] About: `https://<PRODUCTION_DOMAIN>/about`.
- [ ] Legal entity name and GSTIN shown in the footer or terms, matching the GST certificate (placeholders in `siteConfig.legal` replaced).

### 4.2 Razorpay account

- [ ] KYC approved and the account activated (**Live Mode** is selectable). Documents and timeline: [platform-applications.md](platform-applications.md#72-steps).
- [ ] Settlement bank account added and verified (a current account in the exact legal name of the company).
- [ ] Business website details submitted and approved for `https://<PRODUCTION_DOMAIN>`.
- [ ] Subscriptions enabled in Live Mode.
- [ ] Payment capture set to **Automatic** in Live Mode (section 2.4).
- [ ] Payment methods you want to accept (cards, UPI, netbanking, wallets) enabled in Live Mode. UPI AutoPay or card mandates are needed for subscriptions.

### 4.3 Live keys and webhook

1. In **Live Mode** open **Account & Settings**, then **API keys**, choose **Generate Live Key** and store the key ID and secret in the password manager under `Motionile / Razorpay / production`.
2. Create the live webhook with a **new** secret (`openssl rand -hex 32`, different from the test one). Test-mode webhooks do not exist in Live Mode, so this is a new registration, not an edit:

   | Field         | Value                                                  |
   | ------------- | ------------------------------------------------------ |
   | Webhook URL   | `https://api.<PRODUCTION_DOMAIN>/v1/webhooks/razorpay` |
   | Secret        | the new live `<WEBHOOK_SECRET>`                        |
   | Alert Email   | `billing@motionile.com`                                |
   | Active Events | the same 16 events as section 2.2                      |

3. Upload the three values to production exactly as in section 2.3, with `production` in place of `staging`, then deploy. Production deploys wait for reviewer approval ([deploy-and-rollback.md](deploy-and-rollback.md)).
4. Confirm readiness: `curl -fsS https://api.<PRODUCTION_DOMAIN>/health/ready`.

### 4.4 Products in production

The sample seed never runs in production. Create the real products in the admin console as in section 2.5 (credit packs, then each subscription product: create, **Sync plan**, **Activate**). Plans are created in the live account, so every plan ID starts with `plan_` and belongs to Live Mode. Check `https://<PRODUCTION_DOMAIN>/pricing` shows exactly the products you intend to sell.

### 4.5 First live smoke test

Use a real card or UPI account you control and keep amounts small. Razorpay may keep its fee on refunded payments, so expect a small cost.

- [ ] Buy the smallest credit pack. The order becomes `paid`, the lot and receipt appear, and the live webhook deliveries show HTTP 200.
- [ ] Refund that payment fully from the admin console. The refund becomes `processed`, the credits are clawed back, and the refund email arrives. The refunded amount reaches the card or account on Razorpay's refund timeline.
- [ ] Subscribe to the cheapest plan. The subscription becomes `active` with the first charge and its credits.
- [ ] Cancel the subscription, then refund its charge. Refunding does not cancel a subscription and cancelling does not refund.
- [ ] Check **Webhooks**: no `failed` or stuck events.
- [ ] The next morning, the settlement check run for the previous day is `completed` with zero mismatches, and the Razorpay dashboard settlement for the smoke payments matches.
- [ ] Look for `alert.raised` lines in CloudWatch ([billing.md](../billing.md#7-alerts)): none.

### 4.6 After go-live

- [ ] Record the date, the operator and the Razorpay account ID in the operations log.
- [ ] Put the rotation dates in the calendar ([secrets-rotation.md](secrets-rotation.md#schedule)).
- [ ] Tell support who holds `billing.refunds.create` and `billing.credits.adjust` ([billing-operations.md](billing-operations.md#who-can-do-what)).
- [ ] Confirm the finance routine for exports from `orders` and `payments` until GST invoices ship ([billing.md](../billing.md#14-gst-invoices-a-documented-follow-up)).

If go-live goes wrong, set the production webhook inactive in the Razorpay dashboard (events are redelivered later when you reactivate it and the daily reconciliation repairs gaps), and disable purchases by deactivating the affected products in the admin console. Do not switch production to test keys: orders and plans created with live keys cannot be read with test keys.

## 5. Rotation and troubleshooting

- Rotate keys and the webhook secret by following [secrets-rotation.md](secrets-rotation.md#9-razorpay-key-and-webhook-secret).
- Every webhook returns `401`: the webhook secret in Razorpay and in SSM differ, or the modes are mixed. Re-enter the secret on both sides, redeploy, and use the delivery log to redeliver recent events.
- Purchases stay `pending` in the browser but settle later: webhooks are not arriving. Check the webhook is active, the URL is exact, `webhooks.razorpay` is not rate limited and the API logs show the requests.
- `503 payment_provider_unavailable` on checkout: Razorpay did not answer. Retrying is safe; the order is looked up by receipt, never duplicated.
- A deployment fails with `BILLING_RAZORPAY_... must be set`: the parameter is missing; upload it and redeploy.
