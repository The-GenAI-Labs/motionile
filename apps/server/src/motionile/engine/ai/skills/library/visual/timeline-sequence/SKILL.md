---
name: timeline-sequence
description: Ordered or dated events revealed one by one along a line - history of a technology or company, release timeline, project phases, milestones, a process over time, first then next then finally. Horizontal axis in landscape, vertical in portrait and square, with a current-event marker that follows the narration. Even spacing for steps, proportional spacing when gaps between real dates matter. Not for branching flows (flow-diagram) or numeric trends (data-chart-story).
metadata:
  layer: visual
---

# Timeline sequence

In examples the scene root class is `.mo-s-demo`; replace `demo` with the real scene id.

## When to use

The narration walks through three to five events in time order, each with a short label and ideally a date or ordinal. More than five events: split scenes or keep the turning points. Branching or looping stories use `flow-diagram`.

## Structure

1. The first event appears on its own word, normally within 2 s, so the middle of the scene is never empty.
2. One beat per event: the line travels to it, its dot pops, its date and label slide in, all timed to the word that names the event or its date.
3. The newest event is current: filled dot; the previous dot returns to an outline. Earlier events stay.
4. The last event holds still for at least 0.6 s.

## Do

- Spacing is a decision. Even grid columns for steps and phases. Proportional (`(year - first) / span`) when the narration stresses long gaps or bursts, with a minimum gap and labels alternating above and below the axis in landscape.
- Landscape: horizontal axis, date above, label below. Portrait and square: vertical axis at the left, text to its right. Branch CSS with a `stage` container query and tweens with `ctx.aspect`.
- Dates in `--mo-font-mono` and `--mo-accent`, labels in `--mo-text` at `--mo-text-body`, at most three words each.
- Cue from the date word (`ctx.at("1995")`) or an ordinal (`ctx.at("then", 1)` for the second "then").
- The line is a real element scaled from 0 with `transform-origin` at its start; it arrives 0.4 to 0.5 s before the dot.
- At most five events; four in 1:1 when labels have more than two words.

## Don't

- Do not use fixed widths for side-by-side labels; use `minmax(0, 1fr)` columns or positions computed from `ctx.safeArea`.
- Do not show dates the brief and narration do not state.
- Do not scale text from 0; scale dots, slide text.
- Do not dim past events below opacity 0.6, and never dim muted or coloured text.

## runtime@1 patterns

Line segment that arrives just before the next dot:

```js
ctx.timeline.from(
  line,
  wide ? { scaleX: 0, duration: 0.5 } : { scaleY: 0, duration: 0.5 },
  Math.max(at - 0.5, previousAt + 0.2),
);
```

Current-event marker: each dot owns an inner fill; `ctx.timeline.set(fill, { scale: 0 }, 0)`, scale it to 1 on its cue and back to 0 on the next cue.

Proportional positions need a minimum gap on a vertical axis: `previous = Math.max(previous + minGap, proportional)` (second example).

## Examples

#### Example: Four moments, even spacing

Narration: "In 1989 Tim Berners-Lee proposed the web. CERN made it free in 1993, JavaScript arrived in 1995 and the iPhone followed in 2007."

```js
const events = [
  { when: "1989", what: "Web proposed", cue: "1989" },
  { when: "1993", what: "Free for all", cue: "1993" },
  { when: "1995", what: "JavaScript", cue: "1995" },
  { when: "2007", what: "iPhone", cue: "2007" },
];
const wide = ctx.aspect === "16:9";
const beat = (target, length) => Math.min(ctx.at(target), ctx.duration - length);
const make = (tag, className) => {
  const element = document.createElement(tag);
  element.className = className;
  return element;
};
const track = make("div", "track");
ctx.root.append(track);
const parts = events.map((spec, index) => {
  const event = make("div", "event");
  const [when, what] = [make("p", "when"), make("p", "what")];
  const [marker, dot, fill] = [make("div", "marker"), make("div", "dot"), make("div", "fill")];
  const line = index < events.length - 1 ? make("div", "line") : null;
  when.textContent = spec.when;
  what.textContent = spec.what;
  dot.append(fill);
  marker.append(dot, ...(line ? [line] : []));
  event.append(when, marker, what);
  track.append(event);
  return { when, what, dot, fill, line };
});
const ats = events.map((spec) => beat(spec.cue, 0.6));
parts.forEach((part, index) => {
  const at = ats[index];
  ctx.timeline.set(part.fill, { scale: 0 }, 0);
  ctx.timeline.from(part.dot, { scale: 0, duration: 0.4, ease: "back.out(2)" }, at);
  ctx.timeline.from(
    [part.when, part.what],
    {
      opacity: 0,
      x: wide ? 0 : 24,
      y: wide ? 24 : 0,
      duration: 0.5,
      stagger: 0.1,
      ease: "power3.out",
    },
    at,
  );
  ctx.timeline.to(part.fill, { scale: 1, duration: 0.3 }, at);
  if (index > 0) {
    ctx.timeline.to(parts[index - 1].fill, { scale: 0, duration: 0.3 }, at);
    ctx.timeline.from(
      parts[index - 1].line,
      wide ? { scaleX: 0, duration: 0.5 } : { scaleY: 0, duration: 0.5 },
      Math.max(at - 0.5, ats[index - 1] + 0.2),
    );
  }
});
```

```css
.mo-s-demo {
  --dot: calc(var(--mo-unit) * 2.4);
  --gap: calc(var(--mo-unit) * 4);
  --lift: calc((var(--mo-text-body) * 1.3 - var(--dot)) / 2);
  display: flex;
  align-items: center;
}
.mo-s-demo .track {
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(0, 1fr);
  width: 100%;
}
.mo-s-demo .event {
  display: grid;
  grid-template-areas: "when" "marker" "what";
  grid-template-rows: auto auto 1fr;
  justify-items: center;
  row-gap: calc(var(--mo-unit) * 1.4);
  text-align: center;
}
.mo-s-demo .when {
  grid-area: when;
  margin: 0;
  font-family: var(--mo-font-mono);
  font-size: var(--mo-text-body);
  font-weight: 600;
  line-height: 1.3;
  color: var(--mo-accent);
}
.mo-s-demo .what {
  grid-area: what;
  margin: 0;
  font-size: var(--mo-text-body);
  line-height: 1.25;
  color: var(--mo-text);
}
.mo-s-demo .marker {
  grid-area: marker;
  position: relative;
  width: 100%;
  height: var(--dot);
}
.mo-s-demo .dot {
  position: absolute;
  left: 50%;
  top: 0;
  z-index: 1;
  width: var(--dot);
  height: var(--dot);
  margin-left: calc(var(--dot) / -2);
  overflow: hidden;
  border: 4px solid var(--mo-accent);
  border-radius: 999px;
  background: var(--mo-bg);
}
.mo-s-demo .fill {
  position: absolute;
  inset: 0;
  border-radius: 999px;
  background: var(--mo-accent);
}
.mo-s-demo .line {
  position: absolute;
  top: calc(var(--dot) / 2 - 2px);
  left: 50%;
  right: -50%;
  height: 4px;
  background: var(--mo-accent);
  transform-origin: 0 50%;
}
@container stage (aspect-ratio <= 1) {
  .mo-s-demo .track {
    grid-auto-flow: row;
    grid-auto-columns: auto;
    row-gap: var(--gap);
  }
  .mo-s-demo .event {
    grid-template-areas: "marker when" "marker what";
    grid-template-columns: var(--dot) minmax(0, 1fr);
    grid-template-rows: auto auto;
    column-gap: calc(var(--mo-unit) * 3);
    row-gap: 0;
    justify-items: start;
    text-align: left;
  }
  .mo-s-demo .marker {
    width: var(--dot);
    height: 100%;
  }
  .mo-s-demo .dot {
    top: var(--lift);
    left: 0;
    margin-left: 0;
  }
  .mo-s-demo .line {
    top: calc(var(--lift) + var(--dot) / 2 - 2px);
    bottom: calc(0px - var(--gap) - var(--lift) - var(--dot) / 2);
    left: 50%;
    right: auto;
    width: 4px;
    height: auto;
    margin-left: -2px;
    transform-origin: 50% 0;
  }
}
```

#### Example: Proportional axis from real years

Narration: "Turing asked if machines can think in 1950. The name AI came in 1956, Deep Blue beat Kasparov in 1997, AlphaGo won in 2016."

```js
const events = [
  { year: 1950, what: "Turing asks" },
  { year: 1956, what: "AI named" },
  { year: 1997, what: "Deep Blue" },
  { year: 2016, what: "AlphaGo" },
];
const wide = ctx.aspect === "16:9";
const { width, height } = ctx.safeArea;
const blockWidth = wide ? 380 : width - 80;
const blockHeight = 130;
const first = events[0].year;
const span = events[events.length - 1].year - first;
const low = wide ? blockWidth / 2 : blockHeight / 2;
const high = wide ? width - blockWidth / 2 : height - blockHeight / 2;
let previous = -Infinity;
const along = events.map((spec) => {
  previous = Math.max(
    previous + (wide ? 0 : blockHeight + 20),
    low + ((spec.year - first) / span) * (high - low),
  );
  return previous;
});
const make = (tag, className) => {
  const element = document.createElement(tag);
  element.className = className;
  return element;
};
const axis = make("div", "axis");
const rail = make("div", wide ? "rail rail-wide" : "rail rail-tall");
ctx.root.append(axis);
axis.append(rail);
if (wide) {
  rail.style.left = `${low}px`;
  rail.style.width = `${high - low}px`;
  rail.style.top = `${height / 2}px`;
} else {
  rail.style.top = `${low}px`;
  rail.style.height = `${high - low}px`;
}
ctx.timeline.set(rail, wide ? { scaleX: 0 } : { scaleY: 0 }, 0);
const cues = events.map((spec) => Math.min(ctx.at(String(spec.year)), ctx.duration - 0.5));
events.forEach((spec, index) => {
  const [dot, block] = [make("div", "dot"), make("div", wide ? "block block-wide" : "block")];
  const [when, what] = [make("p", "when"), make("p", "what")];
  when.textContent = String(spec.year);
  what.textContent = spec.what;
  block.append(when, what);
  axis.append(dot, block);
  block.style.width = `${blockWidth}px`;
  block.style.height = `${blockHeight}px`;
  if (wide) {
    dot.style.left = `${along[index]}px`;
    dot.style.top = `${height / 2}px`;
    block.style.left = `${along[index] - blockWidth / 2}px`;
    block.style.top = `${index % 2 === 0 ? height / 2 - blockHeight - 40 : height / 2 + 40}px`;
  } else {
    dot.style.left = "14px";
    dot.style.top = `${along[index]}px`;
    block.style.left = "60px";
    block.style.top = `${along[index] - blockHeight / 2}px`;
  }
  ctx.timeline.from(dot, { scale: 0, duration: 0.4, ease: "back.out(2)" }, cues[index]);
  ctx.timeline.from(
    block,
    {
      opacity: 0,
      x: wide ? 0 : 24,
      y: wide ? (index % 2 === 0 ? 24 : -24) : 0,
      duration: 0.5,
      ease: "power3.out",
    },
    cues[index],
  );
  if (index > 0) {
    const travel = (along[index] - low) / (high - low);
    ctx.timeline.to(
      rail,
      wide
        ? { scaleX: travel, duration: cues[index] - cues[index - 1], ease: "none" }
        : { scaleY: travel, duration: cues[index] - cues[index - 1], ease: "none" },
      cues[index - 1],
    );
  }
});
```

```css
.mo-s-demo {
  display: flex;
  align-items: stretch;
}
.mo-s-demo .axis {
  position: relative;
  width: 100%;
  height: 100%;
}
.mo-s-demo .rail {
  position: absolute;
  background: var(--mo-accent);
}
.mo-s-demo .rail-wide {
  height: 4px;
  margin-top: -2px;
  transform-origin: 0 50%;
}
.mo-s-demo .rail-tall {
  left: 12px;
  width: 4px;
  transform-origin: 50% 0;
}
.mo-s-demo .dot {
  position: absolute;
  z-index: 1;
  width: 28px;
  height: 28px;
  margin: -14px 0 0 -14px;
  border: 4px solid var(--mo-accent);
  border-radius: 999px;
  background: var(--mo-bg);
}
.mo-s-demo .block {
  position: absolute;
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: flex-start;
  text-align: left;
}
.mo-s-demo .block-wide {
  align-items: center;
  text-align: center;
}
.mo-s-demo .when {
  margin: 0;
  font-family: var(--mo-font-mono);
  font-size: var(--mo-text-body);
  font-weight: 600;
  line-height: 1.3;
  color: var(--mo-accent);
}
.mo-s-demo .what {
  margin: 0;
  font-size: var(--mo-text-body);
  line-height: 1.25;
  color: var(--mo-text);
}
```
