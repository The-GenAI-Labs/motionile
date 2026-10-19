# 18. Credit lots and reservations

- Status: Accepted
- Date: 2026-10-17
- Refines: [ADR 0004](0004-razorpay-billing-with-credit-ledger.md)

## Context

ADR 0004 introduced a wallet with an append-only ledger. A single balance cannot express that subscription credits expire at the end of their billing period while purchased credits do not, that a refund must take back only what its payment granted, or that jobs, publishing and MCP submissions all need to hold credits before they know the final cost.

## Decision

- Credits live in **lots** (`credit_lots`): a source (`purchase`, `subscription`, `admin`, `promo`), an amount, a remaining amount, an optional expiry and a reference to the payment, admin action or promotion that created it.
- Credits are consumed from lots in order of soonest expiry, non-expiring lots last, with `created_at` and `id` as tie-breakers.
- A refund claws back only from the lot its payment created, and only what remains unused: `min(lot.remaining, ceil(credits_granted × refund_amount ÷ payment_amount))`.
- Subscription credits expire at the end of their billing period. The runtime setting `billing.subscription_rollover` switches new subscription lots to non-expiring.
- **Reservations** (`credit_reservations`) are the one mechanism for holding credits for jobs, publishing and MCP submissions. A reservation moves `reserved` on the wallet without touching lots. `commit` consumes the actual amount from lots and releases the rest; `release` returns everything; a sweeper releases reservations past their TTL. A reservation names its purpose with `ref_type` and `ref_id`.
- The ledger records both `delta` (balance change) and `reserved_delta` (reservation change) with `balance_after` and `reserved_after`. At least one delta is non-zero, and the signs of both are fixed per reason by a check constraint.
- **Invariant:** per user, the sum of ledger deltas equals the wallet balance and the sum of lot remainders; the sum of reserved deltas equals the reserved amount and the sum of active reservations. A nightly task verifies it for every wallet and alerts on a mismatch.
- Every operation locks the wallet row first, then the lots it touches in `expires_at NULLS LAST, created_at, id` order, so concurrent operations cannot deadlock.
- Every operation takes an idempotency key that is the ledger row's unique key; repeating it returns the original result.
- Credits held by an active reservation are never expired or clawed back below the reserved amount; those operations are limited to `balance - reserved` and the remainder waits for the next sweep.
- An admin deduction never takes the balance below the reserved amount or below zero.

## Consequences

- Expiry, refunds and consumption are explainable lot by lot and rebuildable from the ledger.
- A refund of a spent pack claws back less than it refunds; that is intended, and the refund record shows the credits actually recovered.
- Lots add a table and a locking step to every credit write; the wallet row lock serializes a single user's operations, which is the correct granularity.
- Later phases reserve, commit and release through `motionile.modules.credits` and never touch these tables.
