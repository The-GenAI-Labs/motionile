---
name: whiteboard
description: Light off-white marker-on-whiteboard look with thick dark ink strokes, one blue marker colour, hard offset shadows and slightly tilted cards. Style for classroom-like explainers, beginner topics, math, science, how-it-works stories, step-by-step reasoning and anything that should feel hand-explained and friendly.
metadata:
  layer: style
  tokens: "--mo-bg: #f7f5ee; --mo-surface: #ffffff; --mo-elevated: #ece8da; --mo-border: #c9c2ae; --mo-text-muted: #5b5b63; --mo-text-secondary: #3d3d45; --mo-text: #17171c; --mo-accent: #1d4ed8; --mo-danger: #c62828; --mo-success: #17703a"
---

# Whiteboard

## When to use

Teaching-first scenes: beginners, school subjects, intuition before formality, process and cause-and-effect stories, metaphors. Pairs well with `concept-metaphor`, `math-equation`, `flow-diagram` and `timeline-sequence`. Avoid for code-heavy or night-time developer topics.

## Structure

Palette: warm paper `--mo-bg`, white `--mo-surface`, ink `--mo-text`, marker-blue `--mo-accent`. Contrast on `--mo-bg` and `--mo-surface`: text 16:1 or better, secondary 9.9:1, muted 6.2:1, accent 6.1:1, danger 5.1:1, success 5.6:1. The accent works as text on paper and as a fill with `--mo-bg` text (6.1:1).

## Do

- Type: Noto Sans weight 700 for titles and labels, 400 for body; Geist Mono for numbers. Sentence case, no uppercase tracking.
- Ink: strokes 6 to 8 px in `--mo-text`, `stroke-linecap: round`, `stroke-linejoin: round`. Circle, underline or arrow the focus in `--mo-accent`; use `--mo-danger` for a crossed-out wrong idea and `--mo-success` for the right one.
- Cards: white with a 4 px `--mo-text` border, radius `calc(var(--mo-unit) * 1.4)`, a hard shadow `6px 6px 0 var(--mo-border)` and a rotation of at most 1 degree set by gsap.
- Motion: things are drawn, not faded. Draw strokes by `strokeDashoffset` with `ease: "none"` or `power1.inOut`, 0.5 to 0.9 s; cards drop in with `back.out(1.4)` from 30 px above; underline and circle marks scale from their start.
- Keep drawings loose but few: at most 8 shapes, thick lines, no fine detail.
- Fill diagram shapes with `--mo-surface` or `--mo-elevated`, never saturated colour.

## Don't

- Do not use dark panels, gradients, glows or thin 1 px lines; they vanish on a light page.
- Do not use `--mo-border` as the only edge of important shapes; it is a shadow colour here.
- Do not set `--mo-text-muted` below 28 px or on `--mo-elevated` for key information.
- Do not tilt more than 1 degree or tilt text blocks that carry equations.

## runtime@1 patterns

```css
.mo-s-demo {
  --ink: 6px;
  --radius: calc(var(--mo-unit) * 1.4);
}
.mo-s-demo .panel {
  background: var(--mo-surface);
  border: 4px solid var(--mo-text);
  border-radius: var(--radius);
  box-shadow: 6px 6px 0 var(--mo-border);
  padding: calc(var(--mo-unit) * 3);
}
.mo-s-demo .ink {
  fill: none;
  stroke: var(--mo-text);
  stroke-width: var(--ink);
  stroke-linecap: round;
  stroke-linejoin: round;
}
.mo-s-demo .mark {
  stroke: var(--mo-accent);
}
```
