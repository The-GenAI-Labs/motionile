---
name: razorpay-flow
description: Patterns for Motionile billing with Razorpay orders, subscriptions, checkout verification, webhooks, refunds and the append-only credit ledger. Use when adding or changing anything in the billing or credits modules.
---

# Razorpay flow

## Invariants

- Amounts come only from `products`. Money is `bigint` paise; credits are `bigint`.
- Every credit change is one `credit_ledger` row with `balance_after` and a unique `idempotency_key`, written in the same transaction as the wallet update with the wallet row locked.
- Settlement is idempotent: checkout verification and webhooks call the same settlement function and the second call is a no-op.

## Credit pack

1. Insert `orders` with the product's amount and `status = 'created'`.
2. Create the Razorpay order with that amount and `receipt` set to the order ID.
3. Checkout returns `razorpay_order_id`, `razorpay_payment_id` and `razorpay_signature`.
4. Verify `HMAC_SHA256(order_id + "|" + payment_id, key_secret)` with a constant-time compare.
5. Fetch the payment from Razorpay and confirm `status`, `amount` and `currency` match the order.
6. In one transaction: mark the order paid, insert `payments`, credit the wallet and append the ledger row with `idempotency_key = "order:<order_id>"`.
7. `payment.captured` and `order.paid` webhooks run step 6 again and find it already done.

## Subscriptions

- Create from `products.razorpay_plan_id`. Verify `HMAC_SHA256(payment_id + "|" + subscription_id, key_secret)`.
- Webhooks drive state: `activated`, `charged`, `pending`, `halted`, `cancelled`, `completed`, `paused`, `resumed`, `updated`.
- `charged` grants credits once per payment with `idempotency_key = "subscription-charge:<payment_id>"`.
- Cancellation takes effect at the end of the period.

## Webhooks

1. Read the raw body before parsing and verify `X-Razorpay-Signature` against the webhook secret.
2. Insert into `webhook_events` keyed by the event ID; a duplicate returns 200 without work.
3. Defer processing to the `billing` queue and return 200 quickly.
4. The task applies the state machine; an event older than the current state is stored as `ignored`.

## Refunds

- Admin-initiated, bounded by the refundable amount.
- `refund.processed` marks it done and claws back unused credits proportionally with `idempotency_key = "refund:<refund_id>"`.

## Reconciliation

- Every 15 minutes settle or expire pending orders older than 30 minutes.
- Daily, compare Razorpay settlements with `payments` and report differences.

## Tests

Use the fake Razorpay provider in `PROVIDERS_MODE=fake`. Cover duplicate webhooks, concurrent settlement, out-of-order subscription events, signature failures and partial refunds. Sign test webhooks with `tests/support/signed-webhook.ts`.
