# Billing operations

How to run Motionile billing day to day: issue refunds, handle disputes, investigate reconciliation mismatches, clear flagged orders and stuck webhooks, correct credits, respond to the integrity alert and change prices. For the design behind these procedures, see [billing.md](../billing.md); for connecting Razorpay, see [razorpay-setup.md](razorpay-setup.md).

Two rules apply to everything here:

- Use the admin console and the API. Never edit billing or credit rows with SQL. Credits are corrected with an adjustment that carries a reason, and every administrative action is audited.
- Never send a create call to Razorpay a second time to "retry". Payments, orders, refunds and subscriptions are looked up first; the application does that for you, and when you work in the Razorpay dashboard you should look before you create.

Placeholders:

| Placeholder    | Meaning                                                           |
| -------------- | ----------------------------------------------------------------- |
| `<ENV>`        | `staging` or `production`                                         |
| `<WEB_DOMAIN>` | The web host of the environment; the admin console is at `/admin` |
| `<API_DOMAIN>` | `api.<DOMAIN>` or `api.<STAGING_DOMAIN>`                          |

Admin console pages (all under `https://<WEB_DOMAIN>/admin/billing`): `payments`, `orders`, `refunds`, `subscriptions`, `webhooks`, `reconciliation`, `products`. Credits and adjustments are on a user's page, `https://<WEB_DOMAIN>/admin/users/<USER_ID>`. The runtime settings are under `/admin/settings` and the audit trail under `/admin/audit-logs`.

## Who can do what

| Permission                | Actions                                                                                                                               | Default holders          |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ |
| `billing.read`            | View products, payments, orders, refunds, subscriptions, credit wallets and ledgers, reconciliation runs, download reports, analytics | `admin`, `super_admin`   |
| `billing.products.manage` | Create, edit, duplicate, activate, deactivate products and sync plans                                                                 | `admin`, `super_admin`   |
| `billing.webhooks.manage` | View stored webhook events and reprocess them                                                                                         | `admin`, `super_admin`   |
| `billing.refunds.create`  | Refund a payment; cancel a user's subscription as an admin                                                                            | `super_admin` by default |
| `billing.credits.adjust`  | Grant or remove credits for a user                                                                                                    | `super_admin` by default |

Money-moving permissions (refunds and credit adjustments) are deliberately kept off the `admin` role. Grant them to a narrower role only for people who need them and review the grant quarterly; role changes take effect on the holder's next request. See [bootstrap-admin.md](bootstrap-admin.md) for creating the first `super_admin` and the roles area of the console for custom roles.

What gets audited (visible in `/admin/audit-logs`, actor and target recorded): `billing.refund.requested`, `billing.refund.processed`, `billing.refund.failed`, `billing.refund.rejected`, `billing.refund.adopted`, `credits.adjusted`, `billing.webhook.reprocess_requested`, `billing.subscription.cancelled_by_admin`, `billing.product.*`, `billing.order.paid`, `billing.order.settled_late` and `billing.payment.flagged`. Entries about billing are kept eight years.

Good practice: the person who requests a refund or adjustment writes the ticket reference in the reason, and a second person reviews the weekly list of refunds and adjustments.

## Daily routine

A five-minute check each morning (UTC) and after every deployment:

1. Alerts. In CloudWatch Logs Insights for `/motionile/<ENV>` ([access-and-operations.md](access-and-operations.md#logs-insights-queries)):

   ```text
   fields @timestamp, alert_code, @message
   | filter event = "alert.raised"
   | sort @timestamp desc
   | limit 100
   ```

   Expected result: no rows, or rows you have already handled. Each code and its action is in [billing.md](../billing.md#7-alerts).

2. The **Needs attention** panel on the billing overview (`/admin/billing`) lists flagged orders, reconciliation runs with mismatches and failed webhooks. Then **Webhooks**, filtered to `failed` and then to `received`: both lists should be empty or contain only events from the last few minutes.
3. **Orders** with the flagged filter: nothing unhandled ([Flagged orders](#flagged-orders)).
4. **Reconciliation**: yesterday's `settlement` run is `completed` with `mismatch` 0, today's `subscriptions` run (03:15 UTC) is `completed`, and the latest `pending_orders` runs are `completed`.
5. **Refunds** filtered to `pending`: none older than an hour.
6. The Razorpay dashboard: no banner about a disabled webhook, no open disputes ([Disputes and chargebacks](#disputes-and-chargebacks)), settlements arriving.

## Issuing a refund

Refunds are made by an administrator with `billing.refunds.create`. Customers cannot refund themselves.

1. Open **Payments**, find the payment (filter by user, status or order), and open it. Check:
   - Status `captured` or `partially_refunded`. A `failed` or `authorized` payment is not refundable.
   - `refundablePaise`: the amount still refundable, which is the payment amount minus processed refunds minus refunds already pending.
   - The credit lot of the payment and how much of it remains. A spent pack recovers fewer credits than the money returned; that is expected.
2. Choose **Refund**. Leave the amount empty for everything still refundable, or enter a partial amount in rupees. The dialog previews the credits that will be taken back (the same calculation the processing uses: `min(lot remaining, ceil(credits x refund / payment amount))`, bounded by the unreserved balance).
3. Enter the reason (required, up to 500 characters). Include the ticket ID and why: `Ticket 4821: duplicate purchase, customer contacted support`.
4. Submit.

   Expected result: a refund in `pending` with the Razorpay refund ID. Within a minute the `refund.created` and `refund.processed` webhooks arrive, the refund becomes `processed`, `creditsClawedBack` shows the credits taken, the payment becomes `partially_refunded` or `refunded`, and the customer gets the refund email. Razorpay returns the money to the customer's card or account on its own timeline, typically within 5 to 7 working days.

5. If the customer should also stop being billed, cancel the subscription separately: **Subscriptions**, open it, **Cancel** (at period end or immediately). A refund never cancels a subscription and a cancellation never refunds.

Errors you may see:

| Response                           | Meaning and action                                                                                                                                                                        |
| ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `422 refund_exceeds_refundable`    | The amount is above what is left. The response includes the remaining `refundablePaise`. Check the **Refunds** list for a `pending` refund of this payment: it counts against the amount. |
| `409 payment_not_refundable`       | The payment is not captured (failed, authorized) or is already fully refunded.                                                                                                            |
| `409 idempotency_key_reused`       | The same request key was used with a different amount. Start a new refund.                                                                                                                |
| `422 refund_rejected`              | Razorpay rejected the refund; the reason is on the refund. Fix the cause and submit again with a new request.                                                                             |
| `503 payment_provider_unavailable` | Razorpay did not answer. The refund may or may not exist at Razorpay; see [Failed and pending refunds](#failed-and-pending-refunds). Do not create a duplicate in the Razorpay dashboard. |

Repeating exactly the same request (same `Idempotency-Key`) is always safe: the refund is resumed, not duplicated.

## Failed and pending refunds

Refund states: `pending` (requested, waiting for Razorpay), `processed`, `failed`.

**Pending with a Razorpay ID.** Razorpay accepted it and has not confirmed yet. Wait; `refund.processed` completes it. If it is still pending after a day, open the refund in the Razorpay dashboard (Transactions, Refunds). If Razorpay shows it processed, look in **Webhooks** for the `refund.processed` event: if it is `failed`, [reprocess it](#stuck-and-failed-webhooks). If the event never arrived there is no automatic repair, because no task fetches the status of a refund that already has a Razorpay ID: resend the event from the webhook delivery log in the Razorpay dashboard if the console offers it (the original event ID is kept, so it is safe), or ask engineering to settle the refund. Until then the refund keeps its amount reserved against the payment.

**Pending without a Razorpay ID.** The create call timed out and the lookup found nothing (alert `billing.refund_unconfirmed`). The amount stays reserved against the payment. Within 15 minutes `billing.reconcile_pending_refunds` looks the refund up again through its notes:

- It finds it: the refund is linked and settled as if the webhook had arrived (alert `billing.refund_resolved`, informational).
- It confirms Razorpay has no such refund: the refund becomes `failed` with `not_found_at_provider` (alert `billing.refund_not_found_at_provider`) and the amount is free again. Check the payment in the Razorpay dashboard to be sure no refund exists, then issue the refund again.
- The lookup itself fails: nothing changes and the next run tries again.

Do not create the refund by hand in the Razorpay dashboard while a Motionile refund for the same payment is pending. If you must refund from the dashboard (for example the console is unavailable), do it once, and Motionile adopts the refund when its webhook arrives (see below).

**Failed.** Razorpay rejected the refund or reported `refund.failed` (alert `billing.refund_rejected` or `billing.refund_failed`). Read `failureReason` on the refund. Common causes are an expired payment instrument or insufficient Razorpay balance for the refund. Resolve the cause (add balance, ask the customer for another channel) and issue a new refund with a new request key. A failed refund frees its amount.

**Refunds made in the Razorpay dashboard.** They arrive as webhooks without Motionile's refund ID. The handler adopts them as refunds with reason `external_refund` (idempotency key `external:<Razorpay refund id>`), claws back the proportional credits and emails the customer. If the amount does not fit what is refundable, `billing.external_refund_exceeds_payment` is raised and nothing is applied: compare the payment's refunds in both systems and correct credits by adjustment if needed.

## Disputes and chargebacks

A dispute starts when a customer asks their bank to reverse a payment. Razorpay notifies `billing@motionile.com` and lists it in the dashboard under the payment's Disputes. Motionile does not subscribe to Razorpay's dispute events, so disputes are handled in the Razorpay dashboard and the effect on credits is applied by hand. The platform keeps no dispute state; the payment keeps its status.

1. **Spot it.** The Razorpay email names the payment ID, the amount and the response deadline. Find the payment in **Payments** by Razorpay payment ID (or the order from the payment's notes). Note the deadline; missing it loses the dispute.
2. **Decide quickly whether to refund instead.** If the customer has a legitimate complaint and the money would be lost anyway, issue a normal refund before the deadline ([Issuing a refund](#issuing-a-refund)) and tell Razorpay support. Do not both refund and contest unless Razorpay advises it; check the payment's state in the dashboard first.
3. **Gather evidence** for a contested dispute: order and payment IDs and amounts from the console, the receipt email, the credit ledger (credits granted and when), usage records and the videos the customer generated with those credits (which prove the service was delivered and used), the terms, refund policy and pricing pages as they were at purchase, login and session data from the audit log for the account, and the support thread. Redact anything unrelated.
4. **Respond** in the Razorpay dashboard before the deadline with the evidence documents. Razorpay forwards them to the bank; the outcome arrives by email.
5. **Outcome:**
   - **Won:** nothing changes. Note it on the ticket.
   - **Lost:** Razorpay debits the disputed amount from your settlements. The payment in Motionile still shows `captured` and `refundedPaise` is unchanged. Remove the credits the customer still holds with an adjustment ([Corrections](#corrections)) of up to the unspent credits from that payment, with a reason such as `Chargeback lost, payment pay_xxx, dispute disp_xxx`. If the customer has spent the credits, the loss stands; consider suspending the account if the dispute looks fraudulent (the access area of the console; suspension revokes every session).
6. The settlement check (next section) may show a `refunded` difference for a payment whose dispute was resolved as a reversal; record the dispute ID on the ticket so the difference is explained.

Keep a log of every dispute (payment, user, amount, deadline, decision, outcome) with the finance records.

## Flagged orders

An order is flagged when a captured payment cannot be matched to it. The payment is recorded, **no credits are granted**, the order keeps its status and leaves the reconciliation queue, and an alert is raised.

| Flag reason         | What happened                                                                     | Alert                       |
| ------------------- | --------------------------------------------------------------------------------- | --------------------------- |
| `amount_mismatch`   | The captured amount differs from the order (or from the plan price for a charge). | `billing.payment_mismatch`  |
| `currency_mismatch` | The captured currency differs.                                                    | `billing.payment_mismatch`  |
| `duplicate_payment` | A second captured payment arrived for an order that is already paid.              | `billing.duplicate_payment` |

To work the queue, open **Orders**, filter to flagged orders, and open one. The detail lists the order, its payments, the flag reason and when it was flagged.

- **Amount or currency mismatch.** This should not happen with Motionile's checkout, so first understand it: did someone pay a different amount through another channel, did the product price change between order creation and payment (the order snapshots the price, so no), or is a Razorpay account setting converting currency? Then resolve:
  1. Refund the full payment ([Issuing a refund](#issuing-a-refund)). The clawback preview is zero because no credits were granted.
  2. Tell the customer to buy again, or, if the customer legitimately paid the right value through another route and you decide to honor it, grant the credits with an adjustment and write the payment ID in the reason.
- **Duplicate payment.** Identify the extra payment: the second one by capture time, not the one that granted credits. Refund the extra payment in full. The customer keeps the credits from the first.
- A subscription charge that does not match the plan price is flagged the same way (the subscription keeps going; later correct charges grant normally). Compare the charge amount with the plan in the Razorpay dashboard; if the plan in Razorpay no longer matches the product, stop and ask engineering before anything else is charged.

An order stays marked as flagged after you resolve it; the refund on the payment, or the audit entry of the adjustment, is the record that it was handled. Write the resolution on the ticket.

## Reconciliation mismatches

The daily settlement check compares the previous UTC day's Razorpay payments with `payments` by Razorpay payment ID and alerts with `billing.reconciliation_mismatch` when anything differs. It reports and never repairs.

1. Open **Reconciliation**, find the `settlement` run for the date (the alert names the run ID and the date) and download its report with **Download report**. Or from the terminal with an admin session cookie: `GET /v1/admin/billing/reconciliation/runs/<RUN_ID>/report`.
2. Read the report. It is a JSON document:

   | Field                              | Meaning                                                                                                                                   |
   | ---------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
   | `date`, `periodStart`, `periodEnd` | The UTC day compared.                                                                                                                     |
   | `counts`                           | `checked`, `mismatches`, and the numbers of `missing`, `extra` and `mismatched`.                                                          |
   | `truncated`                        | `true` when there were more than 1000 differences; the file lists the first 1000. Fix the cause and re-run before reading the rest.       |
   | `mismatches[]`                     | `kind`, `razorpayPaymentId`, `fields[]` (for mismatched), `remote` and `local` with `amountPaise`, `currency`, `status`, `refundedPaise`. |

3. Work each difference by kind.

**`missing`: Razorpay captured the payment, Motionile has no record.** The most likely causes are a dropped `payment.captured` webhook for a payment made after the order had already expired, a subscription `charged` event that never arrived, or a payment that did not come from a Motionile order (a Razorpay payment link, a manual collection, another application on the same account).

1.  Open the payment in the Razorpay dashboard and read its notes and order. Notes carry `userId` and `orderId` for Motionile orders and `subscriptionId` for subscriptions.
2.  No Motionile notes: not ours. Refund it in Razorpay or leave it, per finance policy, and write down why.
3.  Notes point to an order: open the order in the console. If it is `pending` or `created`, the 15-minute reconciliation will settle it; wait one cycle and check again. If it is already `expired`, `failed` or `cancelled`, reconciliation will not look at it again. Resend the event from the Razorpay webhook delivery log if the console offers a resend (the original event ID is kept, so it is safe), or ask engineering to settle it from the stored data. As a last resort grant the credits with an adjustment that cites the payment ID, accepting that the payment row is then still missing.
4.  A subscription charge: open the subscription; the daily sync repairs status and period but does not grant credits. Resend the `subscription.charged` event or grant the period's credits by adjustment (reason: `Missing charge pay_xxx for subscription sub_xxx`).

**`extra`: Motionile has a captured payment that Razorpay does not know.** Treat as serious. Possible causes: keys of the wrong mode connected to the environment, a test payment recorded in production, or data damage. Stop issuing refunds for this payment, find how the row was created (audit log, webhook events around its `created_at`, the order and the user) and involve engineering and the billing reviewer. Do not delete the row.

**`mismatched`: both sides know the payment but disagree.** Read `fields`:

- `refunded`: Razorpay shows a different refunded amount. Often benign: a refund is in flight (Motionile counts pending refunds as refunded for this comparison) or a dashboard refund's webhook has not been processed. Check **Refunds** and **Webhooks** for the payment; reprocess a failed `refund.*` event, or wait a day. A lost dispute can also appear here ([Disputes and chargebacks](#disputes-and-chargebacks)).
- `status`: Razorpay says captured and Motionile does not (or the reverse). Reprocess the payment's webhook events; if there are none, look at the order and the 15-minute reconciliation.
- `amount` or `currency`: investigate like a flagged order; this means money moved that Motionile recorded differently.

4. After the cause is fixed, record the resolution on the ticket. A day is compared once (the settlement run is unique per UTC day), so the difference will not be raised again; the ticket and the audit log are the record.

The `subscriptions` run (03:15 UTC) alerts with `billing.subscription_sync_mismatch` when Razorpay's subscription state could not be reached through allowed transitions. Open the subscription, compare with the Razorpay dashboard and look for missing events; the usual fix is replaying the missing webhook.

## Stuck and failed webhooks

An event is stuck when it stays `received` for more than a few minutes and failed when processing raised an error. `billing.requeue_stuck_webhooks` runs every 2 minutes and re-queues `received` events older than 2 minutes and `failed` events that still have attempts left when no job is pending, so most hiccups heal themselves.

1. Open **Webhooks** and filter by status `failed` (or `received`). Open the event: it shows the type, the attempts, `lastError` and the redacted payload.
2. Read `lastError`:
   - A database or network error on the first attempts: transient. It is retried with exponential backoff until `BILLING_WEBHOOK_MAX_ATTEMPTS` (10 by default).
   - `ValidationError ...`: the payload shape differs from what the code expects. This is a code issue; do not reprocess until it is fixed and deployed.
   - A message about an unexpected order state or an unknown subscription period: data problem; look up the order or subscription in the console and compare with Razorpay.
3. If the worker looks unhealthy, check it ([access-and-operations.md](access-and-operations.md#3-logs-status-and-restarts-on-the-instance)); billing tasks run on `worker-default`. Failed attempts are logged as `billing.webhook_attempt_failed`:

   ```text
   fields @timestamp, event_row_id, attempts, error
   | filter event = "billing.webhook_attempt_failed"
   | sort @timestamp desc
   | limit 50
   ```

4. After the cause is fixed, choose **Reprocess** (permission `billing.webhooks.manage`). Reprocessing queues a forced run and is audited. It is safe because handlers are idempotent: a payment already settled stays settled, a refund already processed does not claw back twice.
5. Check the event is now `processed` (or `ignored` with a reason you understand).

Notes:

- Events that ended `ignored` are normal: `unhandled_event` (a type we do not process), `unknown_entity` (a payment or refund that is not ours), `stale` and `invalid_transition` (an older or impossible subscription event). Reprocess an `ignored` event only if the reason was a bug or an older version of the code (see [Rolling back](#rolling-back)).
- An event that stays `failed` after the maximum attempts has raised `billing.webhook_failed`. It is not retried automatically any more; reprocessing is the way.
- Payloads of `processed` and `ignored` events are blanked after 90 days; reprocessing such an event cannot work.
- If Razorpay shows deliveries failing with non-2xx statuses, the problem is on the receiving side: check the API is up, the rate limit `webhooks.razorpay` and the webhook secret ([razorpay-setup.md](razorpay-setup.md#5-rotation-and-troubleshooting)). Razorpay redelivers, and duplicates are harmless.

## Corrections

Use an adjustment for every correction to credits: goodwill credits, compensation for a failed job, removal after a lost chargeback, a subscription charge that expired before its credits could be granted, a missing charge, or removing credits obtained fraudulently. Never edit `credit_wallets`, `credit_lots` or `credit_ledger`; the ledger is append-only and a database trigger rejects changes.

1. Open the user's page in the console, **Credits**, and review the wallet, the lots (what is left in each, which expire) and the ledger. Understand the cause before changing anything.
2. Choose **Adjust credits**:
   - A positive amount grants credits as a new `admin` lot. Add an expiry for goodwill credits you do not want to live forever.
   - A negative amount removes credits, taking them from the lots expiring soonest first.
3. Write the reason (required, up to 500 characters) with the ticket and the references: `Ticket 4821: chargeback lost, payment pay_xxx`. This text is stored on the ledger entry and in the audit log.
4. Submit. Each submission carries an idempotency key, so a repeated click or retry never applies twice.

   Expected result: the ledger shows an `admin_adjust` entry with your reason, the wallet balance moves by the amount, and `credits.adjusted` appears in the audit log.

Limits you will meet:

- A removal cannot take the balance below the credits held by active reservations (`409 adjustment_exceeds_available`). Wait for the reservations to settle (they end with the job or within the reservation TTL, one hour by default) or remove less.
- A grant expiry must be in the future and applies to grants only (`invalid_credit_expiry`).
- To undo an adjustment, make the opposite adjustment with a reason that cites the first one. Do not look for a delete.

An adjustment cannot repair a structural problem such as a wallet that disagrees with its lots; see [Integrity check alert](#integrity-check-alert).

## Integrity check alert

`credits.check_integrity` runs at 02:30 UTC, is read-only and raises `credit_integrity_violation` when any wallet breaks an invariant. The alert lists, per user, each problem with the invariant, the expected value and the actual value. Treat it as an incident: balances are money.

1. Pull the alert from the logs ([Daily routine](#daily-routine)) and note the user IDs and problems.
2. Read what each invariant means:

   | Invariant                               | Meaning                                                           |
   | --------------------------------------- | ----------------------------------------------------------------- |
   | `balance_equals_ledger_delta_sum`       | The wallet balance is not the sum of all ledger deltas.           |
   | `balance_equals_lot_remaining_sum`      | The wallet balance is not the sum of the lots' remaining credits. |
   | `reserved_equals_ledger_reserved_sum`   | Reserved credits are not the sum of ledger reserved deltas.       |
   | `reserved_equals_active_reservations`   | Reserved credits are not the sum of active reservations.          |
   | `balance_equals_latest_balance_after`   | The newest ledger row's balance after disagrees with the wallet.  |
   | `reserved_equals_latest_reserved_after` | The newest ledger row's reserved after disagrees with the wallet. |
   | `balance_non_negative`                  | The balance is negative.                                          |
   | `reserved_within_balance`               | Reserved is negative or above the balance.                        |
   | `lots_non_negative`                     | A lot has a negative remainder.                                   |

3. Open the user in the console: wallet, lots and ledger. Compare the newest ledger rows with the lots and active reservations. Check whether a deployment, migration or manual database change happened near the time of the last ledger row, and whether the problem appeared right after a particular operation (a refund clawback, an expiry, a commit).
4. Do not adjust, do not edit rows, and do not re-run the check hoping it clears. An adjustment moves the balance, a lot and the ledger together, so it cannot fix a disagreement between them; it would hide the evidence.
5. Escalate to engineering and the billing reviewer with the alert text, the user IDs, the ledger and the timeline. A structural repair is a reviewed data fix with its own audit record, not an ad hoc statement.
6. While waiting, if the user is actively spending credits and the numbers are wrong in the user's disfavor, communicate with the customer rather than letting jobs fail silently; in an emergency, suspend the account (the access area of the console) to stop operations on a damaged wallet.
7. The next nightly run confirms the repair. The same violation twice means the cause is still active.

Related alerts: `credit_invariant_violation` means an operation was rolled back because it would have broken the reserved-versus-balance rule (a bug in the caller; the wallet is untouched), and `credit_wallet_missing` means a credit operation found no wallet where one must exist.

## Price changes

A product that any order or subscription references cannot change its price, credits, currency, interval or plan. A price change is a new version.

For a credit pack:

1. Open the product, choose **Duplicate**. This creates the inactive product `<base>_v<n>` with the next version number and a link to the source.
2. Edit the new product's price and credits (allowed while it is unused). Check the name and features read correctly; the pricing page shows these.
3. **Activate** the new product and **Deactivate** the old one. Customers see the new price within a minute (the products cache lasts 60 seconds). Old orders keep the price they paid.

For a subscription:

1. **Duplicate** the product, edit price or credits, then **Sync plan**. A new Razorpay plan with the new amount is created and linked. If `sync-plan` answers `503` with a warning that a plan may exist unlinked, look in the Razorpay dashboard under **Subscriptions**, **Plans** before retrying so you do not leave an orphan.
2. Only one active product may exist per plan key and interval. **Deactivate** the old product first, then **Activate** the new one right away; activation names the product to deactivate if you forget (`active_plan_exists`). Between the two steps that plan is not on sale.
3. Existing subscribers stay on the old plan and its old price. Their next charge is the old plan's amount until they change plan themselves (the pricing page offers the new plan). There is no bulk migration; before moving customers to a higher price, give the notice your terms require.
4. Keep the old product: subscriptions and orders still reference it, and a deactivated product stays readable.

Never change the amount of a plan in the Razorpay dashboard; Razorpay plans are immutable, and the product row would then disagree with what customers are charged.

## Rolling back

- **A deployment.** Roll back with [deploy-and-rollback.md](deploy-and-rollback.md). The database migration for credits and billing is expand-only, so older code keeps working. Webhooks that arrive while older code runs are stored and processed by whatever version is running; an event type the older version has no handler for ends `ignored` with `unhandled_event`. After rolling forward again, filter **Webhooks** to `ignored` and reprocess those events. Pending orders, refunds and subscriptions are healed by the periodic tasks once the correct code runs.
- **A product or price change.** Reactivate the previous version (deactivate the new one first for a subscription plan) and the pricing page returns to the old price within a minute. Orders already placed on the new version stay valid and subscribers on the new plan stay on it.
- **A mistaken refund.** Refunds at Razorpay cannot be undone. Re-grant the clawed-back credits with an adjustment that cites the refund, and decide with finance whether to recover the money from the customer.
- **A mistaken adjustment.** Make the opposite adjustment with a reason citing the first.
- **A bad Razorpay configuration.** Setting the webhook inactive in the Razorpay dashboard is safe: Razorpay redelivers on reactivation and the periodic tasks repair gaps. Deactivate products in the admin console to stop sales without deleting anything. Never point production at test keys.
- **The `billing.subscription_rollover` setting.** Switching it back affects only credits granted afterwards; lots already created keep their expiry.
