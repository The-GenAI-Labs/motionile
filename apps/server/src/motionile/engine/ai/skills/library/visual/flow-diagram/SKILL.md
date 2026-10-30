---
name: flow-diagram
description: Flow diagram that builds one step at a time, boxes joined by arrows that draw in as the narrator names each step. Use for processes, pipelines, workflows, algorithms in plain words, request lifecycles, cause and effect chains, decision flows with yes/no branches, and any "first this, then that" explanation of a sequence of three to six stages. Not for layered system architecture (use architecture-build-up) or data over time.
metadata:
  layer: visual
---

# Flow diagram

In the examples the scene root is `.mo-s-demo`; replace `demo` with the real scene id in the CSS. The diagram is SVG built in the builder, sized to `ctx.safeArea`, so it never leaves the safe area.

## When to use

- A sequence of 3 to 5 named steps, or a small decision with two branches.
- The narration walks through the steps in order and names each one.
- More than 5 nodes: split across scenes (stages 1 to 3, then 4 to 6) rather than shrinking boxes. Text below `--mo-text-small` fails validation.

## Structure

1. One beat per node: the node pops in on the word that names it (`ctx.at("word")`), then the arrow into the next node draws so that it finishes as the next word starts.
2. The node being talked about carries a halo (accent outline). The halo moves on with the narration; the finished flow keeps only the last halo.
3. For a branch: the decision node first, then the branch whose word comes first, then the other. Label each branch edge (`yes` / `no`, `hit` / `miss`) on the word that says it.
4. No animation after the last cue; the finished flow holds until the scene ends.

## Do

- Layout by aspect: landscape (`16:9`) lays a chain out as a row, portrait and square as a column. Compute centers as `(index + 0.5) / count` of the safe area. Branching flows use two sets of normalised positions, one for landscape and one for the others.
- Boxes: `rx` about 28, fill `--mo-surface`, stroke `--mo-border` 3 px, label `--mo-text` in `--mo-text-subtitle` weight 700, centered with `dominant-baseline: central`. Labels have at most 12 characters (SVG text does not wrap); 9 or fewer fit in portrait.
- One text line per box. A second line (step number, caption) needs 1.4 times the font size of vertical separation or it fails `text_overlap`.
- Edges end 14 px before the boxes, stroke `--mo-accent` 5 px, with a separate arrowhead path that fades in as the line completes.
- Choose cues from the narration words that name the steps; clamp with `Math.min(time, ctx.duration - 0.6)`.

## Don't

- Do not rely on `DrawSVGPlugin` or `MorphSVGPlugin`; they may not be loaded. Draw lines with `pathLength="1"`, `stroke-dasharray: 1` and a `strokeDashoffset` tween.
- Do not use SVG `marker` or `url(#id)` references, nor `foreignObject`.
- Do not draw arrows through boxes or let edges cross; reorder nodes.
- Do not show all nodes at once and then highlight them; the diagram must build with the voice.
- Do not put sentences in boxes. Boxes hold names; the narration holds the explanation.
- Do not use the danger color except for a failure branch.

## runtime@1 patterns

Draw an edge without a plugin: `from(line, { strokeDashoffset: 1 })` on a path with `pathLength="1"` and CSS `stroke-dasharray: 1`, then `from(head, { opacity: 0 })` at the draw end.

Trim an edge to the box borders in any direction: take the center-to-center vector `(dx, dy)`, scale it by `Math.min(w / 2 / Math.abs(dx), h / 2 / Math.abs(dy))` plus the gap divided by the vector length (see `trim` in the examples), and put the arrowhead at the tip with `Math.atan2`.

Moving halo: one halo rect per node, `opacity` 0 to 1 on its cue and back to 0 on the next cue.

## Examples

#### Example: Three step pipeline

Narration: "First we collect the data, then we clean it, and finally we train the model."

```js
const NS = "http://www.w3.org/2000/svg";
const el = (name, attrs, parent) => {
  const node = document.createElementNS(NS, name);
  Object.keys(attrs).forEach((key) => node.setAttribute(key, attrs[key]));
  parent.append(node);
  return node;
};
const { width, height } = ctx.safeArea;
const svg = el("svg", { width, height, viewBox: `0 0 ${width} ${height}` }, ctx.root);
const wide = ctx.aspect === "16:9";
const size = wide ? { w: 400, h: 200 } : { w: Math.min(620, width * 0.8), h: 150 };
const steps = [
  { label: "Collect", cue: "collect" },
  { label: "Clean", cue: "clean" },
  { label: "Train", cue: "train" },
];
const last = ctx.duration - 0.6;
const cues = steps.map((step) => Math.min(ctx.at(step.cue), last));
const nodes = steps.map((step, i) => {
  const x = wide ? (width * (i + 0.5)) / steps.length : width / 2;
  const y = wide ? height / 2 : (height * (i + 0.5)) / steps.length;
  const group = el("g", {}, svg);
  const rect = { x: x - size.w / 2, y: y - size.h / 2, width: size.w, height: size.h, rx: 28 };
  el("rect", { ...rect, class: "box" }, group);
  const halo = el("rect", { ...rect, class: "halo" }, group);
  const label = el("text", { x, y, class: "label" }, group);
  label.textContent = step.label;
  return { x, y, group, halo };
});
const trim = (from, to, gap) => {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const reach = Math.min(
    size.w / 2 / Math.max(Math.abs(dx), 0.001),
    size.h / 2 / Math.max(Math.abs(dy), 0.001),
  );
  const k = reach + gap / Math.hypot(dx, dy);
  return { x: from.x + dx * k, y: from.y + dy * k };
};
const edges = nodes.slice(1).map((node, i) => {
  const a = trim(nodes[i], node, 14);
  const b = trim(node, nodes[i], 14);
  const angle = Math.atan2(b.y - a.y, b.x - a.x);
  const wing = (turn) =>
    `${b.x - 24 * Math.cos(angle + turn)} ${b.y - 24 * Math.sin(angle + turn)}`;
  const line = el(
    "path",
    { d: `M ${a.x} ${a.y} L ${b.x} ${b.y}`, pathLength: 1, class: "edge" },
    svg,
  );
  const head = el(
    "path",
    { d: `M ${wing(0.5)} L ${b.x} ${b.y} L ${wing(-0.5)}`, class: "head" },
    svg,
  );
  return { line, head };
});
nodes.forEach((node, i) => {
  ctx.timeline.from(
    node.group,
    { opacity: 0, scale: 0.9, transformOrigin: "50% 50%", duration: 0.45, ease: "back.out(1.6)" },
    cues[i],
  );
  ctx.timeline.from(node.halo, { opacity: 0, duration: 0.3 }, cues[i]);
  if (i < nodes.length - 1) {
    ctx.timeline.to(node.halo, { opacity: 0, duration: 0.3 }, cues[i + 1]);
    const start = Math.min(Math.max(cues[i] + 0.2, cues[i + 1] - 0.6), last);
    ctx.timeline.from(
      edges[i].line,
      { strokeDashoffset: 1, duration: 0.45, ease: "power2.inOut" },
      start,
    );
    ctx.timeline.from(edges[i].head, { opacity: 0, duration: 0.15 }, start + 0.4);
  }
});
```

```css
.mo-s-demo svg {
  display: block;
}
.mo-s-demo .box {
  fill: var(--mo-surface);
  stroke: var(--mo-border);
  stroke-width: 3;
}
.mo-s-demo .halo {
  fill: none;
  stroke: var(--mo-accent);
  stroke-width: 4;
}
.mo-s-demo .label {
  fill: var(--mo-text);
  font-size: var(--mo-text-subtitle);
  font-weight: 700;
  text-anchor: middle;
  dominant-baseline: central;
}
.mo-s-demo .edge {
  fill: none;
  stroke: var(--mo-accent);
  stroke-width: 5;
  stroke-dasharray: 1;
}
.mo-s-demo .head {
  fill: none;
  stroke: var(--mo-accent);
  stroke-width: 5;
  stroke-linecap: round;
  stroke-linejoin: round;
}
```

#### Example: Decision with two branches

Narration: "If the cache has the answer, return it at once. Otherwise ask the database, then save the result."

```js
const NS = "http://www.w3.org/2000/svg";
const el = (name, attrs, parent) => {
  const node = document.createElementNS(NS, name);
  Object.keys(attrs).forEach((key) => node.setAttribute(key, attrs[key]));
  parent.append(node);
  return node;
};
const { width, height } = ctx.safeArea;
const svg = el("svg", { width, height, viewBox: `0 0 ${width} ${height}` }, ctx.root);
const wide = ctx.aspect === "16:9";
const size = wide ? { w: 340, h: 170 } : { w: 400, h: 150 };
const spots = wide
  ? [
      [0.16, 0.5],
      [0.7, 0.18],
      [0.5, 0.8],
      [0.86, 0.8],
    ]
  : [
      [0.5, 0.13],
      [0.27, 0.5],
      [0.73, 0.5],
      [0.73, 0.87],
    ];
const steps = [
  { label: "In cache?", cue: "cache" },
  { label: "Return it", cue: "return" },
  { label: "Ask DB", cue: "ask" },
  { label: "Save it", cue: "save" },
];
const links = [
  { from: 0, to: 1, text: "yes", side: -1 },
  { from: 0, to: 2, text: "no", side: 1 },
  { from: 2, to: 3, text: "", side: 1 },
];
const last = ctx.duration - 0.6;
const at = (cue) => Math.min(ctx.at(cue), last);
const nodes = steps.map((step, i) => {
  const x = spots[i][0] * width;
  const y = spots[i][1] * height;
  const group = el("g", {}, svg);
  el(
    "rect",
    {
      x: x - size.w / 2,
      y: y - size.h / 2,
      width: size.w,
      height: size.h,
      rx: 28,
      class: i === 0 ? "box decision" : "box",
    },
    group,
  );
  const label = el("text", { x, y, class: "label" }, group);
  label.textContent = step.label;
  ctx.timeline.from(
    group,
    { opacity: 0, scale: 0.9, transformOrigin: "50% 50%", duration: 0.45, ease: "back.out(1.6)" },
    at(step.cue),
  );
  return { x, y };
});
const trim = (from, to, gap) => {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const reach = Math.min(
    size.w / 2 / Math.max(Math.abs(dx), 0.001),
    size.h / 2 / Math.max(Math.abs(dy), 0.001),
  );
  const k = reach + gap / Math.hypot(dx, dy);
  return { x: from.x + dx * k, y: from.y + dy * k };
};
links.forEach((link) => {
  const a = trim(nodes[link.from], nodes[link.to], 14);
  const b = trim(nodes[link.to], nodes[link.from], 14);
  const angle = Math.atan2(b.y - a.y, b.x - a.x);
  const wing = (turn) =>
    `${b.x - 24 * Math.cos(angle + turn)} ${b.y - 24 * Math.sin(angle + turn)}`;
  const line = el(
    "path",
    { d: `M ${a.x} ${a.y} L ${b.x} ${b.y}`, pathLength: 1, class: "edge" },
    svg,
  );
  const head = el(
    "path",
    { d: `M ${wing(0.5)} L ${b.x} ${b.y} L ${wing(-0.5)}`, class: "head" },
    svg,
  );
  const start = Math.min(Math.max(at(steps[link.to].cue) - 0.6, 0), last);
  ctx.timeline.from(line, { strokeDashoffset: 1, duration: 0.45, ease: "power2.inOut" }, start);
  ctx.timeline.from(head, { opacity: 0, duration: 0.15 }, start + 0.4);
  if (link.text) {
    const tag = el(
      "text",
      {
        x: (a.x + b.x) / 2 - link.side * Math.sin(angle) * 44,
        y: (a.y + b.y) / 2 + link.side * Math.cos(angle) * 44,
        class: "tag",
      },
      svg,
    );
    tag.textContent = link.text;
    ctx.timeline.from(tag, { opacity: 0, duration: 0.3 }, start);
  }
});
```

```css
.mo-s-demo svg {
  display: block;
}
.mo-s-demo .box {
  fill: var(--mo-surface);
  stroke: var(--mo-border);
  stroke-width: 3;
}
.mo-s-demo .decision {
  stroke: var(--mo-accent);
}
.mo-s-demo .label {
  fill: var(--mo-text);
  font-size: var(--mo-text-subtitle);
  font-weight: 700;
  text-anchor: middle;
  dominant-baseline: central;
}
.mo-s-demo .tag {
  fill: var(--mo-text-secondary);
  font-family: var(--mo-font-mono);
  font-size: var(--mo-text-small);
  text-anchor: middle;
  dominant-baseline: central;
}
.mo-s-demo .edge {
  fill: none;
  stroke: var(--mo-accent);
  stroke-width: 5;
  stroke-dasharray: 1;
}
.mo-s-demo .head {
  fill: none;
  stroke: var(--mo-accent);
  stroke-width: 5;
  stroke-linecap: round;
  stroke-linejoin: round;
}
```
