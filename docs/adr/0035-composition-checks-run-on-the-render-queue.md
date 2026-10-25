# 35. Composition checks run on the render queue

- Status: Accepted
- Date: 2026-10-25
- Refines: [ADR 0026](0026-render-sandbox-design.md), [ADR 0034](0034-generation-queue-for-long-running-graphs.md)

## Context

The `validate` and `visual_review` steps of the generation graph need the Phase 8 sanitizer, the sandbox and the validator, and `visual_review` needs sampled frames. The sandbox needs Chromium. The API and generation worker images carry ffmpeg but no browser: only the render worker image has Chromium with its seccomp profile, non-root user and minimal environment ([ADR 0026](0026-render-sandbox-design.md)). Adding the browser to the generation image would widen the attack surface of the process that holds the model keys and the database credentials with a component that runs untrusted code.

## Decision

- The graph never opens a browser. A composition check is a task `media.check_composition` on the `render` queue. The submitter (`modules/generation`, behind the `CompositionCheckGateway` port) writes the input to private storage under `work/jobs/<jobId>/checks/<checkId>/request.json`, defers the task and polls the same prefix for `result.json` every second until the stage timeout.
- The input holds the composition HTML, the narration document, the aspects and whether frames are wanted. `checkId` is the SHA-256 of those four values, so the same composition always maps to the same prefix: a retried graph node finds the stored result, and a duplicate deferral is dropped by a queueing lock on the check ID. The task recomputes the ID from the stored request and refuses a mismatch.
- The task runs exactly what `modules/media/pipeline` runs for a render: `sanitize_composition`, then a `RenderSandbox` and `validate_composition` for every aspect, with the explicit browser environment and a stage timeout, and the sandbox is closed on every path. When frames are wanted it renders each scene at 25 % and 75 % of its time in each aspect, downscales the PNG with Pillow to at most 768 pixels wide and stores it next to the result. A sandbox failure (page error, network violation, timeout, crash) is recorded as an error issue in the report instead of failing the task, so the repair loop sees it.
- `result.json` is written last, after the frames, so its existence means the result is complete. It holds the engine's `ValidationReport` and the frame manifest, never prompts, keys or secrets. The objects live under `work/`, which the CDN never serves, and the bucket lifecycle rule expires them after seven days.
- Infrastructure errors in the task propagate and procrastinate retries it. A task that never finishes ends as a submitter timeout, which fails the graph node and lets the generation task retry.

## Consequences

- The browser stays in the one image built and hardened for it; the generation worker needs no browser, no seccomp profile and no extra memory.
- Every check pays a queue hop and a browser start (a few seconds); the loop of `compose → validate → visual_review → repair` is bounded by `ai.max_repairs`, so the extra latency is bounded as well.
- Render workers carry the validation load of generation. Render capacity and generation capacity scale independently but share the render queue, so a deployment sizes the render workers for both.
- Check inputs and results are readable by operators with bucket access for up to seven days, like other work objects.
