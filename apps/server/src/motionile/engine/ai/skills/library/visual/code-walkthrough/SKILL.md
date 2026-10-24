---
name: code-walkthrough
description: Code walkthrough, a short snippet on screen with a highlight bar that moves line by line as the narrator explains it, optional output and variable-state panels that update on cue. Use for explaining source code, functions, loops, algorithms in code, API calls, SQL queries, shell commands, config files, regex, how a line or statement executes, what a variable holds after each step, and "walk me through this code" requests in any programming language.
metadata:
  layer: visual
---

# Code walkthrough

In the examples the scene root is `.mo-s-demo`; replace `demo` with the real scene id in the CSS. The builder creates the DOM with `createElement`; code text is set only through `textContent`.

## When to use

- The narration explains what specific lines do, in order, or what a variable holds after each step (trace panel).
- Not for architecture or flows (use the diagram skills) or long listings: show the 3 to 8 lines that matter, never a whole file.

## Structure

1. Beat 1: the editor panel fades in and rises 40 px (0.5 s). No highlight yet.
2. One beat per line or block: on the word naming it, the highlight bar slides to that line (0.4 s, `power2.inOut`), the line goes to full opacity and the previous one dims to 0.7. The first cue only fades the bar in.
3. Final beat: an output row, or the state panel values, appear on the word that states the result.
4. Hold. Every cue is clamped with `Math.min(time, ctx.duration - 0.7)`.

## Do

- Use `.mo-code` for the panel, `--mo-font-mono` and `--mo-text-code`. At most 8 lines and 36 characters per line (portrait is the narrowest); break long lines or simplify the code.
- Build each line as a row of token spans. Color sparingly with tokens only: keywords `--mo-text-secondary`, strings `--mo-success`, numbers and function names `--mo-accent`, everything else `--mo-text`. Line numbers in `--mo-text-secondary`.
- Measure line boxes with `getBoundingClientRect` after building the DOM and before creating any tween, because `from` tweens move the elements. Store `top` relative to the body and `height`.
- Highlight a block by tweening the bar to the first line's top and the combined height.
- For a trace panel use `.mo-split` (columns in landscape, stacked in portrait and square): code first, state card second. Show the variable's value as stacked spans in one grid cell that cross-fade on the cue words.
- Dim lines to opacity 0.7, never lower; dimmed code must keep contrast 4.5:1.
- Show output literally, in mono.

## Don't

- Do not type code out character by character; the line appears whole and the highlight explains it.
- Do not scroll, pan or use `position: fixed`.
- Do not use a syntax highlighter library or `innerHTML`.
- Do not show code the narration does not discuss, and do not highlight a line before its word is spoken.
- Do not use tabs; indent with two spaces.

## runtime@1 patterns

Moving bar: `gsap.set(bar, { y, height, opacity: 0 })` once, then `to(bar, { y, height, duration: 0.4 }, time)` per cue.

Value cross-fade: for spans stacked in one grid cell, `from(span, { opacity: 0, y: 16 })` on its cue and `to(previous, { opacity: 0, y: -16 })` on the same cue.

## Examples

#### Example: Three lines of Python

Narration: "First we make a list of names. Then a comprehension upper-cases each one. Finally we print the new list."

```js
const source = [
  [
    ["names = [", ""],
    ['"Ada"', "str"],
    [", ", ""],
    ['"Linus"', "str"],
    ["]", ""],
  ],
  [
    ["upper = [n.", ""],
    ["upper", "fn"],
    ["() ", ""],
    ["for", "kw"],
    [" n ", ""],
    ["in", "kw"],
    [" names]", ""],
  ],
  [
    ["print", "fn"],
    ["(upper)", ""],
  ],
];
const cues = ["make", "comprehension", "print"].map((cue) =>
  Math.min(ctx.at(cue), ctx.duration - 0.7),
);
const editor = document.createElement("div");
editor.className = "mo-code editor";
const body = document.createElement("div");
body.className = "body";
const mark = document.createElement("div");
mark.className = "mark";
body.append(mark);
const lines = source.map((tokens, index) => {
  const row = document.createElement("div");
  row.className = "line";
  const number = document.createElement("span");
  number.className = "number";
  number.textContent = String(index + 1);
  row.append(number);
  tokens.forEach(([text, kind]) => {
    const span = document.createElement("span");
    span.className = kind;
    span.textContent = text;
    row.append(span);
  });
  body.append(row);
  return row;
});
const output = document.createElement("div");
output.className = "output";
output.textContent = "['ADA', 'LINUS']";
body.append(output);
editor.append(body);
ctx.root.append(editor);
const bodyTop = body.getBoundingClientRect().top;
const spots = lines.map((line) => {
  const box = line.getBoundingClientRect();
  return { top: box.top - bodyTop, height: box.height };
});
gsap.set(mark, { y: spots[0].top, height: spots[0].height, opacity: 0 });
gsap.set(lines, { opacity: 0.7 });
ctx.timeline.from(editor, { opacity: 0, y: 40, duration: 0.5, ease: "power3.out" }, 0);
cues.forEach((time, index) => {
  if (index === 0) {
    ctx.timeline.to(mark, { opacity: 1, duration: 0.3 }, time);
  } else {
    ctx.timeline.to(
      mark,
      { y: spots[index].top, height: spots[index].height, duration: 0.4, ease: "power2.inOut" },
      time,
    );
    ctx.timeline.to(lines[index - 1], { opacity: 0.7, duration: 0.3 }, time);
  }
  ctx.timeline.to(lines[index], { opacity: 1, duration: 0.3 }, time);
});
ctx.timeline.from(
  output,
  { opacity: 0, y: 12, duration: 0.4 },
  Math.min(cues[2] + 0.4, ctx.duration - 0.5),
);
```

```css
.mo-s-demo {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.mo-s-demo .editor {
  width: min(100%, 1100px);
  padding: 0;
  overflow: hidden;
}
.mo-s-demo .body {
  position: relative;
  padding: calc(var(--mo-unit) * 2.4) 0;
}
.mo-s-demo .mark {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  background: var(--mo-elevated);
  border-left: calc(var(--mo-unit) * 0.6) solid var(--mo-accent);
}
.mo-s-demo .line {
  position: relative;
  padding: 0 calc(var(--mo-unit) * 3);
  line-height: 1.7;
}
.mo-s-demo .number {
  display: inline-block;
  width: 2ch;
  margin-right: 2ch;
  text-align: right;
  color: var(--mo-text-secondary);
}
.mo-s-demo .kw {
  color: var(--mo-text-secondary);
  font-weight: 700;
}
.mo-s-demo .str {
  color: var(--mo-success);
}
.mo-s-demo .fn {
  color: var(--mo-accent);
}
.mo-s-demo .output {
  margin-top: calc(var(--mo-unit) * 1.6);
  padding: calc(var(--mo-unit) * 1.6) calc(var(--mo-unit) * 3) 0;
  border-top: 2px solid var(--mo-border);
  color: var(--mo-success);
}
```

#### Example: Tracing a loop with its state

Narration: "The loop adds each price to total. First total becomes four, then nine, and finally twelve."

```js
const source = [
  [
    ["let", "kw"],
    [" total = ", ""],
    ["0", "num"],
    [";", ""],
  ],
  [
    ["for", "kw"],
    [" (", ""],
    ["const", "kw"],
    [" p ", ""],
    ["of", "kw"],
    [" [", ""],
    ["4", "num"],
    [", ", ""],
    ["5", "num"],
    [", ", ""],
    ["3", "num"],
    ["]) {", ""],
  ],
  [["  total += p;", ""]],
  [["}", ""]],
];
const steps = [
  { line: 1, cue: "loop" },
  { line: 2, cue: "adds" },
];
const split = document.createElement("div");
split.className = "mo-split split";
const editor = document.createElement("div");
editor.className = "mo-code editor";
const body = document.createElement("div");
body.className = "body";
const mark = document.createElement("div");
mark.className = "mark";
body.append(mark);
const lines = source.map((tokens) => {
  const row = document.createElement("div");
  row.className = "line";
  tokens.forEach(([text, kind]) => {
    const span = document.createElement("span");
    span.className = kind;
    span.textContent = text;
    row.append(span);
  });
  body.append(row);
  return row;
});
const card = document.createElement("div");
card.className = "mo-card state";
const swaps = [];
[
  ["p", ["-", "4", "5", "3"]],
  ["total", ["0", "4", "9", "12"]],
].forEach(([name, values]) => {
  const row = document.createElement("div");
  row.className = "row";
  const label = document.createElement("span");
  label.className = "name";
  label.textContent = name;
  const cell = document.createElement("div");
  cell.className = "cell";
  row.append(label, cell);
  card.append(row);
  swaps.push(
    values.map((value) => {
      const span = document.createElement("span");
      span.className = "value";
      span.textContent = value;
      cell.append(span);
      return span;
    }),
  );
});
editor.append(body);
split.append(editor, card);
ctx.root.append(split);
const bodyTop = body.getBoundingClientRect().top;
const spots = lines.map((line) => {
  const box = line.getBoundingClientRect();
  return { top: box.top - bodyTop, height: box.height };
});
gsap.set(mark, { y: spots[steps[0].line].top, height: spots[steps[0].line].height, opacity: 0 });
gsap.set(lines, { opacity: 0.7 });
ctx.timeline.from(split, { opacity: 0, y: 40, duration: 0.5, ease: "power3.out" }, 0);
steps.forEach((step, index) => {
  const time = Math.min(ctx.at(step.cue), ctx.duration - 0.7);
  const spot = spots[step.line];
  if (index === 0) {
    ctx.timeline.to(mark, { opacity: 1, duration: 0.3 }, time);
  } else {
    ctx.timeline.to(
      mark,
      { y: spot.top, height: spot.height, duration: 0.4, ease: "power2.inOut" },
      time,
    );
    ctx.timeline.to(lines[steps[index - 1].line], { opacity: 0.7, duration: 0.3 }, time);
  }
  ctx.timeline.to(lines[step.line], { opacity: 1, duration: 0.3 }, time);
});
const times = [
  0,
  ...["four", "nine", "twelve"].map((cue) => Math.min(ctx.at(cue), ctx.duration - 0.6)),
];
swaps.forEach((spans) => {
  spans.forEach((span, index) => {
    if (index > 0) {
      ctx.timeline.from(span, { opacity: 0, y: 16, duration: 0.3 }, times[index]);
    }
    if (index < spans.length - 1) {
      ctx.timeline.to(span, { opacity: 0, y: -16, duration: 0.3 }, times[index + 1]);
    }
  });
});
```

```css
.mo-s-demo {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.mo-s-demo .split {
  align-items: center;
}
.mo-s-demo .editor {
  padding: 0;
  overflow: hidden;
}
.mo-s-demo .body {
  position: relative;
  padding: calc(var(--mo-unit) * 2.4) 0;
}
.mo-s-demo .mark {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  background: var(--mo-elevated);
  border-left: calc(var(--mo-unit) * 0.6) solid var(--mo-accent);
}
.mo-s-demo .line {
  position: relative;
  padding: 0 calc(var(--mo-unit) * 3);
  line-height: 1.7;
}
.mo-s-demo .kw {
  color: var(--mo-text-secondary);
  font-weight: 700;
}
.mo-s-demo .num {
  color: var(--mo-accent);
}
.mo-s-demo .state {
  display: flex;
  flex-direction: column;
  gap: calc(var(--mo-unit) * 2);
}
.mo-s-demo .row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: calc(var(--mo-unit) * 3);
}
.mo-s-demo .name {
  font-family: var(--mo-font-mono);
  font-size: var(--mo-text-subtitle);
  color: var(--mo-text-secondary);
}
.mo-s-demo .cell {
  display: grid;
  justify-items: end;
}
.mo-s-demo .value {
  grid-area: 1 / 1;
  font-family: var(--mo-font-mono);
  font-size: var(--mo-text-title);
  font-weight: 700;
  line-height: 1.2;
}
```
