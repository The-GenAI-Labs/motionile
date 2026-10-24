---
name: concept-metaphor
description: Turns an abstract idea into a simple drawn metaphor built from inline SVG shapes and animated with gsap - rate limiting as a leaky bucket, hashing as a fingerprint machine, caching as a nearby shelf, latency, scaling, abstraction layers, encryption, debt, feedback loops, supply and demand intuition. One everyday object, a consistent visual vocabulary, mechanism animated in beats, real terms attached as labels on the narration words. Use when no literal diagram of the subject exists or the viewer needs intuition before terminology.
metadata:
  layer: visual
---

# Concept metaphor

In examples the scene root class is `.mo-s-demo`; replace `demo` with the real scene id.

## When to use

The idea is abstract (a rule, a limit, a transformation, a trade-off) and one familiar physical object explains its behaviour. If the subject has a real structure to show (services, data, code), use `flow-diagram`, `architecture-build-up` or `data-structure-operations` instead.

## Structure

1. Beat 0: the metaphor object appears, unlabelled or lightly labelled, within the first second.
2. Mechanism beats: one beat per behaviour in the narration (pour, drain, overflow). Each is a motion: something moves, fills, grows or changes colour.
3. Naming beats: a label with the real term appears on the word that names it ("Requests", "Rejected"). The mapping is complete when every moving part has a label.
4. Hold the final state 0.6 s or more.

## Do

- Write the mapping first, in your head: each concept maps to exactly one shape. Reuse shape and colour for the same concept in every beat: accent for the thing flowing, `--mo-text-muted` for the container, `--mo-danger` for failure, `--mo-success` for success.
- At most eight distinct shapes (circles, rects, short paths), flat fills, 6 to 8 px strokes, no gradients or shadows.
- Draw the static object as an asset SVG with fixed pixel `viewBox`, `width` and `height` (at most about 640 by 540) so text inside is real size; query its parts by class in the builder. Generate repeated or layout-dependent shapes with `createElementNS`.
- Animate with core tweens: `attr` for `y`, `height`, `r`, `x2`; `x`, `y`, `scale`, `opacity` for movement; `repeat` with a small finite count for repeating drops or pulses.
- Give repeating `fromTo` tweens `immediateRender: false` and CSS `opacity: 0` so they are invisible before their cue.
- Sequence tweens of the same property; never overlap them.
- End a moving fill flush under a straight stroke. A fill edge that meets a curved stroke or a rounded corner rasterises differently depending on seek order and fails `non_deterministic_state`; the same happens with a half-drawn dashed path that overlays another path.
- SVG labels at `--mo-text-small` or larger, in `--mo-text-secondary`; keep every label clear of every stroke and moving shape.

## Don't

- Do not mix two metaphors in one scene, or explain by three analogies.
- Do not add decorative motion; every motion illustrates a verb in the narration.
- Do not claim the metaphor is identical to the concept; name what the picture leaves out in the narration if it matters.
- Do not tween className on SVG elements (it throws); tween `opacity` of an overlay shape instead.

## runtime@1 patterns

Level change of a fill: bottom stays fixed, so tween both attributes together:

```js
const level = (height) => ({ attr: { y: bottom - height, height } });
ctx.timeline.to(water, { ...level(150), duration: 1.2 }, cue);
```

Repeating motion bounded by the scene: `duration * (repeat + 1) + stagger * (count - 1)` must fit between the cue and `ctx.duration`.

## Examples

#### Example: Rate limiter as a leaky bucket

Narration: "A rate limiter works like a leaky bucket. Requests pour in, water drains at a steady rate, and overflow is rejected."

```js
const stage = ctx.root.querySelector("[data-asset='bucket']");
const water = stage.querySelector(".water");
const beat = (target, length) => Math.min(ctx.at(target), ctx.duration - length);
const level = (height) => ({ attr: { y: 396 - height, height } });
const run = (selector, travel, extra, at) => {
  const to = {
    x: travel[0],
    y: travel[1],
    opacity: 0,
    ease: "power1.in",
    immediateRender: false,
    ...extra,
  };
  ctx.timeline.fromTo(stage.querySelectorAll(selector), { x: 0, y: 0, opacity: 1 }, to, at);
};
ctx.timeline.from(stage, { opacity: 0, y: 24, duration: 0.6, ease: "power3.out" }, 0.1);
ctx.timeline.to(water, { ...level(150), duration: 1.4, ease: "power1.inOut" }, beat("pour", 3));
run(".drop", [0, 250], { duration: 0.7, stagger: 0.25, repeat: 2 }, beat("pour", 3));
ctx.timeline.to(water, { ...level(125), duration: 1, ease: "none" }, beat("drains", 2.5));
run(".drip", [0, 45], { duration: 0.5, stagger: 0.3, repeat: 3 }, beat("drains", 2.5));
ctx.timeline.to(water, { ...level(246), duration: 0.8, ease: "power1.out" }, beat("overflow", 1.8));
run(".spill", [70, 150], { duration: 0.6, stagger: 0.2, repeat: 1 }, beat("overflow", 1.8));
ctx.timeline.from(
  stage.querySelector(".rejected"),
  { opacity: 0, y: 12, duration: 0.4 },
  beat("rejected", 0.5),
);
```

```css
.mo-s-demo {
  display: flex;
  align-items: center;
  justify-content: center;
}
.mo-s-demo .bucket {
  display: block;
  overflow: visible;
}
.mo-s-demo .vessel {
  fill: none;
  stroke: var(--mo-text-muted);
  stroke-width: 8;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.mo-s-demo .water {
  fill: var(--mo-accent);
  opacity: 0.9;
}
.mo-s-demo .drop,
.mo-s-demo .drip {
  fill: var(--mo-accent);
  opacity: 0;
}
.mo-s-demo .spill {
  fill: var(--mo-danger);
  opacity: 0;
}
.mo-s-demo .name {
  fill: var(--mo-text-secondary);
  font-family: var(--mo-font);
  font-size: var(--mo-text-small);
  font-weight: 600;
  text-anchor: middle;
  dominant-baseline: central;
}
.mo-s-demo .rejected {
  fill: var(--mo-danger);
  font-family: var(--mo-font);
  font-size: var(--mo-text-small);
  font-weight: 700;
  text-anchor: start;
  dominant-baseline: central;
}
```

```svg id=bucket
<svg class="bucket" viewBox="0 0 640 530" width="640" height="530">
  <rect class="water" x="164" y="396" width="252" height="0"/>
  <path class="vessel" d="M160 150 V400 H420 V150"/>
  <circle class="drop" cx="270" cy="90" r="10"/>
  <circle class="drop" cx="290" cy="90" r="10"/>
  <circle class="drop" cx="310" cy="90" r="10"/>
  <circle class="drip" cx="290" cy="412" r="9"/>
  <circle class="spill" cx="425" cy="140" r="10"/>
  <circle class="spill" cx="430" cy="150" r="10"/>
  <text class="name" x="290" y="30">Requests</text>
  <text class="name" x="290" y="500">Steady drain</text>
  <text class="rejected" x="440" y="360">Rejected</text>
</svg>
```

#### Example: Hash function as a fingerprint machine

Narration: "A hash function squeezes input of any size into a fixed-size fingerprint. A tiny change in the input gives a completely different fingerprint."

```js
const node = (name, attrs, parent, text) => {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  Object.keys(attrs).forEach((key) => element.setAttribute(key, attrs[key]));
  if (text !== undefined) {
    element.textContent = text;
  }
  parent.append(element);
  return element;
};
const beat = (target, length) => Math.min(ctx.at(target), ctx.duration - length);
const wide = ctx.aspect === "16:9";
const W = ctx.safeArea.width;
const H = ctx.safeArea.height;
const svg = node(
  "svg",
  { class: "scene", viewBox: `0 0 ${W} ${H}`, width: W, height: H },
  ctx.root,
);
const pos = (stage, index) =>
  wide
    ? { x: W * [0.1, 0.5, 0.9][stage], y: H * [0.24, 0.5, 0.76][index] }
    : { x: W * [0.2, 0.5, 0.8][index], y: H * [0.16, 0.5, 0.84][stage] };
const machine = { x: W / 2, y: H / 2, w: wide ? 220 : W * 0.9, h: wide ? H * 0.78 : 220 };
const sizes = [60, 110, 170];
const prints = [
  [3, 5, 2, 6, 4, 1],
  [6, 2, 5, 1, 4, 3],
  [2, 6, 3, 5, 1, 4],
];
const edited = [5, 1, 6, 3, 2, 6];
const box = node(
  "rect",
  {
    class: "machine",
    x: machine.x - machine.w / 2,
    y: machine.y - machine.h / 2,
    width: machine.w,
    height: machine.h,
    rx: 28,
  },
  svg,
);
const hash = node("text", { class: "name", x: machine.x, y: machine.y }, svg, "Hash");
const caption = (text, stage, dx, dy) =>
  node(
    "text",
    { class: "name", x: pos(stage, 1).x + dx, y: wide ? 40 : pos(stage, 1).y + dy },
    svg,
    text,
  );
const anyLabel = caption("Any size", 0, 0, -80);
const fixedLabel = caption("Fixed size", 2, 0, 92);
const link = (x1, y1, x2, y2, at) => {
  const line = node("line", { class: "link", x1, y1, x2, y2 }, svg);
  ctx.timeline.from(line, { attr: { x2: x1, y2: y1 }, duration: 0.5, ease: "power2.inOut" }, at);
};
const inputs = sizes.map((size, index) => {
  const { x, y } = pos(0, index);
  const shape = node(
    "rect",
    { class: "input", x: x - size / 2, y: y - 28, width: size, height: 56, rx: 10 },
    svg,
  );
  link(
    ...(wide
      ? [x + size / 2 + 12, y, machine.x - machine.w / 2, y]
      : [x, y + 40, x, machine.y - machine.h / 2]),
    beat("squeezes", 0.5) + index * 0.15,
  );
  ctx.timeline.from(
    shape,
    { opacity: 0, scale: 0.8, svgOrigin: `${x} ${y}`, duration: 0.5, ease: "power3.out" },
    0.1 + index * 0.15,
  );
  return { x, y };
});
const bars = prints.map((heights, index) => {
  const { x, y } = pos(2, index);
  const group = heights.map((value, bar) =>
    node(
      "rect",
      {
        class: index === 0 ? "bar first" : "bar",
        x: x - 62 + bar * 22,
        y: y - (value * 10 + 10) / 2,
        width: 14,
        height: value * 10 + 10,
        rx: 4,
      },
      svg,
    ),
  );
  link(
    ...(wide
      ? [machine.x + machine.w / 2, y, x - 74, y]
      : [x, machine.y + machine.h / 2, x, y - 46]),
    beat("fixed-size", 0.5) + index * 0.15,
  );
  ctx.timeline.from(
    group,
    { opacity: 0, duration: 0.4, stagger: 0.05 },
    beat("fixed-size", 0.6) + 0.3 + index * 0.15,
  );
  return { group, y };
});
const dot = node(
  "circle",
  { class: "dot", cx: inputs[0].x + sizes[0] / 2, cy: inputs[0].y - 28, r: 12 },
  svg,
);
ctx.timeline.from(dot, { attr: { r: 0 }, duration: 0.4, ease: "back.out(2)" }, beat("tiny", 0.5));
bars[0].group.forEach((bar, index) => {
  ctx.timeline.to(
    bar,
    {
      attr: { y: bars[0].y - (edited[index] * 10 + 10) / 2, height: edited[index] * 10 + 10 },
      duration: 0.6,
      ease: "power2.inOut",
    },
    beat("completely", 1) + index * 0.06,
  );
});
ctx.timeline.from([anyLabel, hash], { opacity: 0, duration: 0.5 }, 0.2);
ctx.timeline.from(fixedLabel, { opacity: 0, duration: 0.5 }, beat("fixed-size", 0.5));
```

```css
.mo-s-demo {
  display: flex;
  align-items: center;
  justify-content: center;
}
.mo-s-demo .scene {
  display: block;
  overflow: visible;
}
.mo-s-demo .machine {
  fill: var(--mo-surface);
  stroke: var(--mo-border);
  stroke-width: 4;
}
.mo-s-demo .input {
  fill: var(--mo-text-muted);
}
.mo-s-demo .bar {
  fill: var(--mo-text-secondary);
}
.mo-s-demo .bar.first {
  fill: var(--mo-accent);
}
.mo-s-demo .dot {
  fill: var(--mo-success);
}
.mo-s-demo .link {
  stroke: var(--mo-border);
  stroke-width: 6;
  stroke-linecap: round;
}
.mo-s-demo .name {
  fill: var(--mo-text-secondary);
  font-family: var(--mo-font);
  font-size: var(--mo-text-body);
  font-weight: 600;
  text-anchor: middle;
  dominant-baseline: central;
}
```
