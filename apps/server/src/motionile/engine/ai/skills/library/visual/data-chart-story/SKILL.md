---
name: data-chart-story
description: Bar, line and scatter charts drawn as inline SVG that tell one insight per beat - growth, decline, peak, comparison between categories, trend over time, correlation, before and after numbers, statistics, survey results, benchmarks. The builder computes scales in JavaScript, draws axes first, then reveals data on the narration words and annotates the key data point. Use only with numbers given in the brief or narration. Not for diagrams of structure (flow-diagram) or formulas (math-equation).
metadata:
  layer: visual
---

# Data chart story

In examples the scene root class is `.mo-s-demo`; replace `demo` with the real scene id.

## When to use

The point of the scene is a number, a trend, a ranking or a relationship, and the data has at most 12 points (bar: 3 to 6 bars; line: up to 12 points; scatter: up to 20 dots). Use only values stated in the brief or narration; never invent data. Label the unit in the heading.

## Structure

1. Heading and axes appear first (0.1 to 0.6 s): the viewer sees the frame before the data.
2. One beat per insight, never per data point: bars or line segments enter on the words that name them.
3. The key data point gets an accent colour and a one-line annotation ("Peak: 120") on the word that states it.
4. Everything else stays muted. Hold the final state for at least 0.6 s.

## Do

- Build the SVG at 1:1 pixel scale: `viewBox="0 0 W H"` and `width`/`height` attributes equal to W and H, with W and H taken from `ctx.safeArea` minus the heading (reserve about 110 px in landscape and 170 px otherwise). Then CSS font sizes inside the SVG are real pixels.
- Compute scales in the builder: `y = bottom - (value / axisMax) * plotHeight`, with a round axis maximum above the data so annotations fit inside the plot. Three to five gridlines.
- Axis labels, tick labels and category labels use `--mo-text-small` or larger and `--mo-text-secondary`; annotations use `--mo-text-body`, `--mo-text`, bold.
- Thin the ticks when crowded (portrait: every third month, three-letter day names). Labels may never touch.
- Muted series `--mo-text-muted`, the highlighted series `--mo-accent`; gridlines `--mo-border`.
- Grow bars with `from(rect, { attr: { height: 0, y: bottom } })`; draw lines by animating `strokeDashoffset`; pop dots by animating `attr: { r }`.
- Put annotation text at the start of its anchor and keep it clear of strokes and bars: the contrast check reads the pixels behind text.
- Scatter: circles with `r` of at least 10, a trend line only when the narration says "trend"; label the axes with what they measure.

## Don't

- Do not truncate a bar axis above zero; do not use 3D, pies with more than four slices or dual axes.
- Do not label every data point; the narration carries the numbers.
- Do not place a label on top of a line, bar or another label.
- Do not scale the SVG with CSS `width: 100%`; set pixel attributes so text is not shrunk.

## runtime@1 patterns

Create SVG nodes with one `node(name, attrs, parent, text)` helper built on `document.createElementNS` and `setAttribute` (both examples).

Draw a path on a cue: with `length = path.getTotalLength()`, `ctx.timeline.set(path, { strokeDasharray: length, strokeDashoffset: length }, 0)`, then `ctx.timeline.to(path, { strokeDashoffset: 0, duration, ease: "none" }, at)`. Draw one path in phases by ending each phase at the cumulative length so far; never overlay two paths on the same point.

## Examples

#### Example: Bar chart with a peak

Narration: "Tickets arrive mostly on Monday at 120, then drop through Tuesday, Wednesday and Thursday to just 40 on Friday."

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
const heading = document.createElement("p");
heading.className = "heading";
heading.textContent = "Support tickets per weekday";
ctx.root.append(heading);
const W = ctx.safeArea.width;
const H = ctx.safeArea.height - (ctx.aspect === "16:9" ? 110 : 170);
const svg = node(
  "svg",
  { class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H },
  ctx.root,
);
const plot = { left: 100, right: W - 20, top: 20, bottom: H - 70 };
const axisMax = 160;
const y = (value) => plot.bottom - (value / axisMax) * (plot.bottom - plot.top);
for (let value = 0; value <= axisMax; value += 40) {
  node("line", { class: "grid", x1: plot.left, x2: plot.right, y1: y(value), y2: y(value) }, svg);
  node("text", { class: "tick", x: plot.left - 16, y: y(value) }, svg, String(value));
}
const days = [
  ["Mon", 120, "monday"],
  ["Tue", 95, "tuesday"],
  ["Wed", 80, "wednesday"],
  ["Thu", 60, "thursday"],
  ["Fri", 40, "friday"],
];
const slot = (plot.right - plot.left) / days.length;
const barWidth = slot * 0.6;
const bars = days.map(([label, value, cue], index) => {
  const x = plot.left + slot * index + (slot - barWidth) / 2;
  const bar = node(
    "rect",
    {
      class: index === 0 ? "bar key" : "bar",
      x,
      y: y(value),
      width: barWidth,
      height: plot.bottom - y(value),
      rx: 6,
    },
    svg,
  );
  const name = node(
    "text",
    { class: "label", x: x + barWidth / 2, y: plot.bottom + 44 },
    svg,
    label,
  );
  ctx.timeline.from(
    bar,
    { attr: { height: 0, y: plot.bottom }, duration: 0.6, ease: "power3.out" },
    beat(cue, 0.6),
  );
  ctx.timeline.from(name, { opacity: 0, duration: 0.4 }, beat(cue, 0.4));
  return { x, value };
});
const note = (text, x, value, cue, anchor) => {
  const label = node("text", { class: `note ${anchor}`, x, y: y(value) - 30 }, svg, text);
  ctx.timeline.from(
    label,
    { opacity: 0, y: "+=12", duration: 0.4, ease: "power2.out" },
    beat(cue, 0.4),
  );
};
note("Peak: 120", bars[0].x, 120, "120", "start");
note("Just 40", bars[4].x + barWidth / 2, 40, "40", "middle");
ctx.timeline.from(
  [heading, ...svg.querySelectorAll(".grid, .tick")],
  { opacity: 0, duration: 0.5 },
  0.1,
);
```

```css
.mo-s-demo {
  display: flex;
  flex-direction: column;
  gap: calc(var(--mo-unit) * 2);
}
.mo-s-demo .heading {
  margin: 0;
  font-size: var(--mo-text-body);
  font-weight: 600;
  line-height: 1.3;
  color: var(--mo-text);
}
.mo-s-demo .chart {
  display: block;
  overflow: visible;
}
.mo-s-demo .grid {
  stroke: var(--mo-border);
  stroke-width: 2;
}
.mo-s-demo .bar {
  fill: var(--mo-text-muted);
}
.mo-s-demo .bar.key {
  fill: var(--mo-accent);
}
.mo-s-demo .tick,
.mo-s-demo .label {
  fill: var(--mo-text-secondary);
  font-family: var(--mo-font-mono);
  font-size: var(--mo-text-small);
  dominant-baseline: central;
}
.mo-s-demo .tick {
  text-anchor: end;
}
.mo-s-demo .label {
  text-anchor: middle;
}
.mo-s-demo .note {
  fill: var(--mo-text);
  font-size: var(--mo-text-body);
  font-weight: 700;
  dominant-baseline: central;
}
.mo-s-demo .start {
  text-anchor: start;
}
.mo-s-demo .middle {
  text-anchor: middle;
}
```

#### Example: Line chart with a turning point

Narration: "Signups were flat through spring, then climbed sharply every month from June, ending the year at four times where they started."

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
const heading = document.createElement("p");
heading.className = "heading";
heading.textContent = "Signups, January = 100";
ctx.root.append(heading);
const W = ctx.safeArea.width;
const H = ctx.safeArea.height - (ctx.aspect === "16:9" ? 110 : 170);
const svg = node(
  "svg",
  { class: "chart", viewBox: `0 0 ${W} ${H}`, width: W, height: H },
  ctx.root,
);
const plot = { left: 100, right: W - 30, top: 70, bottom: H - 70 };
const values = [100, 100, 105, 100, 100, 150, 200, 250, 300, 350, 380, 400];
const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const x = (index) => plot.left + (index / (values.length - 1)) * (plot.right - plot.left);
const y = (value) => plot.bottom - (value / 400) * (plot.bottom - plot.top);
[0, 200, 400].forEach((value) => {
  node("line", { class: "grid", x1: plot.left, x2: plot.right, y1: y(value), y2: y(value) }, svg);
  node("text", { class: "tick", x: plot.left - 16, y: y(value) }, svg, String(value));
});
months.forEach((month, index) => {
  if (index % 3 === 0) {
    node("text", { class: "label", x: x(index), y: plot.bottom + 44 }, svg, month);
  }
});
const points = values.map((value, index) => [x(index), y(value)]);
const line = node(
  "path",
  {
    class: "line",
    d: points.map(([px, py], index) => `${index === 0 ? "M" : "L"} ${px} ${py}`).join(" "),
  },
  svg,
);
const length = line.getTotalLength();
const turn = points
  .slice(1, 5)
  .reduce(
    (sum, [px, py], index) => sum + Math.hypot(px - points[index][0], py - points[index][1]),
    0,
  );
const flatStart = beat("flat", 1);
const climbStart = beat("climbed", 1);
const climbEnd = Math.max(beat("ending", 0.8), climbStart + 0.8);
ctx.timeline.set(line, { strokeDasharray: length, strokeDashoffset: length }, 0);
ctx.timeline.to(
  line,
  {
    strokeDashoffset: length - turn,
    duration: Math.max(climbStart - flatStart, 0.8),
    ease: "none",
  },
  flatStart,
);
ctx.timeline.to(
  line,
  { strokeDashoffset: 0, duration: climbEnd - climbStart, ease: "none" },
  climbStart,
);
const mark = (index, text, anchor, dx, dy, cue) => {
  const dot = node("circle", { class: "dot", cx: x(index), cy: y(values[index]), r: 12 }, svg);
  const label = node(
    "text",
    { class: `note ${anchor}`, x: x(index) + dx, y: y(values[index]) + dy },
    svg,
    text,
  );
  ctx.timeline.from(dot, { attr: { r: 0 }, duration: 0.4, ease: "back.out(2)" }, beat(cue, 0.5));
  ctx.timeline.from(label, { opacity: 0, duration: 0.4 }, beat(cue, 0.5));
};
mark(5, "June", "start", 20, 50, "june");
mark(11, "4× January", "end", 0, -36, "four");
ctx.timeline.from(
  [heading, ...svg.querySelectorAll(".grid, .tick, .label")],
  { opacity: 0, duration: 0.5 },
  0.1,
);
```

```css
.mo-s-demo {
  display: flex;
  flex-direction: column;
  gap: calc(var(--mo-unit) * 2);
}
.mo-s-demo .heading {
  margin: 0;
  font-size: var(--mo-text-body);
  font-weight: 600;
  line-height: 1.3;
  color: var(--mo-text);
}
.mo-s-demo .chart {
  display: block;
  overflow: visible;
}
.mo-s-demo .grid {
  stroke: var(--mo-border);
  stroke-width: 2;
}
.mo-s-demo .line {
  fill: none;
  stroke: var(--mo-accent);
  stroke-width: 8;
  stroke-linejoin: round;
}
.mo-s-demo .dot {
  fill: var(--mo-accent);
}
.mo-s-demo .tick,
.mo-s-demo .label {
  fill: var(--mo-text-secondary);
  font-family: var(--mo-font-mono);
  font-size: var(--mo-text-small);
  dominant-baseline: central;
}
.mo-s-demo .tick {
  text-anchor: end;
}
.mo-s-demo .label {
  text-anchor: middle;
}
.mo-s-demo .note {
  fill: var(--mo-text);
  font-size: var(--mo-text-body);
  font-weight: 700;
  dominant-baseline: central;
}
.mo-s-demo .start {
  text-anchor: start;
}
.mo-s-demo .end {
  text-anchor: end;
}
```
