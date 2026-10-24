---
name: comparison-split
description: Side-by-side comparison of exactly two things on matching attributes - before and after, old way versus new way, myth versus fact, A versus B, pros and cons, trade-offs, monolith versus microservices, SQL versus NoSQL. Two cards reveal row by row as the narration names each point, side by side in landscape and stacked in portrait and square, with an optional verdict that spotlights the winner. Not for three or more options, rankings or step-by-step flows.
metadata:
  layer: visual
---

# Comparison split

In examples the scene root class is `.mo-s-demo`; replace `demo` with the real scene id.

## When to use

The narration contrasts two named things and walks through the same few attributes for both. One scene holds two panels and at most four matching rows each. Three or more options become a table or several scenes; a sequence of steps is a `flow-diagram`.

## Structure

1. Beat 0, within the first 0.3 s: nothing is empty. Show the scene heading if there is one, or the first panel.
2. Beat 1: the first panel enters when the narration names the first option.
3. Beats 2 to 4: each row appears on its keyword, in the same order on both sides, so the eye can compare row by row.
4. Beat 5: the second panel enters when the narration turns to the second option; its rows follow on their keywords.
5. Optional verdict beat on the closing words: dim the loser's body text to opacity 0.6 and fade in an accent outline on the winner. Never remove the loser.

Hold the final state for at least the last 0.6 s. One new idea per beat; a row never appears before its word is spoken.

## Do

- Give both panels the same structure: tag line, heading, rows. Same row count, same order of attributes, rows of at most five words.
- Use a data array of sides with `{ cue, rows: [[text, cue]] }` so cues sit next to the text they reveal.
- Mark the sides with more than colour: a different tag word ("Old way", "New way") and a different dot or border. Use `--mo-success` only for the side the narration endorses, `--mo-danger` for a myth or failure.
- Reveal with `from` tweens of 0.4 to 0.6 s; slide in sideways in landscape and from below in portrait and square.
- Clamp every start time with `Math.min(time, ctx.duration - length)` so no tween runs past the scene.
- Keep rows at `--mo-text-body` and headings at `--mo-text-subtitle`; use `--mo-text-small` only for tags.
- Put numbers that differ between sides in `--mo-font-mono` and align them.

## Don't

- Do not put more than four rows per side or sentences in rows; the narration carries the sentences.
- Do not write absolute widths or pixel font sizes; use `--mo-unit` multiples and the type tokens.
- Do not draw lines through text for strikethrough: the contrast check reads the pixels behind the text. Dim the card instead.
- Do not dim below opacity 0.6, and never dim text coloured with `--mo-danger`, `--mo-success` or `--mo-text-muted`; opacity multiplies away their contrast.
- Do not use `x: 60` slides in portrait: the card would leave the safe area while sliding in.

## runtime@1 patterns

Clamp a cue so the tween always finishes in the scene:

```js
const beat = (target, length) => Math.min(ctx.at(target), ctx.duration - length);
```

Aspect-aware entrance, sideways only when the panels are side by side:

```js
const side = ctx.aspect === "16:9" ? 60 : 0;
const lift = side === 0 ? 50 : 0;
ctx.timeline.from(
  card,
  { opacity: 0, x: index === 0 ? -side : side, y: lift, duration: 0.6, ease: "power3.out" },
  beat(cue, 0.6),
);
```

Spotlight without layout change: the winner owns a pre-built outline element, so its opacity is the only thing that tweens.

```js
ctx.timeline.to(loserText, { opacity: 0.6, duration: 0.5 }, beat("better", 0.5));
ctx.timeline.to(outline, { opacity: 1, duration: 0.5 }, beat("better", 0.5));
```

## Examples

#### Example: Manual editing versus narration first

Narration: "Editing by hand means timelines, keyframes and hours of work. Narration first means you write the idea, hear the voice and get the video."

```js
const sides = [
  {
    cue: "editing",
    tag: "The old way",
    title: "Editing by hand",
    rows: [
      ["Drag clips on timelines", "timelines"],
      ["Set keyframes one by one", "keyframes"],
      ["Spend hours on one minute", "hours"],
    ],
  },
  {
    cue: "narration",
    tag: "The new way",
    title: "Narration first",
    accent: true,
    rows: [
      ["Write the idea", "write"],
      ["Hear the voice", "hear"],
      ["Get the video", "get"],
    ],
  },
];
const beat = (target, length) => Math.min(ctx.at(target), ctx.duration - length);
const side = ctx.aspect === "16:9" ? 60 : 0;
const lift = side === 0 ? 50 : 0;
const split = document.createElement("div");
split.className = "mo-split";
ctx.root.append(split);
sides.forEach((spec, index) => {
  const card = document.createElement("div");
  card.className = spec.accent ? "mo-card panel panel-accent" : "mo-card panel";
  const tag = document.createElement("p");
  tag.className = "mo-caption tag";
  tag.textContent = spec.tag;
  const heading = document.createElement("h2");
  heading.className = "heading";
  heading.textContent = spec.title;
  const list = document.createElement("ul");
  list.className = "rows";
  card.append(tag, heading, list);
  split.append(card);
  ctx.timeline.from(
    card,
    { opacity: 0, x: index === 0 ? -side : side, y: lift, duration: 0.6, ease: "power3.out" },
    beat(spec.cue, 0.6),
  );
  spec.rows.forEach(([text, cue]) => {
    const row = document.createElement("li");
    row.className = "row";
    const dot = document.createElement("span");
    dot.className = "dot";
    row.append(dot, document.createTextNode(text));
    list.append(row);
    ctx.timeline.from(
      row,
      { opacity: 0, x: -24, duration: 0.4, ease: "power2.out" },
      beat(cue, 0.4),
    );
  });
});
```

```css
.mo-s-demo {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}
.mo-s-demo .panel {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: calc(var(--mo-unit) * 1.6);
  text-align: left;
}
.mo-s-demo .tag {
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.mo-s-demo .heading {
  margin: 0;
  font-size: var(--mo-text-subtitle);
  font-weight: 700;
  letter-spacing: -0.02em;
}
.mo-s-demo .rows {
  display: flex;
  flex-direction: column;
  gap: calc(var(--mo-unit) * 1.2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.mo-s-demo .row {
  display: flex;
  align-items: center;
  gap: calc(var(--mo-unit) * 1.6);
  font-size: var(--mo-text-body);
  line-height: 1.25;
  color: var(--mo-text-secondary);
}
.mo-s-demo .dot {
  flex: none;
  width: calc(var(--mo-unit) * 1.4);
  height: calc(var(--mo-unit) * 1.4);
  border-radius: 999px;
  background: var(--mo-text-muted);
}
.mo-s-demo .panel-accent {
  border-color: var(--mo-accent);
}
.mo-s-demo .panel-accent .dot {
  background: var(--mo-success);
}
```

#### Example: Myth versus fact with a verdict

Narration: "Many people believe lightning never strikes the same place twice. In fact, tall structures are hit again and again, sometimes many times each year."

```js
const beat = (target, length) => Math.min(ctx.at(target), ctx.duration - length);
const stacked = ctx.aspect !== "16:9";
const split = document.createElement("div");
split.className = "mo-split";
ctx.root.append(split);
const cards = [
  { kind: "myth", tag: "Myth", text: "Lightning never strikes twice", cue: "believe" },
  { kind: "fact", tag: "Fact", text: "Tall structures are hit again and again", cue: "fact" },
].map((spec) => {
  const card = document.createElement("div");
  card.className = `mo-card verdict verdict-${spec.kind}`;
  const tag = document.createElement("p");
  tag.className = "mo-caption tag";
  tag.textContent = spec.tag;
  const text = document.createElement("p");
  text.className = "claim";
  text.textContent = spec.text;
  const outline = document.createElement("div");
  outline.className = "outline";
  card.append(tag, text, outline);
  split.append(card);
  ctx.timeline.from(
    card,
    {
      opacity: 0,
      x: stacked ? 0 : spec.kind === "myth" ? -60 : 60,
      y: stacked ? 50 : 0,
      duration: 0.6,
      ease: "power3.out",
    },
    beat(spec.cue, 0.6),
  );
  return { text, outline };
});
const [myth, fact] = cards;
ctx.timeline.to(myth.text, { opacity: 0.6, duration: 0.5 }, beat("again", 0.5));
ctx.timeline.to(fact.outline, { opacity: 1, duration: 0.5 }, beat("again", 0.5));
```

```css
.mo-s-demo {
  display: flex;
  flex-direction: column;
  justify-content: center;
  align-items: center;
}
.mo-s-demo .verdict {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: calc(var(--mo-unit) * 1.6);
  text-align: left;
}
.mo-s-demo .tag {
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.mo-s-demo .verdict-myth .tag {
  color: var(--mo-danger);
}
.mo-s-demo .verdict-fact .tag {
  color: var(--mo-success);
}
.mo-s-demo .claim {
  margin: 0;
  font-size: var(--mo-text-subtitle);
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: -0.02em;
}
.mo-s-demo .outline {
  position: absolute;
  inset: -2px;
  border: 3px solid var(--mo-accent);
  border-radius: inherit;
  opacity: 0;
  pointer-events: none;
}
```
