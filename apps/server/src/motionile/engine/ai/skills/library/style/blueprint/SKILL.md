---
name: blueprint
description: Engineering blueprint look - deep blue paper, faint drafting grid, thin cyan line work, monospaced dimension labels, square corners and precise linear motion. Style for architecture, systems, infrastructure, hardware, mechanics, electronics, networks, specifications and any design-and-build explainer.
metadata:
  layer: style
  tokens: "--mo-bg: #0b2545; --mo-surface: #12315a; --mo-elevated: #1a3f70; --mo-border: #3d6aa3; --mo-text-muted: #9fb8dd; --mo-text-secondary: #c3d6f0; --mo-text: #eef4ff; --mo-accent: #7fd1ff; --mo-danger: #ff8a80; --mo-success: #6ee7b0"
---

# Blueprint

## When to use

Structure and construction: system architecture, cloud and network layouts, mechanical and electrical topics, protocols, specifications, build-up diagrams. Pairs well with `architecture-build-up`, `flow-diagram` and `data-structure-operations`. Avoid for emotional or human-centred stories.

## Structure

Palette: navy paper `--mo-bg`, slightly lighter `--mo-surface`, cyan `--mo-accent` for the live line work, pale blue-white text. Contrast on `--mo-bg` and `--mo-surface`: text 11.8:1 or better, secondary 8.8:1, muted 6.4:1, accent 7.7:1, danger 5.7:1, success 8.5:1. The accent as a fill takes `--mo-bg` text at 9.1:1.

## Do

- Type: Geist Mono for labels, dimensions, ids and numbers (uppercase `--mo-text-small` with 0.06em tracking); Geist weight 600 for titles.
- Line work: 3 px strokes in `--mo-accent` for the active object, `--mo-text-muted` for context, no fills except `--mo-surface`. Corners square or radius at most `calc(var(--mo-unit) * 0.6)`.
- Grid: paint the paper grid on the scene root with `--mo-surface` lines (not `--mo-border`, whose contrast against text is too low behind words): `linear-gradient(var(--mo-surface) 2px, transparent 2px)` in both directions at `background-size: calc(var(--mo-unit) * 5)`.
- Annotate like a drawing: thin dimension lines with end ticks, a label per part, tag numbers in mono (`A1`, `B2`).
- Motion: lines draw on with `strokeDashoffset`, `ease: "power2.inOut"`, 0.4 to 0.7 s; boxes appear by stroke first, label second; no overshoot or bounce, no rotation.
- Highlight a part by switching its stroke to `--mo-accent` and its label to `--mo-text`.

## Don't

- Do not use warm colours except `--mo-danger` for faults.
- Do not fill large areas with `--mo-elevated`; the page stays dark and the lines carry the design.
- Do not use rounded pill shapes, soft shadows or gradients other than the grid.
- Do not put text over a crossing of grid lines with colour `--mo-border`.

## runtime@1 patterns

```css
.mo-s-demo {
  background-image:
    linear-gradient(var(--mo-surface) 2px, transparent 2px),
    linear-gradient(90deg, var(--mo-surface) 2px, transparent 2px);
  background-size: calc(var(--mo-unit) * 5) calc(var(--mo-unit) * 5);
}
.mo-s-demo .part {
  fill: none;
  stroke: var(--mo-accent);
  stroke-width: 3;
}
.mo-s-demo .tag {
  font-family: var(--mo-font-mono);
  font-size: var(--mo-text-small);
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--mo-text-secondary);
}
```
