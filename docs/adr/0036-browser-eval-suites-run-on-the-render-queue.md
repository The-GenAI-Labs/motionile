# 36. Browser eval suites run on the render queue

- Status: Accepted
- Date: 2026-10-29
- Refines: [ADR 0033](0033-eval-gated-prompt-activation.md), [ADR 0035](0035-composition-checks-run-on-the-render-queue.md)

## Context

Admins start eval runs from the console and a prompt version can be activated only when every required suite has a passing run that covers it ([ADR 0033](0033-eval-gated-prompt-activation.md)). The `scenes` and `sync` suites compose scene modules and load them in the Chromium sandbox. The generation worker runs from the API image, which has no browser and must not get one ([ADR 0035](0035-composition-checks-run-on-the-render-queue.md)), so these two suites could not run there and no scene prompt could ever be activated from the console.

## Decision

- The suite decides the queue, in one table (`EVAL_QUEUE_BY_SUITE` in `modules/prompts/domain.py`) read by `EvalRunService.start`. `planner`, `safety` and `cost` stay on the `generation` queue as task `prompts.run_eval`. `scenes` and `sync` run as task `prompts.run_eval_browser` on the `render` queue, registered next to the first in `modules/prompts/tasks.py`. Both tasks call the same runner and the same installed `EvalExecutor`.
- The render worker image carries `evals/` (without the cassettes) and `PYTHONPATH=/app`, like the API image. `worker-render` receives only the variables an eval needs and nothing else beyond them: `AI_ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `AI_LANGFUSE_PUBLIC_KEY`, `AI_LANGFUSE_SECRET_KEY`, `AI_LANGFUSE_HOST`, `EMBEDDING_MODEL` and `EMBEDDING_DIMENSIONS`. In production they are optional, so the render worker still starts without them and `Settings.deployment_problems()` for `APP_ROLE=render_worker` is unchanged.
- The executor fails the run with `eval_keys_missing` when a provider key is absent in its process. Chromium keeps the explicit minimal environment from `RenderEngineConfig.browser_environment` (`PATH`, `HOME`, the temp directories and the fixed locale), so the keys never reach the browser; a unit test asserts it.
- `eval_browser_unavailable` remains the error for a browser suite started where a browser cannot launch, for example a local run without Chromium. It no longer describes any admin run.

## Consequences

- Every suite required by [ADR 0033](0033-eval-gated-prompt-activation.md) can be run from the console, so scene prompts and the vision review prompt can be activated.
- The render worker now holds model keys. It already runs untrusted compositions, so the keys are exposed only to the Python process, never to the browser, and the browser is the part that touches untrusted code. Deployments that do not want keys there leave them unset; admin runs of the two browser suites then end as `eval_keys_missing`.
- Eval runs share the render queue with renders and composition checks. A live `scenes` run lasts minutes and occupies a render worker slot, so render capacity must account for it.
