# 24. Deterministic capture through the Web Animations API and a frozen clock

- Status: Accepted
- Date: 2026-10-19
- Refines: [ADR 0009](0009-narration-first-generation-pipeline.md)

## Context

Frame capture must give frame-identical output for the same composition, audio and options, across runs, across machines and between one capturing page and several. Real time, `requestAnimationFrame` pacing, `Math.random`, GSAP's ticker and CSS animations that advance on their own all break that. Banning CSS animation would remove a useful tool for generated scenes and would not stop a model from using it.

## Decision

- The composition builds a paused GSAP master timeline exposed as `window.__timeline`. The renderer never plays it.
- Before every frame at time `t` the renderer, in one page evaluation:
  1. seeks `window.__timeline` to `t`;
  2. pauses every animation returned by `document.getAnimations()` and sets its `currentTime` to `t`, which covers CSS animations, CSS transitions and the Web Animations API.
- Time and randomness are frozen. Playwright's clock pins `Date`, `performance.now`, timers and `requestAnimationFrame`; the renderer advances it by exactly one frame per frame. `Math.random` is replaced before any page script by a seeded generator whose seed is derived from the render options.
- The renderer then waits for two animation frames, so style and layout settle, and takes the screenshot.
- Screenshots never use Playwright's `animations: "disabled"`, which would finish and cancel animations.
- Each page reaches the same state at any `t` because the timeline and the animations are pure functions of `t`. Chunks of the timeline captured by different pages therefore match single-page capture. Callbacks that change state must be idempotent functions of time; the contract in `docs/render.md` says so, and validation samples frames out of order to catch violations.
- Frames are streamed to ffmpeg and never written to disk. Encoding uses fixed settings from configuration and segments that start on a keyframe.

## Consequences

- The same inputs produce the same frames; tests compare per-frame hashes.
- Compositions may use CSS animations, transitions and the Web Animations API, provided their start state is set at load rather than by timeline callbacks.
- Compositions that read the real time or depend on network responses are not supported; the sandbox blocks the network and the clock is frozen.
