# State machines

Every status column follows an explicit state machine. Services change a status only through a transition function that checks the current state, and every transition is a single `UPDATE ... WHERE id = :id AND status = :expected`, so concurrent writers cannot skip a state. An event that arrives for a transition that is no longer allowed is recorded and ignored, never applied.

Terminal states are marked with `[*]` as an exit.

## `users.status`

```mermaid
stateDiagram-v2
    [*] --> pending_verification: register
    pending_verification --> active: contact verified
    pending_verification --> deleted: abandoned (retention) or deleted by user
    active --> suspended: admin suspends
    suspended --> active: admin reinstates
    active --> deleted: user deletes account
    suspended --> deleted: admin deletes account
    deleted --> [*]
```

- OAuth sign-up with a provider-verified email starts directly in `active`.
- Moving to `suspended` or `deleted` revokes every session with reason `user_suspended` or `logout_all`.
- `deleted` sets `deleted_at`; the row is anonymized or purged by retention.

## `jobs.status`

```mermaid
stateDiagram-v2
    [*] --> queued: created, credits reserved
    queued --> planning: worker picks up
    planning --> awaiting_approval: storyboard ready
    awaiting_approval --> planning: user edits and regenerates
    awaiting_approval --> voicing: user approves
    voicing --> generating: narration ready
    generating --> validating: scenes generated
    validating --> generating: scene repair (at most 2 per scene)
    validating --> rendering: all scenes valid
    rendering --> completed: renditions uploaded
    queued --> cancelled
    planning --> cancelled
    awaiting_approval --> cancelled
    voicing --> cancelled
    generating --> cancelled
    validating --> cancelled
    rendering --> cancelled
    planning --> failed
    voicing --> failed
    generating --> failed
    validating --> failed
    rendering --> failed
    queued --> failed: sweeper gives up
    completed --> [*]
    failed --> [*]
    cancelled --> [*]
```

- MCP jobs (`source = 'mcp'`) skip planning: `queued --> voicing` when only narration is submitted, `queued --> validating` when narration audio already exists.
- `completed` commits the charged credits and releases the rest; `failed` and `cancelled` release the whole reservation.
- `awaiting_approval` jobs expire to `cancelled` after 7 days.

## `orders.status`

```mermaid
stateDiagram-v2
    [*] --> created: order row inserted
    created --> pending: Razorpay order or subscription created
    created --> failed: Razorpay creation rejected
    pending --> paid: payment settled (checkout, webhook or reconciliation)
    pending --> failed: reconciliation finds only failed payments past expiry
    pending --> expired: reconciliation after expires_at
    pending --> cancelled: user abandons checkout
    created --> expired: reconciliation after expires_at
    expired --> paid: late payment
    failed --> paid: late payment
    cancelled --> paid: late payment
    paid --> [*]
    failed --> [*]
    expired --> [*]
    cancelled --> [*]
```

- A captured payment for an `expired`, `failed` or `cancelled` order still settles it: the order moves to `paid` and an audit entry records the late settlement, because the customer was charged. This is the only transition out of those states.
- `payment.failed` never changes the order. Razorpay allows retries on the same order, so the order stays `pending` until it is paid or expires.
- A captured payment whose amount or currency differs from the order is recorded, grants no credits and sets `flagged_at` and `flag_reason`; the order keeps its status, leaves the reconciliation queue and raises an alert. An admin resolves it by refunding the payment.
- A subscription order moves to `paid` when the first `subscription.charged` payment settles.

## `payments.status`

```mermaid
stateDiagram-v2
    [*] --> authorized: payment.authorized
    [*] --> captured: payment.captured seen first
    [*] --> failed: payment.failed
    authorized --> captured: auto-capture
    authorized --> failed: authorization expired
    captured --> partially_refunded: refund processed, amount < total
    captured --> refunded: refund processed, amount = total
    partially_refunded --> partially_refunded: another partial refund
    partially_refunded --> refunded: refunds reach the total
    failed --> [*]
    refunded --> [*]
```

## `subscriptions.status`

```mermaid
stateDiagram-v2
    [*] --> created: subscription created at Razorpay
    created --> authenticated: verify endpoint
    created --> active: activated or charged seen first
    created --> expired: never authorized
    created --> cancelled
    authenticated --> active: subscription.activated or subscription.charged
    active --> active: subscription.charged (grants credits)
    active --> pending: charge failed, retrying
    pending --> active: retry succeeded
    pending --> halted: retries exhausted
    halted --> active: payment method updated and charged
    active --> paused: subscription.paused
    paused --> active: subscription.resumed
    active --> cancelled: period end after cancellation
    pending --> cancelled
    halted --> cancelled
    paused --> cancelled
    authenticated --> cancelled
    active --> completed: all billing cycles done
    cancelled --> [*]
    completed --> [*]
    expired --> [*]
```

- `subscription.updated` changes plan or period fields without changing status.
- A subscription event whose `created_at` is older than `subscriptions.last_event_at` never changes status, period or plan; it is stored with `webhook_events.status = 'ignored'` and `ignored_reason = 'stale'`.
- A `subscription.charged` event is applied in full even when stale: recording the payment and granting credits is idempotent per payment ID, and money received is never ignored. Only its status and period effects are skipped when stale.
- `subscription.cancelled` records `cancelled_at` and `cancel_at_period_end`. The status becomes `cancelled` immediately when there is no paid period left; otherwise it changes when the period ends, through the periodic finalization task, so access lasts to the end of the paid period.
- Every transition is a single `UPDATE ... WHERE status = :expected` checked against this diagram; a transition the diagram does not allow is ignored.

## `refunds.status`

```mermaid
stateDiagram-v2
    [*] --> pending: admin initiates, Razorpay accepts
    pending --> processed: refund.processed
    pending --> failed: refund.failed or API error
    processed --> [*]
    failed --> [*]
```

## `webhook_events.status`

```mermaid
stateDiagram-v2
    [*] --> received: signature verified, stored
    received --> processing: task starts
    processing --> processed: applied
    processing --> ignored: stale, unknown entity or unhandled event type
    processing --> failed: error
    failed --> processing: retry with backoff
    failed --> processing: admin reprocess
    processed --> processing: admin reprocess
    ignored --> processing: admin reprocess
```

- A delivery whose `(provider, event_id)` already exists returns 200 without creating a row; it never reaches this machine again.
- After 10 failed attempts the event stays `failed` and raises an alert.
- Reprocessing is safe because every handler is idempotent.

## `credit_reservations.status`

```mermaid
stateDiagram-v2
    [*] --> active: reserve
    active --> committed: commit (actual up to the reserved amount)
    active --> released: release
    active --> expired: TTL passed, released by the sweeper
    committed --> [*]
    released --> [*]
    expired --> [*]
```

- `commit` consumes the actual amount from lots in expiry order and releases the rest in the same ledger row.
- A repeated call with the same idempotency key returns the original result; any other call on a settled reservation fails with `reservation_not_active`.

## `billing_reconciliation_runs.status`

```mermaid
stateDiagram-v2
    [*] --> running
    running --> completed
    running --> failed
    completed --> [*]
    failed --> [*]
```

## `publications.status`

```mermaid
stateDiagram-v2
    [*] --> draft
    draft --> scheduled: schedule set
    scheduled --> draft: schedule removed
    draft --> publishing: publish now
    scheduled --> publishing: schedule reached
    publishing --> completed: every target published
    publishing --> partially_failed: some targets failed
    publishing --> failed: every target failed
    partially_failed --> publishing: retry failed targets
    failed --> publishing: retry
    draft --> cancelled
    scheduled --> cancelled
    completed --> [*]
    cancelled --> [*]
```

A publication's status is derived from its targets once publishing starts; it is recomputed whenever a target reaches a final state.

## `publication_targets.status`

```mermaid
stateDiagram-v2
    [*] --> pending
    pending --> uploading: task starts
    uploading --> publishing: media uploaded
    uploading --> failed: upload rejected
    publishing --> published: post created
    publishing --> unknown: timeout or ambiguous error
    unknown --> published: fetch_status finds the post
    unknown --> failed: fetch_status confirms no post
    failed --> pending: user retries
    pending --> cancelled: publication cancelled
    published --> [*]
    cancelled --> [*]
```

- The post-creation call is never retried from `publishing` or `unknown`; only `fetch_status` resolves `unknown`, which prevents duplicate posts.

## `skill_versions.scan_status`

```mermaid
stateDiagram-v2
    [*] --> pending: version uploaded
    pending --> passed: scanner found nothing
    pending --> flagged: scanner found a policy issue
    flagged --> passed: admin overrides after review
    passed --> [*]
```

- Only a `passed` version can become a skill's `current_version_id` or be used in a generation.
- `flagged` versions stay unusable until an admin review; the override is audited.
