---
name: razorpay-flow
description: Patterns for Motionile billing with Razorpay orders, subscriptions, checkout verification, webhooks, refunds and the append-only credit ledger. Use when adding or changing anything in the billing or credits modules.
---

# Razorpay flow

Read `docs/billing.md` first; it has the sequence diagrams, lock ordering and failure handling. `docs/context.md` section 8 is the source of truth and `docs/db/state-machines.md` has every status machine.

## Invariants

- Amounts, credits and plan IDs come only from `products`. The client sends a product code. Money is `bigint` paise; credits are `bigint`. Never use floats.
- A product that any order or subscription references is financially immutable. Change a price by duplicating the product as the next version, never by editing it.
- Credits live in lots (`purchase`, `subscription`, `admin`, `promo`) consumed by `expires_at NULLS LAST, created_at, id`. Jobs, publishing and MCP hold credits with reservations (`reserve`, `commit`, `release`); a sweeper releases stale ones.
- Reach the wallet only through `motionile.modules.credits` (`grant`, `reserve`, `commit`, `release`, `clawback`, `adjust`). Never update `credit_wallets`, `credit_lots` or `credit_reservations` elsewhere, and never edit the ledger.
- Every credit change is exactly one `credit_ledger` row with `delta`, `reserved_delta`, `balance_after`, `reserved_after` and a unique `idempotency_key`, written in the same transaction as the wallet and lot updates, with the wallet row locked first and then its lots. `CreditsService` methods take the caller's session and never commit.
- Keep the ledger invariant: the sum of deltas equals the balance and the sum of lot remainders; the sum of reserved deltas equals the reserved amount and the sum of active reservations. `credits.check_integrity` alerts on a violation. Correct credits through `adjust` with a reason, never by editing rows.
- Settlement is idempotent: checkout verification, webhooks and reconciliation all call `SettlementService.settle` (`settle_payment`), and a second call is a no-op. Subscription charges go through `ChargeRecorder.record`. Never grant credits on a client callback alone.
- Status changes follow the state machines in `billing/states.py` through `billing/transitions.py`: one `UPDATE ... WHERE status = :expected`. A stale or impossible event is stored `ignored`, never applied. Money received is never ignored.

## Idempotency keys

| Operation                             | Key                                                                                                                                                   |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Credit pack grant, subscription grant | `payment:<payments.id>` (our row ID, not Razorpay's)                                                                                                  |
| Refund clawback                       | `refund:<refunds.id>`                                                                                                                                 |
| Admin adjustment                      | SHA-256 of `<admin id>:<user id>:<Idempotency-Key>`                                                                                                   |
| Refund row                            | `refunds.idempotency_key` = SHA-256 of `<admin id>:<payment id>:<Idempotency-Key>`; `external:<Razorpay refund id>` for refunds made in the dashboard |
| Stale reservation release             | `reservation:<id>:ttl`                                                                                                                                |
| Lazy or swept expiry                  | `expiry:<lot id>:<wallet version>`                                                                                                                    |
| Webhook                               | unique `(provider, event_id)` from `X-Razorpay-Event-Id`                                                                                              |
| Order, subscription creation          | `orders` unique `(user_id, idempotency_key)`                                                                                                          |

User and admin endpoints that move money take an `Idempotency-Key` through `idempotent(scope)` and `IdempotencyGuard.respond()`.

## Credit pack

1. `POST /v1/billing/orders` inserts `orders` (snapshot of price, credits and product version) with `status = 'created'`, then creates the Razorpay order with `receipt` set to the order ID, then moves the order to `pending`.
2. Checkout returns `razorpay_order_id`, `razorpay_payment_id` and `razorpay_signature`. `POST /v1/billing/payments/verify` checks `HMAC_SHA256(order_id + "|" + payment_id, key_secret)` in constant time, fetches the payment from Razorpay and requires its order to match.
3. `settle` locks the order, upserts the payment by Razorpay ID, compares amount and currency with the order, then in one transaction marks the order `paid` (even from `expired`, `failed` or `cancelled`: a captured payment always settles), grants a non-expiring `purchase` lot with key `payment:<id>`, writes audit rows and queues the receipt after commit.
4. A different amount or currency flags the order, records the payment without credits and raises `billing.payment_mismatch`. A second captured payment for a paid order is recorded without credits and raises `billing.duplicate_payment`. A payment first seen with refunded money grants only the proportional remainder.
5. `payment.captured` and `order.paid` webhooks and the 15-minute reconciliation run the same `settle` and find it done.

## Subscriptions

- Create from `products.razorpay_plan_id`; the client sends only a product code. A user has at most one live subscription (`409 subscription_exists`). The local `created` subscription and `subscription` order are inserted first, then the Razorpay subscription with notes `userId`, `orderId`, `subscriptionId` and `customer_notify` off.
- `POST /v1/billing/subscriptions/verify` checks `HMAC_SHA256(payment_id + "|" + subscription_id, key_secret)`, fetches the subscription and moves `created` to `authenticated`. It grants no credits.
- Webhooks drive the state: `authenticated`, `activated`, `charged`, `pending`, `halted`, `cancelled`, `completed`, `paused`, `resumed`, `updated`, in any arrival order. Events are ordered by `event_created_at` against `subscriptions.last_event_at`; period fields and `paid_count` only move forward.
- `charged` records the payment and grants the period's credits once per payment, even when it arrives before `activated` or is stale. The lot expires at the period end unless the runtime setting `billing.subscription_rollover` is on. A charge that differs from the plan price grants nothing and alerts; a charge whose period already ended grants nothing and raises `billing.subscription_charge_expired`.
- Cancel at the end of the period when `active`, immediately otherwise; `cancel_at_period_end` subscriptions are closed by `billing.finalize_subscriptions`. A plan change is scheduled for the next cycle through `pending_product_id`. A refund never cancels a subscription.

## Webhooks

1. Read the raw body and verify `X-Razorpay-Signature` (HMAC-SHA256 of the raw body with the webhook secret) before parsing. A bad signature stores nothing and returns `401 invalid_webhook_signature`.
2. Require `X-Razorpay-Event-Id`. Insert into `webhook_events` deduplicated by `(provider, event_id)`; a duplicate returns `200 duplicate`, and a duplicate still `received` after 60 seconds is queued again.
3. Queue `billing.process_webhook_event` on the `billing` queue after commit and return 200 quickly.
4. The task locks the event row, runs the registered handler inside a savepoint and ends `processed`, `ignored` (`unhandled_event`, `unknown_entity`, `stale`, `invalid_transition`) or `failed`. Failures retry with exponential backoff up to `BILLING_WEBHOOK_MAX_ATTEMPTS`, then alert `billing.webhook_failed`. `billing.requeue_stuck_webhooks` rescues lost jobs and `reprocess_event` (admin) replays any `failed`, `processed` or `ignored` event.
5. Register a handler for every event type the dashboard sends; an unregistered type is stored `ignored` with `unhandled_event`.

## Refunds

- Admin-initiated with `billing.refunds.create` and an `Idempotency-Key`. One transaction locks the payment, bounds the amount by `amount - refunded - pending` (`422 refund_exceeds_refundable`) and stores a `pending` refund. The Razorpay call happens outside the transaction with `notes.refundId` and `receipt` set to the refund ID.
- `refund.processed` locks payment, then refund, then the wallet and lot, marks the refund processed, adds to `payments.refunded_paise` and claws back `min(lot.remaining, ceil(credits_granted x refund / payment amount))`, capped so all clawbacks of a payment never exceed `credits_granted`, with key `refund:<refund id>`.
- A refund made in the Razorpay dashboard is adopted when its webhook arrives (`external:<id>` key, reason `external_refund`).
- `billing.reconcile_pending_refunds` resolves refunds that stayed `pending` without a Razorpay ID by looking them up through `notes.refundId`.

## Never re-send a create call after a timeout

A timeout, 5xx or unusable response is ambiguous. Look the object up, then decide. The client never retries non-GET requests.

| Create call  | Lookup                                                                                             |
| ------------ | -------------------------------------------------------------------------------------------------- |
| Order        | List orders by `receipt` (our order ID)                                                            |
| Subscription | List the plan's subscriptions in the time window and match `notes.subscriptionId`                  |
| Refund       | List the payment's refunds and match `notes.refundId`                                              |
| Customer     | Created with `fail_existing` off, so a repeat returns the existing customer                        |
| Plan         | None: alert `billing.plan_sync_unconfirmed`, return `503`, and check the dashboard before retrying |

## Locking order

Wallet row first, then the reservation, then lots in `expires_at NULLS LAST, created_at, id` order. Billing locks the order, subscription, payment or refund row before calling credits. Refund processing locks payment, then refund, then credits. Webhook processing locks the event row first. Never call Razorpay while holding a wallet or payment lock.

## Reconciliation

- Every 15 minutes `billing.reconcile_pending_orders` settles or expires `created` and `pending` unflagged orders older than 30 minutes, and `billing.finalize_subscriptions` closes cancelled and abandoned subscriptions (re-checking Razorpay first).
- Daily at 03:15 UTC `billing.sync_subscriptions` repairs subscription state from Razorpay, never backwards. At 04:00 UTC `billing.settlement_check` compares the previous UTC day with `payments`, writes the JSON report and alerts `billing.reconciliation_mismatch`. At 02:30 UTC `credits.check_integrity` verifies the invariant.
- Reconciliation reports and repairs; mismatches in the settlement report are resolved by people through refunds and adjustments.

## Tests

- `PROVIDERS_MODE=fake` uses `FakeRazorpay` (Redis-backed, `modules/billing/razorpay/fake*.py`). In `local` and `ci` the test-support routes under `/v1/_test/razorpay` pay orders, authorize and advance subscriptions, settle refunds, build and deliver signed webhooks (duplicates, fixed event IDs and timestamps, invalid signatures), inject faults (`timeout_after_create`, `timeout_before_create`, `server_error`) and reset state. They are excluded from the API contract.
- Server unit tests live in `apps/server/tests/unit/modules/billing` and `apps/server/tests/unit/modules/credits` and use `apps/server/tests/fakes`; they never touch real I/O. Integration tests live in `apps/server/tests/integration/test_billing_*.py` and `test_credits_*.py` against testcontainers; use a committed-transaction fixture only for the races in `test_billing_races.py`.
- Cover duplicate webhooks, concurrent settlement, out-of-order subscription events, signature failures, timeouts after create, late payments on expired orders, amount mismatches, partial and external refunds, and the ledger invariant (property tests in `test_ledger_properties.py`).
- Sign test webhooks with `sign_webhook` from `motionile.modules.billing.razorpay.signatures`, with `tests/support/signed-webhook.ts` in root specs, or let the fake build them through `/v1/_test/razorpay/webhooks`. Root specs run against the fake Razorpay: `tests/e2e/billing`, `tests/security/api/billing-*.spec.ts` and `tests/load/scenarios/billing-webhooks.js`.
