# AI pipeline operations

How to run, tune and troubleshoot the generation pipeline in staging and production. The design is in [`../ai-pipeline.md`](../ai-pipeline.md); the checks that gate prompts are in [`../evals.md`](../evals.md).

## 1. What runs where

| Service             | Image              | Work                                                                                        |
| ------------------- | ------------------ | ------------------------------------------------------------------------------------------- |
| `worker-generation` | `motionile-api`    | `generation.run_job`, `generation.resume_job`, the sweepers and `prompts.run_eval`          |
| `worker-render`     | `motionile-worker` | Renders and `media.check_composition` (sandbox validation and frame sampling for the graph) |
| `worker-default`    | `motionile-api`    | Notifications and billing; never generation                                                 |

Restart `worker-generation` with `compose.sh restart worker-generation`. Its stop grace period is five minutes; a job interrupted by a restart resumes from its LangGraph checkpoint when procrastinate retries the task, so no job is lost.

## 2. Required parameters

Upload with `infra/scripts/put-parameters.sh` (all `owner` parameters in `deploy/parameters.csv`): `AI_ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (embeddings), `AI_LANGFUSE_PUBLIC_KEY`, `AI_LANGFUSE_SECRET_KEY`. Optional: `AI_LANGFUSE_HOST`, `AI_LANGFUSE_PROJECT_ID` (admin trace links), `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`. `EMBEDDING_DIMENSIONS` is read by the migration that creates `skill_embeddings`; changing it later needs a new migration and a reseed.

## 3. First deployment of an environment

1. Deploy. `deploy.sh` runs the migration, then `seed_prompts` (creates draft prompt versions, activates nothing) and `seed_skills` (creates the system skills and their embeddings).
2. In the admin console open **Prompts**. For each template start the required eval runs (`evals.run`) for the draft version; the suites per template are listed in `modules/prompts/gate.py`. Runs execute on `worker-generation` with live models and cost money.
3. When the runs pass, activate each version. Until every template has an active version, new jobs fail with `prompt_not_active` and release their credits.

Local and CI stacks use `seed_prompts --bootstrap-fake-providers`, which activates drafts without a run and refuses to run anywhere else.

## 4. Changing models, budgets and charging

All of these are runtime settings in **Settings** (no deploy): `ai.model_routing` (JSON; invalid documents are rejected), `ai.job_token_budget`, `ai.max_repairs`, `ai.scene_concurrency`, `ai.approval_timeout_hours`, `ai.stage_timeout_minutes`, `ai.speaking_rate_*`, `ai.skill_token_budget`, `ai.visual_review_enabled`, `charging.*`, `jobs.max_active_per_user`. Change routing only after an eval run on the new models passes; the prompts were evaluated against the models in the routing at the time.

## 5. Troubleshooting

| Symptom                                           | Check                                                                                                                                                                  |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Jobs stay `queued`                                | `worker-generation` running? `compose.sh logs --since 10m worker-generation`; the queue name is `generation`.                                                          |
| Jobs fail with `prompt_not_active`                | A template has no active version: section 3.                                                                                                                           |
| Jobs fail with `budget_exceeded`                  | A job used more than `ai.job_token_budget` tokens. Look at the job in **Admin → Jobs** (scene attempts, repairs). Raise the budget only if repairs are healthy.        |
| Jobs fail with `llm_unavailable`                  | Every model in the route failed after retries: provider outage or an invalid key. Check Langfuse and the routing fallbacks.                                            |
| Jobs wait in `validating` for minutes             | The composition check runs on the `render` queue: `worker-render` must be healthy; results are stored under `work/jobs/<jobId>/checks/` and expire in seven days.      |
| Jobs fail with `job_stalled`                      | The sweeper found no progress for `ai.stage_timeout_minutes`; credits are released. Inspect the last events of the job.                                                |
| Videos contain "simple text layout" scenes        | Fallback scenes: the repair loop gave up. The fallback rate is on the jobs analytics page; a rising rate means a prompt or model regression, so run the `scenes` eval. |
| Share page shows 404 for a link that should exist | The link was revoked or replaced (one active link per job and rendition) or the rendition was deleted with its job.                                                    |

Credits: reservations are held by `credit_reservations` with the job as reference; the sweepers and the credits sweeper release them. Never edit wallet rows; use `adjust` with a reason ([`../billing.md`](../billing.md)).
