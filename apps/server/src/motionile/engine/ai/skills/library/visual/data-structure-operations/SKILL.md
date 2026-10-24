---
name: data-structure-operations
description: Data structure operations animated step by step, arrays, lists, stacks, queues, trees and hash tables with cells, pointers and highlights that move as the narrator explains an operation. Use for push and pop, enqueue, insert, delete, search, binary search, swap, sorting passes, traversal, two pointers, sliding window, comparisons between elements, and "what happens to the array or stack when we do X" in algorithms and data structures lessons.
metadata:
  layer: visual
---

# Data structure operations

In the examples the scene root is `.mo-s-demo`; replace `demo` with the real scene id in the CSS. Build all cells as HTML in the builder with `createElement` and `textContent`; they exist from the first frame so layout never shifts.

## When to use

- One operation on a small structure: 3 to 8 cells, at most 7 in landscape and 5 in portrait for cells showing 2-digit values.
- The narration names each state change ("compare", "swap", "push", "pop", "keep the right half"), so every change has a word to tie to.
- For many items or large data use `data-chart-story`; for code that performs the operation use `code-walkthrough`.

## Structure

1. Beat 1: the structure appears (cells stagger in, 0.12 s apart, 0.4 s each) on the word that introduces it.
2. One beat per operation step, always in this order: focus (ring or pointer moves, a note names what is compared), action (cell moves, appears, leaves or dims), result (note updates).
3. Final beat: mark the answer (ring on the found cell, sorted cells at full opacity) on the word that states it.
4. Hold. A step lasts at least 0.5 s and starts on its word, clamped with `Math.min(time, ctx.duration - 1)`.

## Do

- Cells are mono (`--mo-font-mono`), `--mo-text-title` (or `--mo-text-subtitle` when 6 or more), `--mo-surface` fill, 2 px `--mo-border`, radius `calc(var(--mo-unit) * 1.6)`. Cap the row width at 880 px so cells stay square.
- Measure with `getBoundingClientRect` after the DOM is built and before any tween (tweens move elements), then drive everything with absolute `x` and `y` values relative to the container.
- The focus ring or pointer is one element that moves; the accent color is used only for it and for the final answer.
- Discarded or finished cells dim to opacity 0.55 (a stated state, not decoration); do not remove them.
- Swap by moving both cells to each other's absolute offset over 0.5 s with a 36 px lift on one, so they do not pass through each other.
- A one-line note under the structure states the current comparison in symbols ("5 > 2: swap"); one note visible at a time, stacked in one cell and cross-faded.
- Vertical structures (stack, queue) stay vertical in every aspect; horizontal ones (arrays) stay in one row with at most the cell counts above.

## Don't

- Do not animate more than one change per spoken phrase, and do not move cells before the word that names the move.
- Do not use `DrawSVGPlugin`; draw pointers and arrows with CSS triangles or elements, or SVG with `strokeDashoffset`.
- Do not put index labels below cells unless the narration uses indexes; they compete with the notes.
- Do not use random values; pick small, memorable numbers with a clear story (5, 2, 4, 1).
- Do not animate layout properties (`width`, `top`) of cells; use `x`, `y`, `opacity`.

## runtime@1 patterns

Absolute-offset swap: `to(a, { x: ax, duration: 0.5, ease: "power2.inOut" }, t)`, `to(b, { x: bx, ... }, t)`, and `to(a, { y: -36, duration: 0.25 }, t)` then `to(a, { y: 0, duration: 0.25 }, t + 0.25)`. Track each cell's cumulative offset yourself.

Moving ring: `gsap.set(ring, { x, y, width, height, opacity: 0 })` from measured rects, then `to(ring, { x, duration: 0.4, ease: "power2.inOut" }, t)`.

Element enters or leaves a stack: `from(slot, { opacity: 0, y: -160 })` to push, `to(slot, { opacity: 0, y: -160 })` to pop; a pointer follows the top by tweening `y` to the measured center of the top slot.

## Examples

#### Example: Bubble sort swaps

Narration: "Bubble sort compares neighbours. Five is bigger than two, so they swap. Then five meets four, and swaps again."

```js
const wrap = document.createElement("div");
wrap.className = "mo-stack wrap";
const cells = document.createElement("div");
cells.className = "cells";
const boxes = [5, 2, 4, 1].map((value) => {
  const box = document.createElement("div");
  box.className = "box";
  box.textContent = String(value);
  cells.append(box);
  return box;
});
const ring = document.createElement("div");
ring.className = "ring";
cells.append(ring);
const area = document.createElement("div");
area.className = "notes";
const notes = ["5 > 2: swap", "5 > 4: swap"].map((text) => {
  const note = document.createElement("p");
  note.className = "note";
  note.textContent = text;
  area.append(note);
  return note;
});
wrap.append(cells, area);
ctx.root.append(wrap);
const origin = cells.getBoundingClientRect();
const rects = boxes.map((box) => box.getBoundingClientRect());
const pitch = rects[1].left - rects[0].left;
const pair = (i) => ({
  x: rects[i].left - origin.left - 12,
  y: rects[i].top - origin.top - 12,
  width: rects[i + 1].right - rects[i].left + 24,
  height: rects[i].height + 24,
});
const at = (cue) => Math.min(ctx.at(cue), ctx.duration - 1);
const swap = (a, b, ax, bx, time) => {
  ctx.timeline.to(a, { x: ax, duration: 0.5, ease: "power2.inOut" }, time);
  ctx.timeline.to(b, { x: bx, duration: 0.5, ease: "power2.inOut" }, time);
  ctx.timeline.to(a, { y: -36, duration: 0.25, ease: "power1.out" }, time);
  ctx.timeline.to(a, { y: 0, duration: 0.25, ease: "power1.in" }, time + 0.25);
};
gsap.set(ring, { ...pair(0), opacity: 0 });
gsap.set(notes, { opacity: 0 });
ctx.timeline.from(
  boxes,
  { opacity: 0, y: 40, duration: 0.4, stagger: 0.12, ease: "power3.out" },
  0,
);
ctx.timeline.to(ring, { opacity: 1, duration: 0.3 }, at("compares"));
ctx.timeline.to(notes[0], { opacity: 1, duration: 0.3 }, at("bigger"));
swap(boxes[0], boxes[1], pitch, -pitch, at("swap"));
ctx.timeline.to(notes[0], { opacity: 0, duration: 0.25 }, at("meets") - 0.1);
ctx.timeline.to(ring, { x: pair(1).x, duration: 0.4, ease: "power2.inOut" }, at("meets"));
ctx.timeline.to(notes[1], { opacity: 1, duration: 0.3 }, at("meets") + 0.2);
swap(boxes[0], boxes[2], pitch * 2, -pitch, at("swaps"));
```

```css
.mo-s-demo {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.mo-s-demo .wrap {
  width: 100%;
  align-items: center;
}
.mo-s-demo .cells {
  position: relative;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: calc(var(--mo-unit) * 2);
  width: min(100%, 880px);
}
.mo-s-demo .box {
  display: flex;
  aspect-ratio: 1;
  align-items: center;
  justify-content: center;
  border: 2px solid var(--mo-border);
  border-radius: calc(var(--mo-unit) * 1.6);
  background: var(--mo-surface);
  font-family: var(--mo-font-mono);
  font-size: var(--mo-text-title);
  font-weight: 700;
}
.mo-s-demo .ring {
  position: absolute;
  left: 0;
  top: 0;
  border: 4px solid var(--mo-accent);
  border-radius: calc(var(--mo-unit) * 2);
  pointer-events: none;
}
.mo-s-demo .notes {
  position: relative;
  width: 100%;
  min-height: calc(var(--mo-text-subtitle) * 1.6);
}
.mo-s-demo .note {
  position: absolute;
  inset: 0;
  margin: 0;
  text-align: center;
  font-family: var(--mo-font-mono);
  font-size: var(--mo-text-subtitle);
  font-weight: 600;
}
```

#### Example: Stack push and pop

Narration: "A stack is last in, first out. Push one, push two, push three. Pop removes three, the top."

```js
const wrap = document.createElement("div");
wrap.className = "mo-stack wrap";
const well = document.createElement("div");
well.className = "well";
const slots = ["1", "2", "3"].map((value) => {
  const slot = document.createElement("div");
  slot.className = "slot";
  slot.textContent = value;
  well.append(slot);
  return slot;
});
const pointer = document.createElement("div");
pointer.className = "pointer";
const arrow = document.createElement("span");
arrow.className = "arrow";
const tag = document.createElement("span");
tag.textContent = "top";
pointer.append(arrow, tag);
well.append(pointer);
const label = document.createElement("p");
label.className = "mo-caption";
label.textContent = "Stack";
const popped = document.createElement("p");
popped.className = "popped";
popped.textContent = "popped 3";
wrap.append(well, label, popped);
ctx.root.append(wrap);
const origin = well.getBoundingClientRect();
const centers = slots.map((slot) => {
  const box = slot.getBoundingClientRect();
  return box.top - origin.top + box.height / 2 - pointer.offsetHeight / 2;
});
const at = (cue, occurrence) => Math.min(ctx.at(cue, occurrence), ctx.duration - 1);
gsap.set(pointer, { y: centers[0], opacity: 0 });
gsap.set(popped, { opacity: 0 });
["one", "two", "three"].forEach((cue, index) => {
  const time = at(cue);
  ctx.timeline.from(slots[index], { opacity: 0, y: -160, duration: 0.5, ease: "power2.out" }, time);
  if (index === 0) {
    ctx.timeline.to(pointer, { opacity: 1, duration: 0.3 }, time);
  } else {
    ctx.timeline.to(pointer, { y: centers[index], duration: 0.4, ease: "power2.inOut" }, time);
  }
});
const pop = at("pop");
ctx.timeline.to(slots[2], { opacity: 0, y: -160, duration: 0.5, ease: "power2.in" }, pop);
ctx.timeline.to(pointer, { y: centers[1], duration: 0.4, ease: "power2.inOut" }, pop + 0.3);
ctx.timeline.to(popped, { opacity: 1, duration: 0.3 }, pop + 0.4);
```

```css
.mo-s-demo {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.mo-s-demo .wrap {
  align-items: center;
}
.mo-s-demo .well {
  position: relative;
  display: flex;
  flex-direction: column-reverse;
  gap: calc(var(--mo-unit) * 1.4);
  padding: calc(var(--mo-unit) * 1.4);
  border: 4px solid var(--mo-border);
  border-top: 0;
  border-radius: 0 0 calc(var(--mo-unit) * 2) calc(var(--mo-unit) * 2);
}
.mo-s-demo .slot {
  display: flex;
  align-items: center;
  justify-content: center;
  width: calc(var(--mo-unit) * 38);
  height: calc(var(--mo-unit) * 12);
  line-height: 1;
  border-radius: calc(var(--mo-unit) * 1.4);
  background: var(--mo-surface);
  border: 2px solid var(--mo-border);
  font-family: var(--mo-font-mono);
  font-size: var(--mo-text-title);
  font-weight: 700;
}
.mo-s-demo .pointer {
  position: absolute;
  left: 100%;
  top: 0;
  display: flex;
  align-items: center;
  gap: calc(var(--mo-unit) * 1.2);
  margin-left: calc(var(--mo-unit) * 2);
  font-size: var(--mo-text-body);
  font-weight: 700;
  color: var(--mo-accent);
}
.mo-s-demo .arrow {
  width: 0;
  height: 0;
  border-top: calc(var(--mo-unit) * 1.2) solid transparent;
  border-bottom: calc(var(--mo-unit) * 1.2) solid transparent;
  border-right: calc(var(--mo-unit) * 1.8) solid var(--mo-accent);
}
.mo-s-demo .popped {
  margin: 0;
  font-family: var(--mo-font-mono);
  font-size: var(--mo-text-subtitle);
  font-weight: 600;
  color: var(--mo-success);
}
```
