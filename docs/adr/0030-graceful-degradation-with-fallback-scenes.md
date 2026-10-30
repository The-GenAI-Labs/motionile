# 30. Graceful degradation with fallback scenes

- Status: Accepted
- Date: 2026-10-24
- Refines: [ADR 0029](0029-scene-builders-assembled-by-code.md)

## Context

A generated scene can fail validation or visual review in ways the model cannot fix in two attempts. Failing the whole job wastes the narration, the other scenes and the user's wait, and the credits have already been reserved for a video the user is entitled to expect.

## Decision

- A scene that still has blocking issues after the maximum number of repairs (setting `ai.max_repairs`, default 2) is replaced by a safe fallback scene: kinetic typography of its narration in the job's style, built by code from a fixed template and the style skill's tokens.
- The fallback template shows a bounded window of the narration words, so any narration length fits the safe area in every aspect. It is covered by tests against the sandbox validator for all styles and aspects.
- The job does not fail for one bad scene. Each fallback is recorded as a `scene.fallback` job event and on the scene (`is_fallback`), shown to the user as a notice on the finished video, and counted in admin analytics.
- The fallback itself passes through the same validation. If it fails, the job fails with `composition_invalid`.

## Consequences

- Users get a finished, correctly narrated video in nearly every case.
- Quality problems stay visible: the fallback rate is a tracked metric and an eval threshold.
- Charging does not change for a fallback ([ADR 0031](0031-predictable-charging.md)); the user is told, not billed differently.
