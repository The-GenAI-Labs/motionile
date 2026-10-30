---
name: kinetic-typography
description: Kinetic typography, words and short phrases that appear on screen exactly when the narrator says them, with the key term emphasised. Use for hooks, openers, closers, definitions, quotes, one-sentence takeaways, rules of thumb, punchlines, a big number or claim stated in words, and any scene where the narration itself is the visual and no diagram, chart or code is needed. Also the right look for abstract statements that have nothing to draw.
metadata:
  layer: visual
---

# Kinetic typography

In the examples the scene root is `.mo-s-demo`; replace `demo` with the real scene id in the CSS. The root is the safe area (the scene has padding), so make it a flex column to center content.

## When to use

- A hook, a transition, a definition, a quote, a takeaway or a punchline: the sentence is the point.
- A claim with one or two decisive words (a number, a contrast, a term being defined).
- Never as the only visual for a mechanism, a sequence or data: those need a diagram, a chart or code. Use it for at most one in three scenes.

## Structure

1. One idea per scene, at most 12 words on screen at once. A scene whose narration is longer than 12 words is shown in chunks, one sentence or clause per chunk, each replacing the last.
2. Beat 1: every word enters on its own `ctx.at(index)`, so the picture follows the voice. Words are not early and never wait for a later word.
3. Beat 2: the one or two key words (numbers, the term being defined, the contrast) get a heavier entrance: larger offset, scale from 1.25, `back.out`, and a stronger final colour and weight. Emphasis is rare; if everything is emphasised nothing is.
4. Beat 3 (optional): one accent element after the last word, such as an underline rule that scales in on `ctx.end(lastWord)`.
5. Hold the final state until the scene ends. Clamp every start with `Math.min(time, ctx.duration - 0.6)` so a late word never overflows the scene.

## Do

- Size from tokens: `--mo-text-title` for ordinary lines, up to `calc(var(--mo-text-title) * 1.2)` for a single short hook, `--mo-text-display` only for one to three words.
- Style words as `display: inline-block` spans with a small `margin-inline` so transforms work and wrapping stays natural; add `text-wrap: balance`.
- Use `--mo-text-secondary` for ordinary words and `--mo-text` or `--mo-accent` plus `font-weight: 800` for key words, so emphasis does not rely on colour alone.
- Make words rise with `y: 44` and `power3.out`, 0.3 to 0.4 s. Keep the motion identical for all ordinary words.
- Centre everything. In portrait the same line simply wraps to more lines; do not change the design per aspect.
- Give numbers a count-up when the narration states a quantity (pattern below), ending on the exact spoken value.

## Don't

- Do not put long narration verbatim on screen. Show the sentence's core words, or the full sentence only if it is under 12 words.
- Do not animate letters, rotate, bounce or shake text; it hurts legibility and wastes the beat.
- Do not use more than three font sizes in a scene, and nothing below `--mo-text-small`.
- Do not stack chunks in separate flow positions; overlay them in one grid cell and show one at a time.
- Do not start any tween before its word is spoken, and do not leave a chunk on screen after the next one starts.
- Do not use `TextPlugin` or `SplitText`; build spans yourself.

## runtime@1 patterns

Count-up for a spoken quantity. The callback only writes a pure function of the tween value, so seeking is safe:

```js
const counter = { value: 0 };
ctx.timeline.to(
  counter,
  {
    value: 90,
    duration: 1.2,
    ease: "power2.out",
    onUpdate: () => {
      number.textContent = String(Math.round(counter.value));
    },
  },
  ctx.at("ninety"),
);
```

Chunks overlaid in one grid cell (`display: grid` on the wrapper, `grid-area: 1 / 1` on each chunk), as in Example 2. A chunk exits by tweening its word nodes to `opacity: 0, y: -30`; the next chunk starts no earlier than that exit ends.

Entrance lookup by word index (not text) when the narration may repeat words: `ctx.at(index)` and `ctx.end(index)`.

## Examples

#### Example: One sentence with emphasis

Narration: "Every great video begins with a single question."

```js
const line = document.createElement("p");
line.className = "line";
ctx.root.append(line);
const keys = ["great", "question"];
const nodes = ctx.words.map((word) => {
  const key = keys.indexOf(word.text.toLowerCase().replace(/[^a-z]/g, "")) >= 0;
  const node = document.createElement("span");
  node.className = key ? "word key" : "word";
  node.textContent = word.text;
  line.append(node);
  return node;
});
nodes.forEach((node, index) => {
  const key = node.classList.contains("key");
  ctx.timeline.from(
    node,
    {
      opacity: 0,
      y: key ? 72 : 44,
      scale: key ? 1.25 : 1,
      duration: key ? 0.5 : 0.35,
      ease: key ? "back.out(1.8)" : "power3.out",
    },
    Math.min(ctx.at(index), ctx.duration - 0.6),
  );
});
const rule = document.createElement("div");
rule.className = "rule";
ctx.root.append(rule);
ctx.timeline.from(
  rule,
  { scaleX: 0, duration: 0.6, ease: "power2.inOut" },
  Math.min(ctx.end(ctx.words.length - 1), ctx.duration - 0.7),
);
```

```css
.mo-s-demo {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}
.mo-s-demo .line {
  margin: 0;
  max-width: 100%;
  font-size: calc(var(--mo-text-title) * 1.2);
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: -0.03em;
  color: var(--mo-text-secondary);
  text-wrap: balance;
}
.mo-s-demo .word {
  display: inline-block;
  margin-inline: 0.14em;
}
.mo-s-demo .key {
  color: var(--mo-accent);
  font-weight: 800;
}
.mo-s-demo .rule {
  width: calc(var(--mo-unit) * 18);
  height: calc(var(--mo-unit) * 0.9);
  margin-top: calc(var(--mo-unit) * 4);
  border-radius: 999px;
  background: var(--mo-accent);
  transform-origin: left center;
}
```

#### Example: Two sentences as chunks

Narration: "Most explainers fail in the first five seconds. Lead with the answer, then earn the detail."

```js
const stage = document.createElement("div");
stage.className = "chunks";
ctx.root.append(stage);
const chunks = [];
let current = [];
ctx.words.forEach((word) => {
  current.push(word);
  if (/[.!?]$/.test(word.text)) {
    chunks.push(current);
    current = [];
  }
});
if (current.length > 0) {
  chunks.push(current);
}
const keys = ["five", "seconds", "answer"];
let clear = 0;
chunks.forEach((chunk, chunkIndex) => {
  const line = document.createElement("p");
  line.className = "line";
  stage.append(line);
  const nodes = chunk.map((word) => {
    const key = keys.indexOf(word.text.toLowerCase().replace(/[^a-z]/g, "")) >= 0;
    const node = document.createElement("span");
    node.className = key ? "word key" : "word";
    node.textContent = word.text;
    line.append(node);
    ctx.timeline.from(
      node,
      {
        opacity: 0,
        y: key ? 72 : 44,
        duration: key ? 0.5 : 0.35,
        ease: key ? "back.out(1.8)" : "power3.out",
      },
      Math.min(Math.max(word.start, clear), ctx.duration - 0.6),
    );
    return node;
  });
  if (chunkIndex < chunks.length - 1) {
    const exit = chunk[chunk.length - 1].end;
    ctx.timeline.to(nodes, { opacity: 0, y: -30, duration: 0.25, ease: "power2.in" }, exit);
    clear = exit + 0.25;
  }
});
```

```css
.mo-s-demo {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
}
.mo-s-demo .chunks {
  display: grid;
  width: 100%;
  place-items: center;
}
.mo-s-demo .line {
  grid-area: 1 / 1;
  margin: 0;
  max-width: 100%;
  font-size: calc(var(--mo-text-title) * 1.1);
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.02em;
  color: var(--mo-text-secondary);
  text-wrap: balance;
}
.mo-s-demo .word {
  display: inline-block;
  margin-inline: 0.14em;
}
.mo-s-demo .key {
  color: var(--mo-accent);
  font-weight: 800;
}
```
