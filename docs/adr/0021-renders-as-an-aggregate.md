# 21. Renders are their own aggregate

- Status: Accepted
- Date: 2026-10-19
- Refines: [ADR 0009](0009-narration-first-generation-pipeline.md)

## Context

The first blueprint attached `renditions` to `jobs`. Phase 8 must prove the render and audio engine before any AI exists: an admin submits a composition and narration and gets MP4s back. The MCP path submits a finished composition without a storyboard. Tying output to a job would force a job row, a credit reservation and a storyboard into a test of the engine, and would make the render pipeline unable to run without Phase 9.

## Decision

- A render is an aggregate with its own table, `renders`, owned by a user and created with a `source`: `testbed`, `job` or `mcp`.
- A render holds everything the pipeline needs and produces: options, the composition asset, the mixed audio asset, subtitle tracks, the validation report, per-stage timings, checkpoints, status, stage and progress, and the error.
- `renditions` reference `render_id` instead of `job_id`. Phase 9 sets `jobs.render_id`; jobs and MCP submissions create renders through `create_render` in `motionile.modules.media` and read renditions through `renditions_for`.
- Credits stay outside the render. A job reserves and commits through `motionile.modules.credits`; a test-bed render charges nothing. The media module never touches credit tables.
- `share_links` moves to Phase 9 because sharing belongs to a finished job.
- The pipeline runs as one `render.run` task on the `render` queue. Each stage records a checkpoint on the render, and the task resumes at the first incomplete stage after a retry.
- Progress is published to the Redis channel `render:<id>`; Phase 9's job stream consumes it.

## Consequences

- The engine is exercised end to end without AI, billing or a job, and the admin test bed is a real consumer of the interface Phase 9 will use.
- A job and a render are two rows with two lifecycles; Phase 9 maps render states into job states.
- Deleting a user cascades through renders and renditions; the purge job deletes storage objects first.
