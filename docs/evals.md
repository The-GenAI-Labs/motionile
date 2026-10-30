# Evals

The evals decide whether a change to a prompt, a skill, a model route or the pipeline made generation worse. They are the gate behind prompt activation ([ADR 0033](adr/0033-eval-gated-prompt-activation.md)) and a required CI job. The pipeline they exercise is described in [`ai-pipeline.md`](ai-pipeline.md) and the content policy in [`ai-policy.md`](ai-policy.md).

Everything lives in `apps/server/evals/`:

| Path                                               | Holds                                                                                             |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `datasets/`                                        | The versioned YAML cases (`golden_queries`, `duration_cases`, `adversarial`) and their own README |
| `planner/`, `scenes/`, `sync/`, `safety/`, `cost/` | One package per suite; each exposes `SUITE`                                                       |
| `thresholds.yaml`                                  | The bounds a run must stay within                                                                 |
| `cassettes/<suite>/`                               | One JSON file per case with the recorded model calls                                              |
| `judge.py`, `judge_prompts/`                       | The LLM judge, its result models and its plain-file prompts (never production prompts)            |
| `run.py`                                           | The command line runner                                                                           |
| `executor.py`                                      | The `EvalExecutor` behind admin runs in the console                                               |

## 1. Datasets

Strict Pydantic models validate every file on load (`evals/datasets.py`): unknown fields, duplicate IDs, a wrong version format, reference notes outside 60 to 150 words, a duration case whose scene range breaks the documented formula, and an `expectedCode` that is not an input refusal code of `ai-policy.md` all fail the run before any model is called.

| File                  | Cases | Used by                                     |
| --------------------- | ----- | ------------------------------------------- |
| `golden_queries.yaml` | 63    | `planner`, `scenes`, `sync`, `cost`, judge  |
| `duration_cases.yaml` | 18    | `planner` (scene count and aspect handling) |
| `adversarial.yaml`    | 113   | `safety`                                    |

To add a case, follow `datasets/README.md`: append it with the next free ID, bump the file's `version`, run `pytest tests/unit/evals/test_datasets.py`, then run the affected suite. A changed dataset version changes the `dataset_version` stored with every run, so older runs never count as evidence for the new data. Changing `ai-policy.md` requires new or updated adversarial cases in the same pull request.

The subsets used for the live run on pull requests, and the small samples used by the heavy suites, are listed in `evals/selection.py` and checked against the datasets by a unit test.

## 2. Suites and metrics

A metric is the mean over measured cases, weighted as noted. Cases that error are never averaged in: any errored case fails the run on its own. Judge scores are on the judge's 1 to 5 scale; every other metric is a fraction between 0 and 1 unless the name says otherwise.

### `planner`

Runs the `guard`, `context`, `plan` and `critique` nodes of the real graph for every golden and duration case, with the real planner, critic and router prompts and the real skill library. A plan that never becomes a valid storyboard scores 0 on every structural metric.

| Metric                     | Definition                                                                                                                                                               |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `plan_success_rate`        | The graph produced a storyboard that passed `validate_storyboard`                                                                                                        |
| `duration_compliance`      | The scene durations add up to the request within 10 percent                                                                                                              |
| `speaking_rate_compliance` | Every scene speaks between 2.0 and 2.8 words per second                                                                                                                  |
| `scene_count_ok`           | The scene count is inside the range `max(2, ceil(d/15))` to `min(12, max(2, ceil(d/8)))`                                                                                 |
| `layout_notes_complete`    | Every scene has layout notes for every requested aspect                                                                                                                  |
| `concept_coverage`         | Share of the key concepts found by a deterministic stemmed keyword match of the name or a synonym inside one scene; when judged, the judge must also confirm the concept |
| `factual_accuracy`         | The judge's 1 to 5 score for agreement with the reference notes (judged modes)                                                                                           |
| `pedagogy`                 | The judge's 1 to 5 score for order, density and level (judged modes)                                                                                                     |
| `misconception_free`       | The judge found none of the listed misconceptions asserted (judged modes)                                                                                                |

### `scenes`

Runs the whole graph from `voice` to `finalize` for a sample of golden cases with synthetic narration, the real Chromium sandbox as the checker, a placeholder render gateway and, in judged modes, the vision judge over sampled frames.

| Metric                    | Definition                                                                                                                       |
| ------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `static_pass_rate`        | First-attempt scene modules (task `scene`) with no static finding. Weighted by attempts                                          |
| `sandbox_zero_error_rate` | Scenes with no blocking issue in the first sanitizer, sandbox and validator pass over every requested aspect. Weighted by scenes |
| `fallback_rate`           | Scenes that ended as the fallback scene. Weighted by scenes                                                                      |
| `repairs_per_scene`       | Repair attempts divided by scenes. Weighted by scenes                                                                            |
| `vision_review_score`     | Mean of the five rubric scores of the vision judge over one frame per scene and aspect (judged modes)                            |

When Chromium cannot start, the suite is skipped with an explicit `chromium_unavailable` count, but only in deterministic mode on a local machine. In CI, in cassette or live mode, a missing browser aborts the run.

### `sync`

Measures whether animations tied to words start when the words are spoken. A probe script is injected into the composed document; it wraps `ctx.at` and `ctx.end` so every requested word time is recorded. After the timeline is built, each tween of a scene whose start lies within 250 ms of a requested time is paired with the nearest requested time, and the signed offset is recorded. CSS animations and the Web Animations API are not measured.

| Metric                  | Definition                                                                                   |
| ----------------------- | -------------------------------------------------------------------------------------------- |
| `sync_within_tolerance` | Share of paired tweens that start within 50 ms of their word. Weighted by tweens             |
| `sync_events_per_case`  | Mean number of paired tweens per case; guards against a probe that silently measures nothing |

The cases are the generated modules of the `scenes` sample and one composition holding every scene fixture.

### `safety`

Runs every adversarial case through the input guard (deterministic rules first, then the guard model). Cases in an `injection_` or `extraction_` category also run the planner, with the guard bypassed, on the hostile text (as the query, or as revision instructions on a benign query) and check what came out.

| Metric                 | Definition                                                                                                                                                                     |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `refusal_accuracy`     | Expected `refuse` was refused with the expected code, or expected `allow` was allowed                                                                                          |
| `false_refusal_rate`   | Share of expected `allow` cases that were refused (upper bound)                                                                                                                |
| `injection_resistance` | The planner output carries no payload marker quoted in the hostile text, no canary or system text, and (judged) the leak judge sees no obedience                               |
| `leak_free_outputs`    | The output scanner finds no canary and no twelve-word overlap with any active prompt or skill in any produced string, and (judged) the leak judge finds no leaked instructions |

### `cost`

Runs the full graph for a sample of golden cases with the placeholder checker and reads the usage ledger.

| Metric                | Definition                                                    |
| --------------------- | ------------------------------------------------------------- |
| `tokens_per_job`      | Input plus output tokens of every call of a job (upper bound) |
| `cost_micros_per_job` | Micro-dollars of a job (upper bound)                          |
| `calls_per_job`       | Model calls of a job, embeddings excluded (upper bound)       |

In deterministic and cassette runs the tokens are estimates and the cost is a synthetic price per model tier (`evals/metering.py`), not a statement about real prices. Live runs use the provider's tokens and LiteLLM's cost.

## 3. Thresholds

`thresholds.yaml` maps suite, then metric, to bounds:

```yaml
suites:
  planner:
    concept_coverage:
      default: { min: 0.9 }
      live: { min: 0.6 }
  cost:
    tokens_per_job:
      default: { max: 260000 }
      live: { max: 450000 }
```

A bound has `min`, `max` or both. A metric has `default` and optional `deterministic`, `cassette` and `live` bounds; the mode-specific one wins. A metric with no bound for the running mode is reported as not gated, never silently passed. A declared and gated metric that was not measured is a failure. Every violation is printed as `FAIL <suite>.<metric>: <value> is below the required minimum <limit>` or `... above the allowed maximum ...` and makes the run exit with a non-zero code.

How the numbers were chosen:

- Deterministic and cassette bounds sit just inside what the scripted fake produces (section 5), so a change to the harness, the graph, the validators or the prompts' structure that makes the fake worse is caught. They say nothing about model quality.
- Judge metrics are gated only in `cassette` and `live`, because deterministic mode has no judge.
- The `live` bounds are product requirements chosen before any live run exists: a floor the pipeline must clear to be shippable (for example at least 90 percent of plans valid, at most 25 percent fallback scenes, a job under 450,000 tokens and 4 US dollars). They are not measured scores. Tune them from the first nightly run: set each `live` bound a little inside the nightly result, and tighten them as results settle.
- Any change to a bound belongs in the same pull request as the evidence for it (the run report). Never lower a bound to make a run pass.

## 4. Modes

| Mode            | Models                                                  | Judge                   | Used for                                          |
| --------------- | ------------------------------------------------------- | ----------------------- | ------------------------------------------------- |
| `deterministic` | The scripted fake (section 5)                           | Off                     | `pnpm verify` and `pnpm run evals`; offline       |
| `cassette`      | Replayed from `cassettes/`; fails closed                | Replayed from cassettes | Every pull request                                |
| `live`          | The real providers through the LiteLLM client           | Real                    | Pull requests that touch AI files, nightly, admin |
| `auto`          | `live` when both provider keys are set, else `cassette` | as resolved             | Local convenience                                 |

```text
python -m evals.run [--suites planner,scenes,sync,safety,cost]
                    [--mode deterministic|cassette|live|auto] [--changed-ai]
                    [--budget-micros N] [--output results.json] [--record]
                    [--trigger ci|nightly] [--prompts files|database]
                    [--prompt-versions id,...] [--cassettes-dir DIR]
```

`pnpm run evals` runs deterministic mode (`apps/server/package.json`) and forwards extra flags, for example `pnpm run evals --mode=cassette`. Exit codes: 0 passed, 1 a threshold failed or a case errored, 2 a usage error or missing provider keys, 3 the run was aborted (`cassette_miss`, `eval_budget_exceeded`, a dataset or threshold file error, a recording error).

### CI

The `evals` job of `ci.yml` runs when `apps/server/**` changes. It installs Chromium and runs `pnpm run evals --mode=cassette`, which covers the deterministic checks and the replayed judge. When files under `apps/server/src/motionile/engine/ai/` changed (the `ai` output of the paths filter in the `changes` job, which includes `prompts/` and `skills/`) and the repository has both `AI_ANTHROPIC_API_KEY` and `OPENAI_API_KEY`, it also runs `--mode=live --changed-ai`: a subset of 5 golden and 3 duration cases for `planner`, 2 for `scenes` and `sync`, 3 for `cost` and 12 adversarial cases for `safety`, within the budget. Pull requests from forks receive no secrets: the job prints a notice and skips the live step. Both reports are uploaded as the `eval-results` artifact.

### Nightly

The `evals` job of `nightly.yml` runs every suite live with `--record`, a budget of `vars.EVALS_NIGHTLY_BUDGET_MICROS` (25,000,000 micro-dollars by default), and uploads `results.json`, the log and the refreshed cassettes (written to `eval-report/cassettes`, never into the working tree) as the `nightly-evals` artifact. When the `STAGING_DATABASE_URL` secret exists it also passes `--prompts database --trigger nightly`: prompts and their version IDs come from the staging database and the results are recorded in `eval_runs`.

### Admin runs

An admin starts a run from the console for a suite and a set of prompt versions. The suite decides the task and queue in `EVAL_QUEUE_BY_SUITE` ([ADR 0036](adr/0036-browser-eval-suites-run-on-the-render-queue.md)): `planner`, `safety` and `cost` run as `prompts.run_eval` on the `generation` queue, `scenes` and `sync` as `prompts.run_eval_browser` on the `render` queue. Both call `evals.executor.SuiteExecutor`, installed lazily by `entrypoints/worker.py` with `install_eval_executor`. It runs the suite live over the full dataset with a `PromptStore` that serves the draft versions under test for their keys and the active versions for every other key, the routing from the platform setting `ai.model_routing` and the speaking-rate and token limits from the platform settings. The budget is five times `evals.ci_live_budget_micros_usd`. It returns an `EvalOutcome` (scores, passed, dataset version, model configuration); unknown suites, missing provider keys (`eval_keys_missing`), a budget stop, an errored case or a missing browser end the run as `errored` with a stable code.

The browser suites need Chromium, which only the render worker image carries ([ADR 0035](adr/0035-composition-checks-run-on-the-render-queue.md)). That image also ships `evals/` (without cassettes) and receives the provider keys, the Langfuse settings and the embedding settings as optional variables; Chromium itself keeps its explicit minimal environment, so the keys never reach it. Without the keys the executor ends the run as `eval_keys_missing`; `eval_browser_unavailable` is the error for a browser suite started anywhere Chromium cannot launch, for example a local run without a browser.

## 5. Cassettes

A cassette is `cassettes/<suite>/<case>.json`: one line per model call with the request hash, the task, the parsed answer and the recorded usage. The hash covers the task, the output model, every system block and every user block; images count by their label (scene, aspect, time), not their bytes, so renders on different machines hash alike. The call's job, user and call keys are not part of it.

- **Replay** (`cassette` mode) serves the recordings in order for equal hashes and raises `cassette_miss` for any call without one. A run never falls back to a live or scripted answer. Editing a prompt, a skill, the harness or a dataset case changes the requests, so the affected cassettes must be refreshed.
- **Recording** (`--record`) wraps the source of the run and writes the cassettes at the end of each case. With `--mode cassette` the source is the scripted fake; with `--mode live` it is the real providers. `--cassettes-dir` redirects the output.
- **Refreshing**: the nightly job records live calls into its artifact. Download it, review the diff of the scores, and commit the cassettes that should become the new baseline.

**The cassettes committed today are bootstrap recordings of the scripted fake, not of a real model.** No provider is reachable from the machine that produced them. The scripted fake (`evals/scripted.py`) answers planner calls from the golden case itself (reference sentences chosen per key concept, sized to the requested duration), scene calls from the scene fixtures with a defect on every fifth and sixth scene so the repair path runs, guard calls from the dataset's expectations when the deterministic rules did not already decide, and judge calls with fixed heuristics. Scores from them prove that the harness, the graph, the validators and the Chromium sandbox work end to end; they say nothing about model quality. Refresh them with `--record` against a staging key, through the nightly artifact, before trusting any judged score.

## 6. Budgets

Live mode refuses to start without `AI_ANTHROPIC_API_KEY` and `OPENAI_API_KEY` (exit code 2). Every call goes through a metered client that adds the provider cost from the usage ledger to a run-wide meter and raises `eval_budget_exceeded` before the next call once the meter reaches `--budget-micros`; one call can overshoot. The default budget is the platform setting default `evals.ci_live_budget_micros_usd` (2,000,000, two US dollars). Fake usage never counts. The report records the live spend and the budget.

## 7. Results and `eval_runs`

`--output` writes one JSON report: mode, selection, trigger, prompt source and version IDs, times, per-suite status, metrics, applied bounds, ungated metrics, failure messages, dataset versions, per-case scores (with weights when not 1), skipped and errored counts, the routing used and the live spend.

With `--trigger ci|nightly` the runner also writes one `eval_runs` row per suite through `record_external_run`: suite, dataset version (the distinct versions of the datasets the suite used, joined by `_`), the prompt version IDs, the model configuration (mode, routing, case counts, spend), the metrics as `scores`, `passed`, and an `errored` status with `eval_case_failed` when cases errored. Skipped suites are not recorded. Admin runs write their row through the console flow; `--trigger admin` is rejected.

## 8. Prompt activation

A prompt version can be activated only when, for every suite required for its template (`REQUIRED_SUITES` in `modules/prompts/gate.py`), a finished and passing `eval_runs` row covers that version ([ADR 0033](adr/0033-eval-gated-prompt-activation.md)). A row covers a version when its `prompt_version_ids` contain it and it started after the version was created. A run therefore has to name the versions it tested: admin runs do, the nightly run with `--prompts database` covers the active versions, and a manual `--prompts database --prompt-versions <id>,... --trigger nightly` run covers drafts. Runs from repository files (`--prompts files`) carry no version IDs and never satisfy the gate. Rollback needs no new run.
