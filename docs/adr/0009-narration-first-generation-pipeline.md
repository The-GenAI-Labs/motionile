# 9. Narration-first generation pipeline

- Status: Accepted
- Date: 2026-10-13

## Context

Explainer videos feel wrong when animations drift from the voice. Estimating durations from text is unreliable across voices, languages and providers. Generation is also expensive, so mistakes should be caught before rendering.

## Decision

The pipeline runs in this order:

1. Guard check, then context assembly from preferences, memory, skills, RAG and web search.
2. A structured storyboard that the user reviews, edits and approves before any expensive step.
3. Text-to-speech per scene, returning audio, word-level timestamps and real durations.
4. Scene HTML, CSS and GSAP generated with those fixed durations and composed into one page with a paused master timeline on `window.__timeline`.
5. Sanitization, sandboxed validation, visual QA and at most two repairs.
6. Frame-by-frame capture at 30 fps, encoding, muxing, loudness normalization to −16 LUFS, optional subtitles and renditions in 16:9, 9:16 and 1:1.

The MCP path enters at sanitization and runs TTS first when only narration text is submitted.

## Consequences

- Animation timing matches the real audio exactly.
- Human approval prevents paying for renders of a bad plan.
- TTS cost is incurred before visuals, and a narration change requires regenerating that scene's visuals.
