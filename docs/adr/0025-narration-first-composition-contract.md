# 25. Narration-first composition contract

- Status: Accepted
- Date: 2026-10-19
- Refines: [ADR 0009](0009-narration-first-generation-pipeline.md)

## Context

ADR 0009 fixes the order: narration first, then visuals timed to it. Phase 9's generator needs an exact contract to write against, and the renderer needs to verify that a composition honors it.

## Decision

- Narration is synthesized (or uploaded) before capture. The pipeline assembles one `window.__narration` object: per scene its start, duration and words with absolute and scene-relative timings in milliseconds. The renderer injects it before any page script runs.
- A composition calls `Motionile.composition({ scenes, aspects })` exactly once. The runtime reads `window.__narration`, creates a child timeline per scene sized to the scene's real duration, calls each scene builder with a context (`duration`, `words`, `at()`, `aspect`, `safeArea`, the child timeline), builds the master timeline and pauses it.
- The runtime exposes `window.__timeline`, `window.__composition` (total duration, scene boundaries, supported aspects) and `window.__ready`, a promise that resolves when fonts, images and the timeline are ready.
- Layout adapts through `data-aspect` on `<html>` and CSS container queries, so one composition renders 16:9, 9:16 and 1:1 without cropping. The renderer loads a fresh page per aspect.
- The runtime is versioned (`runtime@1`) and served only from local files at the virtual origin `https://runtime.motionile.local/v1/`. A composition may load scripts and styles only from that origin and images only as `data:` URIs or runtime assets.
- Validation compares the timeline duration with the narration duration (50 ms tolerance), the scene boundaries with the narration, and checks that every scene's animations end within its duration.
- `docs/render.md` is the complete reference. Golden compositions in `apps/server/tests/fixtures/compositions/` are the executable examples; Phase 9's skills quote them.

## Consequences

- Animation timing equals the real audio by construction, and a composition that drifts is rejected before capture.
- A narration change requires rebuilding the timeline, which the runtime does on every load.
- Changing the contract means a new runtime version (`runtime@2`) served beside the first, never an edit of a published one.
