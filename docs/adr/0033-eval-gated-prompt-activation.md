# 33. Evals gate prompt activation

- Status: Accepted
- Date: 2026-10-24
- Refines: [ADR 0009](0009-narration-first-generation-pipeline.md)

## Context

A prompt change can silently degrade accuracy, pacing, safety or cost. Prompts live in the database so admins can roll back without a deploy, which also means a bad edit could reach users immediately.

## Decision

- System prompts are authored as files under `engine/ai/prompts/system/`. A seed command run after migrations syncs them into `prompt_templates` and `prompt_versions`: a changed checksum creates a new draft version and nothing is ever activated by the seed.
- Evaluation results are rows in `eval_runs`: suite, dataset version, the prompt version IDs under test, the model configuration, scores, whether the run passed, the trigger (`ci`, `nightly`, `admin`) and start and finish times.
- A prompt version can be activated only when, for every suite required for its template, a finished and passing `eval_runs` row covers that version. Rollback activates the previous version without a new run, because it passed one when it was first activated.
- Thresholds live in `apps/server/evals/thresholds.yaml`. A regression below any threshold fails the run and, in CI, the pipeline.
- Admins start runs from the console; they execute on staging as a task with the same suites CI uses.

## Consequences

- No prompt reaches production traffic without a recorded passing run.
- Live evals cost money; pull requests run deterministic checks and replayed recordings, and a small live subset only when AI files change, within the budget in settings.
- The required-suite mapping is code and changes with the prompt keys.
