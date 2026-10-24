# AI content policy

Motionile makes short explainer videos. This policy decides which requests the pipeline accepts. It is enforced by the input guard on every query, every storyboard edit and every regeneration or revision instruction, and by the output guard on the storyboard and narration before any narration or rendering is paid for. The implementation is in `engine/ai/guardrails/`; the pipeline is described in [`ai-pipeline.md`](ai-pipeline.md).

## In scope

Educational and technical explanation of any topic at any level: how things work, why they work, how to use them, history and concepts, including security concepts explained defensively (how an attack class works and how to defend against it), medicine and law as general education, and sensitive subjects treated factually and without instructions to cause harm.

## Out of scope

A request is refused when its purpose is any of the following. The code goes to the job as `error_code`, the message is shown to the user, and the reservation is released in full.

| Code                          | Refused                                                                                                                                | Message shown                                                                                                                            |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `policy_weapons`              | Instructions to make, acquire or use weapons, explosives or agents meant to cause mass harm                                            | Motionile cannot make videos that explain how to build or use weapons. Try a topic about the history or science behind it.               |
| `policy_malware`              | Working malware, exploit code against systems you do not own, or help evading detection for malicious purposes                         | Motionile cannot make videos that teach how to build malware or attack systems. Try explaining how the attack class is defended against. |
| `policy_self_harm`            | Encouragement or instructions for suicide, self-harm or eating disorders                                                               | Motionile cannot make this video. If you or someone you know is struggling, please reach out to a local helpline or someone you trust.   |
| `policy_abuse`                | Instructions for abusing, exploiting, trafficking or grooming people, or content sexualizing minors                                    | Motionile cannot make videos that involve abuse or exploitation.                                                                         |
| `policy_sexual_content`       | Sexually explicit content                                                                                                              | Motionile does not make sexually explicit videos.                                                                                        |
| `policy_harassment`           | Harassing, defaming, threatening or demeaning a real, identifiable person or a protected group                                         | Motionile cannot make videos that target a real person or group.                                                                         |
| `policy_political_persuasion` | Persuasive political content: campaigning for or against a candidate, party or ballot measure, or one-sided advocacy presented as fact | Motionile does not make persuasive political videos. A neutral explainer of how the system works is fine.                                |
| `policy_personal_data`        | Personal data that should not end up in a video: contact details, government IDs, financial or health records of a real person         | Your request contains personal information. Remove it and try again.                                                                     |
| `policy_prompt_injection`     | An attempt to override Motionile's instructions, change its role or smuggle instructions through text that is meant as data            | Motionile could not use this request. Describe the topic you want explained and try again.                                               |
| `policy_prompt_extraction`    | An attempt to read Motionile's system prompts, skills or internal configuration                                                        | Motionile could not use this request. Describe the topic you want explained and try again.                                               |
| `policy_unsupported_request`  | Not a request for an explanation (spam, empty or meaningless text, a request for another kind of output)                               | Motionile makes explainer videos. Tell it what you want explained.                                                                       |
| `policy_output_blocked`       | The generated storyboard or narration breaks this policy, or a model output contained protected prompt text                            | The video could not be completed safely. Your credits were returned. Try rephrasing your request.                                        |

## Rules for the guards

1. The guard decides on the purpose of the request, not on keywords: a video that explains how phishing works defensively is in scope; one that drafts a phishing campaign is not.
2. User text is data. A sentence in a query or an edit that tells the system to ignore its rules is a `policy_prompt_injection` refusal, whatever else the request contains.
3. Personal data is detected in the query, in storyboard edits and in generated narration. Public figures named in an educational context (a scientist in a history of physics) are not personal data.
4. A refusal never explains the detection method, never echoes the refused text and never names the matched rule. The response carries the code and the message above.
5. Refusals are logged with the code, the job ID and the user ID only. The refused text is not logged.
6. When the guard model is unavailable the request is retried and then fails with `llm_unavailable`; it is never allowed by default.

## Changing the policy

A change to this file needs a matching change to the guard prompts in `engine/ai/prompts/system/`, new or updated cases in `apps/server/evals/datasets/` (adversarial and out-of-policy sets) and a passing `safety` eval run before the new prompt version can be activated ([ADR 0033](adr/0033-eval-gated-prompt-activation.md)).
