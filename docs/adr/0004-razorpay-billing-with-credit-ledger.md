# 4. Razorpay billing with an append-only credit ledger

- Status: Accepted
- Date: 2026-10-13

## Context

Motionile sells subscriptions and one-time credit packs, primarily to customers in India, and every generation consumes credits. Money and balances must be correct under retries, duplicate webhooks, concurrent requests and partial refunds, and every balance must be explainable.

## Decision

- Payments use Razorpay orders, subscriptions and refunds through its REST API.
- Prices live only in the `products` table; the client never sends an amount.
- Money is stored as `bigint` paise and credits as `bigint`.
- Every credit change appends one row to `credit_ledger` with `balance_after` and a unique `idempotency_key`, in the same transaction as the wallet update.
- Checkout verification and webhooks share one idempotent settlement path. Webhooks are verified on the raw body, stored, deduplicated by event ID and processed on the `billing` queue.
- Status changes follow explicit state machines; stale events are recorded as `ignored`.
- Generation reserves credits up front, commits the actual cost on completion and releases the rest.

## Consequences

- Balances can be audited and rebuilt from the ledger.
- Retries and duplicate events are safe by construction.
- The ledger grows without bound and needs indexing and archival planning.
- Switching providers later means a new adapter, not a new money model.
