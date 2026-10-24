# Eval datasets

Versioned data for the Phase 9 eval suites. Files are UTF-8 YAML with plain data only (no comments). Open them with an explicit UTF-8 encoding.

Every file starts with `version` (`YYYY-MM-DD.N`) and a `cases` list. Change `version` whenever a case is added, edited or removed. Case `id` values are unique within a file and never reused.

## golden_queries.yaml

Reference requests for the planner, scenes, sync and cost suites and the judge model.

| Field             | Rule                                                                                                 |
| ----------------- | ---------------------------------------------------------------------------------------------------- |
| `id`              | `<category>-<subcategory>-NN`, for example `tech-backend-01`                                         |
| `subcategory`     | A subcategory slug exactly as in `seeds/catalog.yaml`; every slug has at least three cases           |
| `query`           | A realistic user request: topic, how-it-works, why-question or a short misconception-driven question |
| `durationSeconds` | 10 to 120                                                                                            |
| `aspects`         | One to three of `16:9`, `9:16`, `1:1`                                                                |
| `language`        | `en` or `hi-IN`                                                                                      |
| `keyConcepts`     | 3 to 6 objects `{name, synonyms}` that a correct explanation must cover                              |
| `misconceptions`  | 1 to 3 statements a good explanation must not assert as true                                         |
| `referenceNotes`  | 60 to 150 words of accurate, specific ground truth the judge compares against                        |

## duration_cases.yaml

Requests that stress scene counts and aspect handling.

| Field                | Rule                                                                                     |
| -------------------- | ---------------------------------------------------------------------------------------- |
| `id`                 | `short-NN`, `long-NN` or `multi-NN`                                                      |
| `kind`               | `short` (10 to 20 s), `long` (100 to 120 s) or `multi_aspect` (all three aspects)        |
| `query`              | The request                                                                              |
| `durationSeconds`    | Within the range of its kind                                                             |
| `aspects`            | One to three of `16:9`, `9:16`, `1:1`                                                    |
| `expectedSceneRange` | `[min, max]`, with `min = max(2, ceil(d / 15))` and `max = min(12, max(2, ceil(d / 8)))` |

## adversarial.yaml

Cases for the `safety` suite and the guards in `engine/ai/guardrails/`.

| Field          | Rule                                                                                                     |
| -------------- | -------------------------------------------------------------------------------------------------------- |
| `id`           | Unique, prefixed by the category family                                                                  |
| `kind`         | `query`, `storyboard_edit` or `instructions` (regeneration and revision instructions)                    |
| `text`         | The text sent to the input guard; may contain newlines, fake closing tags, encodings or non-English text |
| `expected`     | `allow` or `refuse`                                                                                      |
| `expectedCode` | Required when `expected` is `refuse`, omitted otherwise; one of the codes in `docs/ai-policy.md`         |
| `category`     | A grouping label for reporting; benign near-misses use the `benign_` prefix                              |

Roughly a quarter of the cases are `allow` near-misses, which guard against over-refusal. A text that combines an injection with another violation expects `policy_prompt_injection`, per rule 2 of the policy.

## Adding a case

1. Append the case to the matching file with the next free id.
2. For golden queries, write facts you can verify and keep `referenceNotes` within 60 to 150 words.
3. For adversarial cases, take `expectedCode` from `docs/ai-policy.md`. Never put real personal data, real addresses or working harmful payloads in `text`; use obviously invented values and placeholders such as `user@example.com`.
4. Bump `version` in the file.
5. Run the dataset loader tests, then the `safety` or planner suite as appropriate.

Changing `docs/ai-policy.md` requires new or updated adversarial cases in the same pull request.
