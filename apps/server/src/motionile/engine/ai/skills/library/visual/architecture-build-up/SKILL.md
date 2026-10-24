---
name: architecture-build-up
description: Layered system architecture diagram built up progressively, boxes grouped into tiers (client, edge, services, data), connections drawn between them, and a request path traced through the components in step with the narration. Use for system design, backend and cloud architecture, microservices, load balancers, caches, queues, databases, API gateways and "how a request travels through the system".
metadata:
  layer: visual
---

# Architecture build-up

In the examples the scene root is `.mo-s-demo`; replace `demo` with the real scene id in the CSS. The diagram is SVG built in the builder and sized to `ctx.safeArea`.

## When to use

- Components in tiers that talk to each other.
- Build-up mode: the narration introduces components one by one. Trace mode: it follows one request through a system shown at once.
- Plain sequence with no tiers: use `flow-diagram`. More than 3 layers or 6 boxes: split the scene.

## Structure

Build-up, one beat per component: the layer band fades in on its first box's cue, the box pops on the word naming it, and the arrow from the component it depends on draws in, finishing as the box lands.

Trace, three beats: (1) scaffold, bands, boxes and dim connections fade in with a short stagger in the first 1.2 s; (2) a dot starts at the first component on its word and travels each connection, arriving as the next component is named, while the connection turns accent and the component keeps a halo; (3) hold.

## Do

- Layers are horizontal bands stacked top to bottom (client above, data below) in every aspect; at most 3 boxes per band, centered at `(col + 0.5) / count` of the width.
- Band fill `--mo-surface`, layer name top-left in `--mo-text-small` muted. Box fill `--mo-elevated`, label `--mo-text-body` weight 700, at most 12 characters, height `Math.min(150, bandHeight - 70)` so the layer name never meets a box.
- Connections run between box borders (the `trim` helper): muted when structural, accent and thicker when traced. Never route through a box.
- Name components by role in the narrated order and cue from those words. Show only what the narration mentions; keep one accent.

## Don't

- Do not draw every real connection or label connections with protocols.
- Do not use `DrawSVGPlugin`, SVG `marker`, `url(#id)` or `foreignObject`; draw lines with `pathLength="1"`, `stroke-dasharray: 1` and `strokeDashoffset`.
- Do not place the traveling dot above boxes: it covers labels (`contrast_low`). Append it after the bands and before the boxes. Keep each hop between 0.3 s and 1.2 s.

## runtime@1 patterns

Geometry needs no aspect branches: derive band height from the safe-area height and layer count.

Traveling dot: a `circle` at `cx=0 cy=0`, set with `gsap.set(dot, { x, y })` and moved with `timeline.to(dot, { x, y })`.

## Examples

#### Example: Components named one by one

Narration: "The browser sends requests to an API. The API checks a cache first, and falls back to the database."

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
const layers = [
  { name: "Client", boxes: [{ id: "Browser", cue: "browser" }] },
  {
    name: "Service",
    boxes: [
      { id: "API", cue: "api" },
      { id: "Cache", cue: "cache" },
    ],
  },
  { name: "Data", boxes: [{ id: "Database", cue: "database" }] },
];
const links = [
  ["Browser", "API"],
  ["API", "Cache"],
  ["API", "Database"],
];
const gap = 14;
const bandH = (height - gap * (layers.length - 1)) / layers.length;
const boxH = Math.min(150, bandH - 70);
const at = (cue) => Math.min(ctx.at(cue), ctx.duration - 0.6);
const nodes = {};
layers.forEach((layer, row) => {
  const band = el("g", {}, svg);
  el("rect", { x: 0, y: row * (bandH + gap), width, height: bandH, rx: 24, class: "band" }, band);
  el("text", { x: 28, y: row * (bandH + gap) + 30, class: "layer" }, band).textContent = layer.name;
  ctx.timeline.from(band, { opacity: 0, duration: 0.4 }, Math.max(at(layer.boxes[0].cue) - 0.3, 0));
});
layers.forEach((layer, row) => {
  layer.boxes.forEach((box, col) => {
    const w = Math.min(380, width / layer.boxes.length - 40);
    const x = (width * (col + 0.5)) / layer.boxes.length;
    const y = row * (bandH + gap) + 56 + (bandH - 70) / 2;
    const group = el("g", {}, svg);
    el(
      "rect",
      { x: x - w / 2, y: y - boxH / 2, width: w, height: boxH, rx: 20, class: "box" },
      group,
    );
    el("text", { x, y, class: "name" }, group).textContent = box.id;
    ctx.timeline.from(
      group,
      { opacity: 0, scale: 0.9, transformOrigin: "50% 50%", duration: 0.45, ease: "back.out(1.6)" },
      at(box.cue),
    );
    nodes[box.id] = { x, y, w, cue: at(box.cue) };
  });
});
const trim = (from, to) => {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const k =
    Math.min(from.w / 2 / (Math.abs(dx) || 0.001), boxH / 2 / (Math.abs(dy) || 0.001)) +
    12 / Math.hypot(dx, dy);
  return { x: from.x + dx * k, y: from.y + dy * k };
};
links.forEach(([from, to]) => {
  const a = trim(nodes[from], nodes[to]);
  const b = trim(nodes[to], nodes[from]);
  const angle = Math.atan2(b.y - a.y, b.x - a.x);
  const wing = (turn) =>
    `${b.x - 22 * Math.cos(angle + turn)} ${b.y - 22 * Math.sin(angle + turn)}`;
  const line = el(
    "path",
    { d: `M ${a.x} ${a.y} L ${b.x} ${b.y}`, pathLength: 1, class: "link" },
    svg,
  );
  const head = el(
    "path",
    { d: `M ${wing(0.5)} L ${b.x} ${b.y} L ${wing(-0.5)}`, class: "head" },
    svg,
  );
  const start = Math.max(nodes[to].cue - 0.6, 0);
  ctx.timeline.from(line, { strokeDashoffset: 1, duration: 0.45, ease: "power2.inOut" }, start);
  ctx.timeline.from(head, { opacity: 0, duration: 0.15 }, start + 0.4);
});
```

```css
.mo-s-demo svg {
  display: block;
}
.mo-s-demo .band {
  fill: var(--mo-surface);
  stroke: var(--mo-border);
  stroke-width: 2;
}
.mo-s-demo .layer {
  fill: var(--mo-text-muted);
  font-size: var(--mo-text-small);
  font-weight: 600;
  dominant-baseline: central;
}
.mo-s-demo .box {
  fill: var(--mo-elevated);
  stroke: var(--mo-text-muted);
  stroke-width: 3;
}
.mo-s-demo .name {
  fill: var(--mo-text);
  font-size: var(--mo-text-body);
  font-weight: 700;
  text-anchor: middle;
  dominant-baseline: central;
}
.mo-s-demo .link,
.mo-s-demo .head {
  fill: none;
  stroke: var(--mo-accent);
  stroke-width: 5;
  stroke-linejoin: round;
}
.mo-s-demo .link {
  stroke-dasharray: 1;
}
```

#### Example: Tracing one request

Narration: "A request leaves the app, enters through the gateway, passes the auth service, reaches the orders service, and is written to the database."

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
const layers = [
  { name: "Client", boxes: ["App"] },
  { name: "Edge", boxes: ["Gateway"] },
  { name: "Services", boxes: ["Auth", "Orders"] },
  { name: "Data", boxes: ["Database"] },
];
const path = [
  ["App", "app"],
  ["Gateway", "gateway"],
  ["Auth", "auth"],
  ["Orders", "orders"],
  ["Database", "database"],
];
const gap = 14;
const bandH = (height - gap * (layers.length - 1)) / layers.length;
const boxH = Math.min(150, bandH - 70);
const at = (cue) => Math.min(ctx.at(cue), ctx.duration - 0.6);
const nodes = {};
layers.forEach((layer, row) => {
  el("rect", { x: 0, y: row * (bandH + gap), width, height: bandH, rx: 24, class: "band" }, svg);
  el("text", { x: 28, y: row * (bandH + gap) + 30, class: "layer" }, svg).textContent = layer.name;
});
const dot = el("circle", { r: 16, cx: 0, cy: 0, class: "dot" }, svg);
layers.forEach((layer, row) => {
  layer.boxes.forEach((id, col) => {
    const w = Math.min(380, width / layer.boxes.length - 40);
    const x = (width * (col + 0.5)) / layer.boxes.length;
    const y = row * (bandH + gap) + 56 + (bandH - 70) / 2;
    const place = { x: x - w / 2, y: y - boxH / 2, width: w, height: boxH, rx: 20 };
    el("rect", { ...place, class: "box" }, svg);
    el("text", { x, y, class: "name" }, svg).textContent = id;
    nodes[id] = { x, y, w, halo: el("rect", { ...place, class: "halo" }, svg) };
  });
});
const trim = (from, to) => {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const k =
    Math.min(from.w / 2 / (Math.abs(dx) || 0.001), boxH / 2 / (Math.abs(dy) || 0.001)) +
    12 / Math.hypot(dx, dy);
  return { x: from.x + dx * k, y: from.y + dy * k };
};
const arrow = (from, to, className) => {
  const a = trim(nodes[from], nodes[to]);
  const b = trim(nodes[to], nodes[from]);
  const angle = Math.atan2(b.y - a.y, b.x - a.x);
  const wing = (turn) =>
    `${b.x - 22 * Math.cos(angle + turn)} ${b.y - 22 * Math.sin(angle + turn)}`;
  const line = el(
    "path",
    { d: `M ${a.x} ${a.y} L ${b.x} ${b.y}`, pathLength: 1, class: className },
    svg,
  );
  const head = el(
    "path",
    { d: `M ${wing(0.5)} L ${b.x} ${b.y} L ${wing(-0.5)}`, class: `head ${className}` },
    svg,
  );
  return { line, head };
};
path.slice(1).forEach(([id], i) => arrow(path[i][0], id, "base"));
gsap.set(dot, { x: nodes.App.x, y: nodes.App.y });
ctx.timeline.from(
  svg.querySelectorAll(".band, .layer, .box, .name, .base"),
  { opacity: 0, duration: 0.4, stagger: 0.04 },
  0.1,
);
path.forEach(([id, cue], i) => {
  const start = at(cue);
  ctx.timeline.from(nodes[id].halo, { opacity: 0, duration: 0.3 }, start);
  if (i === 0) {
    ctx.timeline.from(dot, { opacity: 0, duration: 0.2 }, start);
    return;
  }
  const begin = at(path[i - 1][1]) + 0.15;
  const span = Math.max(0.3, Math.min(start - begin - 0.05, 1.2));
  const trace = arrow(path[i - 1][0], id, "trace");
  ctx.timeline.from(
    trace.line,
    { strokeDashoffset: 1, duration: span, ease: "power1.inOut" },
    begin,
  );
  ctx.timeline.from(trace.head, { opacity: 0, duration: 0.15 }, begin + span);
  ctx.timeline.to(
    dot,
    { x: nodes[id].x, y: nodes[id].y, duration: span, ease: "power1.inOut" },
    begin,
  );
});
```

```css
.mo-s-demo svg {
  display: block;
}
.mo-s-demo .band {
  fill: var(--mo-surface);
  stroke: var(--mo-border);
  stroke-width: 2;
}
.mo-s-demo .layer {
  fill: var(--mo-text-muted);
  font-size: var(--mo-text-small);
  font-weight: 600;
  dominant-baseline: central;
}
.mo-s-demo .box {
  fill: var(--mo-elevated);
  stroke: var(--mo-border);
  stroke-width: 3;
}
.mo-s-demo .halo {
  fill: none;
  stroke: var(--mo-accent);
  stroke-width: 4;
}
.mo-s-demo .name {
  fill: var(--mo-text);
  font-size: var(--mo-text-body);
  font-weight: 700;
  text-anchor: middle;
  dominant-baseline: central;
}
.mo-s-demo .base,
.mo-s-demo .trace {
  fill: none;
  stroke-linejoin: round;
  stroke-linecap: butt;
}
.mo-s-demo .base {
  stroke: var(--mo-text-muted);
  stroke-width: 3;
}
.mo-s-demo .trace {
  stroke: var(--mo-accent);
  stroke-width: 6;
  stroke-dasharray: 1;
}
.mo-s-demo .head.trace {
  stroke-dasharray: none;
  stroke-linecap: round;
}
.mo-s-demo .dot {
  fill: var(--mo-accent);
}
```
