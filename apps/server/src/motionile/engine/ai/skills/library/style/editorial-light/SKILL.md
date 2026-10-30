---
name: editorial-light
description: Magazine and newspaper look - warm paper background, near-black ink, one oxblood accent, very large tight headlines, hairline rules, uppercase eyebrow labels and slow confident motion. Style for economics, history, culture, finance, policy, science journalism, opinion-style explainers and data stories that should feel authoritative and calm.
metadata:
  layer: style
  tokens: "--mo-bg: #faf7f2; --mo-surface: #ffffff; --mo-elevated: #f0ebe2; --mo-border: #d6cdbd; --mo-text-muted: #5f574e; --mo-text-secondary: #3b352f; --mo-text: #14110f; --mo-accent: #8f1d2c; --mo-danger: #b53a0a; --mo-success: #17703a"
---

# Editorial light

## When to use

Argument and analysis: economics, finance, history, society, health and science news, comparisons and charts with a point of view. Pairs well with `data-chart-story`, `timeline-sequence`, `comparison-split` and `kinetic-typography`. Avoid for code, hardware or playful beginner content.

## Structure

Palette: cream `--mo-bg`, white `--mo-surface`, ink `--mo-text`, oxblood `--mo-accent`. Contrast on `--mo-bg` and `--mo-surface`: text 17.6:1 or better, secondary 11.3:1, muted 6.6:1, accent 8.3:1, danger 5.5:1, success 5.8:1. The accent works as text on paper and as a fill with `--mo-bg` text at 8.3:1.

## Do

- Type: Geist weight 800 for headlines with letter-spacing -0.035em and line-height 1.05, set large (`--mo-text-title` up to `--mo-text-display`); Noto Sans 400 for body; Geist Mono for figures and dates. Headlines are left-aligned and may span several lines.
- Eyebrow: a small uppercase label (`--mo-text-small`, 600, tracking 0.1em, `--mo-accent`) above each headline, followed by a 2 px rule in `--mo-text`.
- Structure with rules, not boxes: 2 px lines in `--mo-text` or `--mo-border`, no card shadows, radius 0 to 4 px. Use `--mo-surface` only for chart plot areas and quotes.
- Emphasis: one accent word or number per headline; charts use `--mo-text` for context, `--mo-accent` for the story, never more than two series colours.
- Motion: slow and composed, `power4.out` entrances of 0.8 to 1 s with 16 to 24 px of travel, 0.15 s staggers; rules extend from the left with `scaleX`. No bounce, no rotation.

## Don't

- Do not use dark backgrounds, gradients, glass, shadows or emoji-like icons.
- Do not centre long headlines or body text.
- Do not use `--mo-border` for text or for the only edge of a chart series.
- Do not use red and green together to carry meaning; add a label or position.

## runtime@1 patterns

```css
.mo-s-demo .eyebrow {
  margin: 0 0 calc(var(--mo-unit) * 1.2);
  font-size: var(--mo-text-small);
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--mo-accent);
}
.mo-s-demo .headline {
  margin: 0;
  font-size: var(--mo-text-title);
  font-weight: 800;
  letter-spacing: -0.035em;
  line-height: 1.05;
  color: var(--mo-text);
  text-align: left;
  text-wrap: balance;
}
.mo-s-demo .rule {
  height: 2px;
  margin-top: calc(var(--mo-unit) * 2);
  background: var(--mo-text);
  transform-origin: 0 50%;
}
```
