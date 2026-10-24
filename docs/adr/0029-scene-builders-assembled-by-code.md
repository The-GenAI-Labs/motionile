# 29. The model writes scene builders, code assembles the document

- Status: Accepted
- Date: 2026-10-24
- Refines: [ADR 0009](0009-narration-first-generation-pipeline.md), [ADR 0025](0025-narration-first-composition-contract.md)

## Context

Phase 9 has a model produce the visuals. Asking it for a whole HTML document per video makes every contract rule (runtime includes, scene registry, one `Motionile.composition` call, scene IDs equal to narration IDs) something the model can get wrong, and a defect in one scene forces regenerating all of them.

## Decision

- For each scene the model returns a `scene-module@1`: the body of a builder function written against `runtime@1`, CSS scoped to the scene's root class, and the scene's inline SVG assets. It never returns the document.
- A deterministic composer assembles the modules into the composition: runtime includes, one `<section data-scene>` per scene carrying its root class and assets, the scoped styles, the style skill's tokens and a single `Motionile.composition({ aspects, scenes })` call. The same modules always produce byte-identical HTML.
- Static checks run on every module before composition: the builder parses as JavaScript, uses only the documented context and an allowed set of globals, every CSS selector is prefixed by the scene's root class, and size limits hold. They are a fast feedback layer for the repair loop; the Phase 8 sanitizer, sandbox and validator remain the controls and run on every composed document.
- A failing scene is repaired alone: its module is regenerated with the issues and the previous attempt while the other modules stay untouched.

## Consequences

- The contract is correct by construction; the model cannot break scene registration, scene order or the runtime includes.
- Repair cost scales with the number of failing scenes, not the number of scenes.
- Scene modules are small, cacheable and easy to inspect in the admin console.
- The model cannot build a feature that needs document-level structure (shared defs across scenes, cross-scene elements). A new capability means extending the composer, not prompting around it.
