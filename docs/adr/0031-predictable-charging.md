# 31. Predictable charging

- Status: Accepted
- Date: 2026-10-24
- Refines: [ADR 0018](0018-credit-lots-and-reservations.md)

## Context

A generation costs the platform a variable amount: model tokens, repairs, narration characters, render time. Charging the user that variable amount would make the price unknowable before they commit and would expose them to our model failures.

## Decision

- Credits are charged by a published formula whose parameters live in platform settings (`charging.*`):

  ```
  subtotal = base + per_second × seconds
  total    = ceil(subtotal × (100 + extra_aspect_percent × (aspects − 1)) / 100) + cloned_voice_premium
  ```

  `seconds` is the target duration for the estimate and the final video duration (rounded up to whole seconds) for the charge. The premium applies only when the selected voice is a cloned voice.

- `POST /v1/jobs/estimate` and `POST /v1/jobs` use the same function. The reservation equals the estimate. The charge is `min(formula(final duration), reservation)`, so it never exceeds what was reserved; the remainder is released.
- Failed and cancelled jobs release the whole reservation.
- True provider costs (tokens, characters, render time) are recorded in `usage_records` for margin analytics. They never change what the user pays.
- Revisions are new jobs with their own estimate and reservation ([ADR 0032](0032-revisions-as-child-jobs.md)).

## Consequences

- The user knows the price before submitting and never pays more than the estimate.
- Margin risk (a video that costs more than it charges) is ours and visible in the admin analytics (average cost versus credits charged), and is tuned by changing settings, not code.
- A final video shorter than the target costs less than the estimate.
