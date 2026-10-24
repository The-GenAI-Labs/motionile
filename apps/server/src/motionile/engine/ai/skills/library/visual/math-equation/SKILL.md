---
name: math-equation
description: Equations and formulas built up term by term and highlighted in sync with the narration - Pythagorean theorem, quadratic formula, fractions, exponents and powers, square roots, algebra rearrangement, area and volume formulas, physics and finance formulas, worked numeric substitution. Typeset with plain HTML, CSS grid and inline SVG because the runtime has no MathJax or KaTeX. Not for graphs of functions or data (data-chart-story) and not for code.
metadata:
  layer: visual
---

# Math equation

In examples the scene root class is `.mo-s-demo`; replace `demo` with the real scene id.

## When to use

One formula or short derivation (three lines at most) is the subject. Add a small diagram when the symbols stand for something drawable.

## Structure

1. The equation appears term by term: each term enters on the word that names it ("a squared" shows `a²`).
2. The term being spoken is lit (accent colour, elevated chip); a matching diagram part lights with it.
3. Release the previous highlight before lighting the next; only the spoken part is lit.
4. Hold still for the last 0.6 s.

## Do

- Build every formula from the same pieces: `.term` spans in an inline flex row (`align-items: center`), `.sup` for powers, `.frac` as a column flex with a bordered numerator, `.root` as an SVG radical plus a radicand with `border-top`.
- Size so a power (0.62em) stays at least `--mo-text-small`: `--mo-text-display` for short formulas; for long ones `calc(var(--mo-text-subtitle) * 1.4)` in landscape, `* 1.1` otherwise.
- Use the characters the fonts ship: `+ − × ÷ ± = < > ² ³ ½ ·` and digits. Greek letters and `√ ≈ ≠ ≤ ≥ ∑ ∞ →` are missing: spell the name ("pi") or draw the symbol with SVG.
- Minus is U+2212, never a hyphen; multiply with `×` or juxtaposition, never the letter x.
- Highlight by tweening `className: "+=lit"` and `"-=lit"`; the CSS then owns the colours. Dimmed text must stay above opacity 0.6 or keep its colour token.
- A worked substitution replaces one symbol by its value per beat, in place.

## Don't

- Do not use `<sup>` or `<sub>` defaults; they shrink below the minimum.
- Do not shrink equations with `transform`; change `font-size`.
- Do not draw lines or overlays through or beside glyph boxes within the line box: the contrast check reads the pixels behind the text. Keep SVG labels clear of strokes.
- Do not show more than three lines or eight terms per scene.

## runtime@1 patterns

Fractions, powers and radicals are CSS (second example): `.frac` is a column flex, the numerator carries `border-bottom: 0.06em solid currentColor`; a power is `position: relative; top: -0.5em; font-size: 0.62em`; the radical is an `svg` path with `preserveAspectRatio="none"` and `vector-effect: non-scaling-stroke` next to a radicand with `border-top`.

Light and release a set of items at a time (HTML nodes tween `className`; SVG elements cannot, so give each SVG part an overlay element and tween its `opacity`):

```js
const light = (keys, at) =>
  items.forEach((item) => {
    const on = keys.includes(item.key);
    if (on !== item.on) {
      ctx.timeline.to(item.node, { className: on ? "+=lit" : "-=lit", duration: 0.3 }, at);
      item.on = on;
    }
  });
```

## Examples

#### Example: Pythagorean theorem with a triangle

Narration: "In a right triangle, a squared plus b squared equals c squared. The two shorter sides, squared and added, match the longest side squared."

```js
const beat = (target, occurrence = 0) => Math.min(ctx.at(target, occurrence), ctx.duration - 0.7);
const make = (className, text) => {
  const element = document.createElement("span");
  element.className = className;
  element.textContent = text;
  return element;
};
const triangle = ctx.root.querySelector("[data-asset='triangle']");
const equation = document.createElement("div");
equation.className = "eq";
ctx.root.append(equation);
const specs = [
  { key: "a", base: "a", power: "2", cue: beat("a", 1) },
  { key: "plus", base: "+", cue: beat("plus") },
  { key: "b", base: "b", power: "2", cue: beat("b") },
  { key: "equals", base: "=", cue: beat("equals") },
  { key: "c", base: "c", power: "2", cue: beat("c") },
];
const items = specs.map((spec) => {
  const node = make("term", spec.base);
  if (spec.power) {
    node.append(make("sup", spec.power));
  }
  equation.append(node);
  ctx.timeline.from(node, { opacity: 0, y: 24, duration: 0.4, ease: "power3.out" }, spec.cue);
  return {
    key: spec.key,
    node,
    on: false,
    lit: { className: "+=lit" },
    unlit: { className: "-=lit" },
  };
});
const sides = ["a", "b", "c"].map((key) => ({
  key,
  node: triangle.querySelector(`.hl-${key}`),
  on: false,
  lit: { opacity: 1 },
  unlit: { opacity: 0 },
}));
const light = (keys, at) =>
  [...items, ...sides].forEach((item) => {
    const on = keys.includes(item.key);
    if (on !== item.on) {
      ctx.timeline.to(item.node, { ...(on ? item.lit : item.unlit), duration: 0.3 }, at);
      item.on = on;
    }
  });
ctx.timeline.from(triangle, { opacity: 0, scale: 0.92, duration: 0.6, ease: "power3.out" }, 0.1);
light(["a"], beat("a", 1));
light(["b"], beat("b"));
light(["c"], beat("c"));
light(["a", "b"], beat("shorter"));
light(["c"], beat("longest"));
```

```css
.mo-s-demo {
  display: flex;
  flex-direction: row;
  align-items: center;
  justify-content: space-evenly;
  gap: calc(var(--mo-unit) * 4);
}
.mo-s-demo .eq {
  display: flex;
  align-items: center;
  gap: 0.2em;
  font-size: var(--mo-text-display);
  font-weight: 600;
  line-height: 1.2;
  color: var(--mo-text-secondary);
}
.mo-s-demo .term {
  padding: 0 0.1em;
  border-radius: 0.15em;
}
.mo-s-demo .sup {
  position: relative;
  top: -0.5em;
  font-size: 0.62em;
}
.mo-s-demo .lit {
  color: var(--mo-accent);
  background: var(--mo-elevated);
}
.mo-s-demo .triangle {
  display: block;
  overflow: visible;
}
.mo-s-demo .side {
  fill: none;
  stroke: var(--mo-text-muted);
  stroke-width: 6;
  stroke-linecap: round;
}
.mo-s-demo .hl {
  fill: none;
  stroke: var(--mo-accent);
  stroke-width: 8;
  stroke-linecap: round;
  opacity: 0;
}
.mo-s-demo .mark {
  fill: none;
  stroke: var(--mo-text-muted);
  stroke-width: 3;
}
.mo-s-demo .name {
  fill: var(--mo-text-secondary);
  font-family: var(--mo-font);
  font-size: var(--mo-text-body);
  font-weight: 600;
}
@container stage (aspect-ratio <= 1) {
  .mo-s-demo {
    flex-direction: column;
  }
}
```

```svg id=triangle
<svg class="triangle" viewBox="0 0 440 370" width="440" height="370">
  <path class="mark" d="M40 268 L72 268 L72 300"/>
  <line class="side side-a" x1="40" y1="300" x2="40" y2="40"/>
  <line class="side side-b" x1="40" y1="300" x2="400" y2="300"/>
  <line class="side side-c" x1="40" y1="40" x2="400" y2="300"/>
  <line class="hl hl-a" x1="40" y1="300" x2="40" y2="40"/>
  <line class="hl hl-b" x1="40" y1="300" x2="400" y2="300"/>
  <line class="hl hl-c" x1="40" y1="40" x2="400" y2="300"/>
  <text class="name" x="4" y="184">a</text>
  <text class="name" x="212" y="358">b</text>
  <text class="name" x="238" y="136">c</text>
</svg>
```

#### Example: Quadratic formula and its discriminant

Narration: "Under the root sits b squared minus four a c. This discriminant tells you how many real solutions the equation has."

```js
const make = (tag, className, text) => {
  const element = document.createElement(tag);
  element.className = className;
  if (text) {
    element.textContent = text;
  }
  return element;
};
const radical = document.createElementNS("http://www.w3.org/2000/svg", "svg");
radical.setAttribute("class", "radical");
radical.setAttribute("viewBox", "0 0 40 100");
radical.setAttribute("preserveAspectRatio", "none");
const stroke = document.createElementNS("http://www.w3.org/2000/svg", "path");
stroke.setAttribute("d", "M2 60 L12 52 L26 96 L40 4");
radical.append(stroke);
const radicand = make("span", "radicand");
const b2 = make("span", "term", "b");
b2.append(make("span", "sup", "2"));
radicand.append(b2, make("span", "term", "−"), make("span", "term", "4ac"));
const root = make("span", "root");
root.append(radical, radicand);
const numerator = make("span", "num");
numerator.append(make("span", "term", "−b"), make("span", "term", "±"), root);
const fraction = make("span", "frac");
fraction.append(numerator, make("span", "den term", "2a"));
const formula = make("div", "eq");
const parts = [make("span", "term", "x"), make("span", "term", "="), fraction];
formula.append(...parts);
const tag = make("p", "tag", "The discriminant");
const cases = [
  ["Positive", "two solutions"],
  ["Zero", "one solution"],
  ["Negative", "none"],
].map(([name, result]) => {
  const chip = make("p", "chip");
  chip.append(make("span", "chip-name", `${name}: `), document.createTextNode(result));
  return chip;
});
const list = make("div", "cases");
list.append(...cases);
ctx.root.append(formula, tag, list);
ctx.timeline.from(
  parts,
  { opacity: 0, y: 20, duration: 0.35, stagger: 0.15, ease: "power3.out" },
  0.1,
);
ctx.timeline.to(root, { className: "+=lit", duration: 0.3 }, Math.max(ctx.at("root"), 0.9));
ctx.timeline.from(
  tag,
  { opacity: 0, y: 16, duration: 0.4, ease: "power3.out" },
  Math.min(ctx.at("discriminant"), ctx.duration - 0.5),
);
ctx.timeline.from(
  cases,
  { opacity: 0, y: 20, duration: 0.4, stagger: 0.3, ease: "power3.out" },
  Math.min(ctx.at("how"), ctx.duration - 1.4),
);
```

```css
.mo-s-demo {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: calc(var(--mo-unit) * 3);
}
.mo-s-demo .eq {
  display: flex;
  align-items: center;
  gap: 0.25em;
  font-size: calc(var(--mo-text-subtitle) * 1.4);
  font-weight: 600;
  line-height: 1.2;
  color: var(--mo-text-secondary);
}
.mo-s-demo .term {
  padding: 0 0.08em;
}
.mo-s-demo .sup {
  position: relative;
  top: -0.5em;
  font-size: 0.62em;
}
.mo-s-demo .frac {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
}
.mo-s-demo .num {
  display: inline-flex;
  align-items: stretch;
  padding: 0 0.2em 0.1em;
  border-bottom: 0.06em solid currentColor;
}
.mo-s-demo .den {
  padding-top: 0.1em;
}
.mo-s-demo .root {
  display: inline-flex;
  align-items: stretch;
  border-radius: 0.15em;
}
.mo-s-demo .radical {
  flex: none;
  width: 0.7em;
  overflow: visible;
}
.mo-s-demo .radical path {
  fill: none;
  stroke: currentColor;
  stroke-width: 4px;
  vector-effect: non-scaling-stroke;
}
.mo-s-demo .radicand {
  display: inline-flex;
  align-items: center;
  padding: 0.1em 0.1em 0;
  border-top: 0.06em solid currentColor;
}
.mo-s-demo .lit {
  color: var(--mo-accent);
  background: var(--mo-elevated);
}
.mo-s-demo .tag {
  margin: 0;
  font-size: var(--mo-text-body);
  font-weight: 600;
  color: var(--mo-text);
}
.mo-s-demo .cases {
  display: flex;
  flex-direction: row;
  gap: calc(var(--mo-unit) * 2);
}
.mo-s-demo .chip {
  margin: 0;
  padding: calc(var(--mo-unit) * 1.2) calc(var(--mo-unit) * 2);
  border: 2px solid var(--mo-border);
  border-radius: calc(var(--mo-unit) * 1.5);
  background: var(--mo-surface);
  font-size: var(--mo-text-body);
  color: var(--mo-text-secondary);
}
.mo-s-demo .chip-name {
  color: var(--mo-text);
  font-weight: 600;
}
@container stage (aspect-ratio <= 1) {
  .mo-s-demo .eq {
    font-size: calc(var(--mo-text-subtitle) * 1.1);
  }
  .mo-s-demo .cases {
    flex-direction: column;
    align-items: stretch;
    gap: calc(var(--mo-unit) * 1.2);
  }
}
```
