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
    queued --> voicing: MCP job with narration text only
    queued --> validating: MCP job with narration audio
    planning --> awaiting_approval: storyboard ready, review requested
    planning --> voicing: storyboard ready, review not requested
    awaiting_approval --> planning: user edits and regenerates
    awaiting_approval --> voicing: user approves
    voicing --> generating: narration ready
    generating --> validating: scenes generated
    validating --> generating: scene repair (at most ai.max_repairs per scene)
    validating --> rendering: all scenes valid
    rendering --> completed: renditions uploaded
    queued --> cancelled
    planning --> cancelled
    awaiting_approval --> cancelled
    voicing --> cancelled
    generating --> cancelled
    validating --> cancelled
    rendering --> cancelled
    awaiting_approval --> failed: approved but the resume never ran
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
- A job whose `options.reviewStoryboard` is off goes from `planning` straight to `voicing`; otherwise it waits in `awaiting_approval`, and a regeneration returns it to `planning`.
- Cancellation is allowed from every non-terminal state. `awaiting_approval` ends by approval, regeneration, cancellation or the approval timeout, which cancels; it fails only when the storyboard was approved and the resume task never ran within `ai.stage_timeout_minutes`, which the stalled-job sweeper detects with the `job_stalled` code.
- `modules/generation/domain.py` (`JOB_TRANSITIONS`) is the code form of this diagram; a unit test compares the two.
- `completed` commits the charged credits and releases the rest; `failed` and `cancelled` release the whole reservation.
- `awaiting_approval` jobs expire to `cancelled` after 7 days.

## `scenes.status`

```mermaid
stateDiagram-v2
    [*] --> pending: scene row created from the approved storyboard
    pending --> voiced: narration synthesized, duration and word timings stored
    voiced --> generated: scene module generated, or the fallback built
    generated --> validated: composition checks pass for the scene
    validated --> generated: scene repaired after a later check
    generated --> generated: scene repaired
    pending --> failed
    voiced --> failed
    generated --> failed
    validated --> failed
    validated --> [*]
    failed --> [*]
```

- Scene rows exist only for the approved storyboard version and are created when voicing starts, so every row starts at `pending`.
- A repair increments `repair_attempts` (at most `ai.max_repairs`, itself at most 3) and appends to `attempt_log`; reaching the limit replaces the module with the fallback scene and sets `is_fallback`. A fallback scene follows the same path as any other scene.
- `failed` is reserved for a scene that cannot be voiced or whose fallback still has blocking issues; it fails the job with `error_code` copied to the scene.

## `eval_runs.status`

```mermaid
stateDiagram-v2
    [*] --> running: run started
    running --> finished: scores computed, passed set
    running --> errored: infrastructure or dataset error
    finished --> [*]
    errored --> [*]
```

- `passed` is null until the run is `finished`; an `errored` run never counts toward activation and never has `passed`.
- `finished_at` is set exactly when the run leaves `running`.
- Activation of a prompt version requires, for every suite required for its template, a `finished` row with `passed = true` whose `prompt_version_ids` contain the version.

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
    created --> paid: payment settled before the order was marked pending
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
- A second captured payment for an order that is already `paid` is recorded without credits and flags the order `duplicate_payment`; the order keeps its status and an alert is raised. An admin resolves it by refunding the extra payment.
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
    active --> halted: pending event missed or out of order
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
- A transition to the state the subscription is already in is a no-op recorded as `processed`; a transition the diagram does not allow is recorded as `ignored` with reason `invalid_transition` and never applied.
- `subscription.activated` after the subscription already left `created` and `authenticated` is a no-op recorded as `processed`: a `charged` event that arrived first has already activated it.
- Period fields only move forward: an event or sync whose `current_end` is older than the stored one leaves them alone.
- A subscription that leaves a live status needs no further events: `cancelled`, `completed` and `expired` rows no longer count toward the one-live-subscription-per-user index, so a new subscription can be started.
- A `charged` event for a subscription that already ended (`cancelled`, `completed`, `expired`) still records the payment and grants the credits, leaves the status alone and raises an alert.
- A subscription left in `created` by reordered events (for example an activation older than an already applied update) is repaired by the daily sync, which also covers `created` subscriptions that already have a Razorpay ID.
- The daily subscription sync and the finalization task use the same machine; when Razorpay is further along than a webhook told us, the sync walks the shortest path of allowed transitions to the Razorpay state and never moves a subscription backwards.
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

- A delivery whose `(provider, event_id)` already exists returns 200 without creating a row; it never reaches this machine again. A duplicate whose stored row is still `received` after 60 seconds is queued again.
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
    failed --> running: settlement run resumed
    completed --> [*]
```

- A `settlement` run is unique per UTC day. A `failed` run, or a `running` run older than one hour, is resumed by the next attempt; a `completed` run is never repeated.

## `renders.status`

```mermaid
stateDiagram-v2
    [*] --> queued: created
    queued --> preparing: worker picks up
    preparing --> voicing: composition sanitized and validated
    voicing --> mixing: narration synthesized or uploaded
    mixing --> capturing: audio mixed
    capturing --> encoding: frames captured
    encoding --> finalizing: video segments joined and muxed
    finalizing --> completed: renditions uploaded
    queued --> cancelled
    preparing --> cancelled
    voicing --> cancelled
    mixing --> cancelled
    capturing --> cancelled
    encoding --> cancelled
    finalizing --> cancelled
    preparing --> failed
    voicing --> failed
    mixing --> failed
    capturing --> failed
    encoding --> failed
    finalizing --> failed
    queued --> failed: sweeper gives up
    completed --> [*]
    failed --> [*]
    cancelled --> [*]
```

- Completing a stage records its checkpoint and moves the status to the next stage in one transaction, so the status always names the first incomplete stage. A retried task resumes there and never repeats a checkpointed stage.
- The pipeline keeps frame and per-aspect checkpoints inside `capturing` and `encoding`; they live in storage under `work/renders/<id>/` and are named in `checkpoints`.
- Deterministic failures (`network_violation`, `timeout`, `validation_failed`, `page_error`, `unsupported_composition`) end in `failed` immediately. Infrastructure failures raise, the task retries and resumes; the sweeper fails a render whose `updated_at` has not moved for the stall limit.
- Cancellation sets `cancel_requested_at`; the worker stops between frames and moves the render to `cancelled`.

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
