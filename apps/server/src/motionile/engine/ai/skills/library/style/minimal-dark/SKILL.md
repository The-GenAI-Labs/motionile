---
name: minimal-dark
description: Motionile's default look - dark monochrome with near-white accent, Geist type, generous space, hairline borders, restrained fast motion. Style for technical explainers, software, engineering, AI, product and general topics when no other style is requested or implied. The brand palette from base.css, so it needs no token overrides.
metadata:
  layer: style
  tokens: ""
---

# Minimal dark

## When to use

The default. Software, backend, DevOps, AI, security, product and business explainers, and any topic where the user asked for no particular look. It never clashes with other content.

## Structure

Palette is the brand set in `base.css` (`--mo-bg` #0E0E10, `--mo-surface` #16161A, `--mo-elevated` #1E1E23, `--mo-border` #2A2A30, `--mo-text` #F2F2F3, `--mo-text-secondary` #B4B4BC, `--mo-text-muted` #8A8A93, `--mo-accent` #FAFAFA, `--mo-danger` #E5484D, `--mo-success` #3DD68C). Text colours measure 5.3:1 or better on `--mo-bg` and `--mo-surface`; the accent is near white, so it separates by brightness and weight, not hue.

## Do

- Type: Geist for everything; Geist Mono for code, numbers, dates and labels. Titles weight 700 to 800 with letter-spacing -0.02em to -0.03em; body 400; labels 500 uppercase with 0.08em tracking at `--mo-text-small`.
- Hierarchy by brightness: `--mo-text` for the focus, `--mo-text-secondary` for support, `--mo-text-muted` only for captions, units and inactive items.
- Emphasis: accent colour or weight 700, one emphasis per beat. Use `--mo-success` and `--mo-danger` only for good and bad states, never as decoration.
- Surfaces: cards on `--mo-surface` with a 2 px `--mo-border`, radius `calc(var(--mo-unit) * 2)`; raise a focused card to `--mo-elevated` or give it an accent border. Strokes in diagrams 4 to 6 px, round caps.
- Motion: `power3.out` for entrances at 0.4 to 0.6 s, travel 24 to 48 px, 0.08 to 0.12 s staggers; `power2.inOut` for moves; `back.out(1.6)` only for small pops. No bounce, no spin.
- Fill space with whitespace; at most one decorative element per scene.

## Don't

- Do not add gradients, glows, shadows, noise or a second accent hue.
- Do not set text in pure white on pure black or use `--mo-accent` as a background behind `--mo-text`.
- Do not put muted text on `--mo-elevated` for anything important.
- Do not use a light background, ever.

## runtime@1 patterns

```css
.mo-s-demo {
  --radius: calc(var(--mo-unit) * 2);
  --stroke: 4px;
}
.mo-s-demo .panel {
  background: var(--mo-surface);
  border: 2px solid var(--mo-border);
  border-radius: var(--radius);
  padding: calc(var(--mo-unit) * 3);
}
.mo-s-demo .panel.focus {
  background: var(--mo-elevated);
  border-color: var(--mo-accent);
}
.mo-s-demo .eyebrow {
  font-size: var(--mo-text-small);
  font-weight: 500;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--mo-text-muted);
}
```
