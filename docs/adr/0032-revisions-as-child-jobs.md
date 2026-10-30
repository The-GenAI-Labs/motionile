# 32. Revisions create child jobs

- Status: Accepted
- Date: 2026-10-24
- Refines: [ADR 0021](0021-renders-as-an-aggregate.md)

## Context

Users want to change a finished video ("make the second scene shorter", "explain it for beginners"). Editing a completed job in place would mutate a video that may already be shared or published, make credit accounting ambiguous, and lose the original.

## Decision

- A revision is a new job with `jobs.parent_job_id` set to the original (`ON DELETE SET NULL`, so deleting the original never blocks or removes the revision). The original is never modified.
- The child job runs the full pipeline with the user's instructions and optional scene IDs entering the planner as delimited data, together with the parent's approved storyboard. The planner keeps unchanged scenes verbatim.
- Narration of unchanged scenes is a `tts_cache` hit ([ADR 0022](0022-tts-cache-by-content-hash.md)), so a revision pays for synthesizing only what changed.
- The child has its own estimate, reservation, storyboard versions, render and share links. Only the owner of the parent may revise it.
- Deleting a job removes its renditions from storage; children are unaffected.

## Consequences

- History is an immutable chain; sharing and publishing a version stay stable.
- A revision costs the normal formula ([ADR 0031](0031-predictable-charging.md)) even when little changed; the cache lowers our cost, not the user's price.
