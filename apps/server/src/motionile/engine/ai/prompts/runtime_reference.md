## runtime@1 reference

A scene module is one piece of a larger HTML composition. You write the body of `build(ctx)` for one scene, the scene's CSS and optional SVG assets. A composer assembles every scene into one document and calls `Motionile.composition({ aspects, scenes })`. The same composition is rendered once per requested aspect by loading the page with a different viewport, frame by frame, in a network-isolated browser.

### What the composer gives you

- The scene element is `<section class="mo-scene mo-s-SCENEID" data-scene="SCENEID">` and it is available as `ctx.root`. `SCENEID` is the scene id you are given.
- `.mo-scene` is absolutely positioned over the whole stage, starts hidden, and is shown only during the scene's time range. Its padding equals the safe area, so children laid out in normal flow stay inside the safe area. The root has no `display` of its own: set it in your CSS (for example `display: flex`).
- Each asset you declare is placed inside the root as `<div data-asset="ASSETID">` holding your SVG. Find it with `ctx.root.querySelector('[data-asset="ASSETID"]')`.
- Everything else is created by your builder with `document.createElement`, `document.createElementNS` and `document.createTextNode`, and appended under `ctx.root`.
- Fonts: Geist (UI), Geist Mono (code), Noto Sans, and Noto Sans Devanagari for Hindi. Latin and Devanagari glyphs only. Arrows, box drawing and other symbols are not in the fonts: draw them with SVG or CSS.
- GSAP core is loaded as `gsap`. Do not rely on any GSAP plugin; use core tweens only.

### The scene context

All times are seconds relative to the scene start.

| Member                | Meaning                                                                                                                                                                                                                                          |
| --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `ctx.id`, `ctx.index` | Scene id and zero-based position                                                                                                                                                                                                                 |
| `ctx.root`            | The scene element                                                                                                                                                                                                                                |
| `ctx.duration`        | Scene length in seconds, including trailing padding                                                                                                                                                                                              |
| `ctx.text`            | The scene narration text                                                                                                                                                                                                                         |
| `ctx.words`           | Array of `{ index, text, start, end }` in seconds                                                                                                                                                                                                |
| `ctx.at(target)`      | Start time of a word. `target` is a word index or a string matched case-insensitively against word text without edge punctuation (first match; `ctx.at("word", 2)` is the third match). It throws when nothing matches and the render then fails |
| `ctx.end(target)`     | End time of a word, same lookup                                                                                                                                                                                                                  |
| `ctx.aspect`          | `"16:9"`, `"9:16"` or `"1:1"`                                                                                                                                                                                                                    |
| `ctx.stage`           | `{ width, height }` in pixels: 1920x1080, 1080x1920 or 1080x1080                                                                                                                                                                                 |
| `ctx.safeArea`        | `{ x, y, width, height }` in pixels inside the stage                                                                                                                                                                                             |
| `ctx.timeline`        | The scene's GSAP timeline, time zero at the scene start. Add every tween to it                                                                                                                                                                   |

The builder runs once per page load and the page is loaded once per aspect, so a builder may branch on `ctx.aspect`. The builder is synchronous.

### Tokens

CSS variables from `base.css`. Use them for every color, size and spacing. Never write raw colors for text on the stage: the style skill overrides these variables.

Colors: `--mo-bg`, `--mo-surface`, `--mo-elevated`, `--mo-border`, `--mo-text-muted`, `--mo-text-secondary`, `--mo-text`, `--mo-accent`, `--mo-danger`, `--mo-success`. Fonts: `--mo-font`, `--mo-font-mono`. Spacing: `--mo-unit` (1% of the shorter side, 10.8px), for example `calc(var(--mo-unit) * 3)`.

Type scale in pixels:

| Token                | 16:9 | 9:16 | 1:1 |
| -------------------- | ---- | ---- | --- |
| `--mo-text-small`    | 28   | 34   | 30  |
| `--mo-text-body`     | 36   | 44   | 40  |
| `--mo-text-subtitle` | 48   | 60   | 54  |
| `--mo-text-title`    | 72   | 88   | 80  |
| `--mo-text-display`  | 120  | 140  | 128 |
| `--mo-text-code`     | 30   | 34   | 32  |

Rendered text smaller than `--mo-text-small` fails validation.

Safe areas in pixels (the bottom inset is reserved for burned-in subtitles):

| Aspect | Viewport    | Left and right | Top | Bottom |
| ------ | ----------- | -------------- | --- | ------ |
| 16:9   | 1920 x 1080 | 96             | 64  | 160    |
| 9:16   | 1080 x 1920 | 72             | 160 | 420    |
| 1:1    | 1080 x 1080 | 72             | 72  | 200    |

Exposed as `--mo-safe-left`, `--mo-safe-right`, `--mo-safe-top`, `--mo-safe-bottom`. Usable content box: 1728x856 (16:9), 936x1340 (9:16), 936x808 (1:1).

### Layout primitives

`.mo-stage` is a size container named `stage`: use `@container stage (aspect-ratio <= 1)` for portrait and square layouts and `@container stage (aspect-ratio < 1)` for portrait only. Classes you may put on elements you create: `.mo-center` (centered column), `.mo-stack` (vertical flex with gap), `.mo-row` (horizontal flex with gap), `.mo-split` (two columns in landscape, one column in portrait and square), `.mo-card` (surface box with border and padding), `.mo-code` (monospace block, `white-space: pre`), `.mo-title`, `.mo-body`, `.mo-caption`, `.mo-muted`, `.mo-accent`, `.mo-safe` (absolute box inside the safe area).

### Rules every composition follows

1. Time is a function of the timeline only. Animate with GSAP tweens on `ctx.timeline` and position them in seconds, usually with `ctx.at(...)`. Do not use CSS animations, transitions, `requestAnimationFrame`, timers or callbacks that start animations.
2. Every tween on the scene timeline must end before `ctx.duration`. Leave the final state on screen until the scene ends: do not fade everything out at the end.
3. Visible text stays inside its element box and inside the safe area, never overlaps other text, is at least `--mo-text-small`, meets WCAG AA contrast and stays on screen. Layout is checked on the settled state at the start (50 ms in), middle and end (50 ms before the end) of the scene, in every aspect.
4. No network access of any kind. Images only as inline SVG assets or `data:` URIs. No external fonts, scripts, stylesheets or URLs.
5. Nothing visible may depend on `Date`, `performance.now` or random numbers.
6. Scenes are stacked and shown one at a time: never depend on the DOM order of scenes and never touch another scene's elements.

### Static checks on your module

The module is checked before composition. Each failure comes back to you as an issue code.

Builder (`builder_syntax`, `builder_identifier`, `builder_forbidden_syntax`):

- It must parse as the body of a synchronous function with the single parameter `ctx`. No wrapper function around the whole body is needed and `this`, `await`, `async`, `yield`, `with`, `import` and `export` are forbidden.
- It may reference only `ctx`, `gsap`, `Math`, `Array`, `Object`, `Number`, `String`, `Boolean`, `JSON`, `Set`, `Map`, `Symbol`, `Infinity`, `NaN`, `undefined`, `parseInt`, `parseFloat`, `isNaN`, `isFinite`, `RegExp`, `Error`, `document` and names it declares itself. Anything else (`window`, `globalThis`, `console`, timers, `Date`, `performance`, `fetch`, storage, `location`, `navigator`, `eval`, `Function`) is rejected.
- `document` may only be used for `createElement`, `createElementNS`, `createTextNode`, `createDocumentFragment`, `querySelector`, `querySelectorAll` and `getElementById`.
- Forbidden properties: `innerHTML`, `outerHTML` and `srcdoc` assignments, `insertAdjacentHTML`, `constructor`, `__proto__`, `__defineGetter__`, `__defineSetter__`, `__lookupGetter__`, `__lookupSetter__`, `ownerDocument`, `defaultView`, `contentWindow`, `contentDocument`, `getRootNode`, `cookie`, `random`, `ticker`, `delayedCall`. Computed access with a variable key on `document`, `ctx`, `Math`, `Object`, `gsap`, `JSON`, `Array`, `Number`, `String`, `Boolean`, `Set`, `Map` or `Symbol` is rejected: write `ctx.words`, not `ctx[name]`.
- Do not create `script`, `style`, `iframe`, `object`, `embed`, `link`, `meta`, `base`, `form`, `video`, `audio` or `foreignObject` elements, and do not set `on*` or `srcdoc` attributes. No HTML comment markers.

CSS (`css_syntax`, `css_unscoped`, `css_forbidden`):

- The first compound selector of every rule starts with `.mo-s-SCENEID`. Sibling combinators (`+`, `~`) are rejected. Inside `@media`, `@container`, `@supports` and `@layer` the same rule applies.
- Allowed at-rules: `@media`, `@container`, `@supports`, `@layer`, `@keyframes`. A keyframes name must start with `mo-s-SCENEID-`. No `@import`, `@font-face` or other at-rules.
- `url()` only with a `data:image/` URI or a `#fragment`. No `url()` built from `var()`, `attr()` or `env()`.
- `position: fixed` only on the scene root. No `!important` on the scene root.

Assets (`asset_invalid`):

- Each asset is one well-formed XML `<svg>` element (quoted attributes, closed tags) with an id matching `^[a-z][a-z0-9-]{0,31}$`.
- No `script`, `foreignObject`, `iframe`, `img`, `canvas`, `input`, `button`, `link`, `meta`, `form` or HTML elements inside. `href` and `xlink:href` only reference a `#fragment`. No `on*` attributes, no external URLs.

Size (`module_too_large`): builder at most 20,000 characters, CSS at most 20,000, each SVG at most 60,000, up to 8 assets, all together at most 120,000.

### Validation issue codes you may be shown

`text_overflow`, `safe_area_violation`, `text_overlap`, `font_too_small`, `contrast_low`, `element_offscreen`, `empty_scene`, `scene_overflow`, `non_deterministic_state`, `duration_mismatch`, `scene_boundary_mismatch`, `page_error`, `network_violation`, `timeout`, `forbidden_element`, `forbidden_attribute`, `forbidden_url`, `too_many_elements`, `invalid_data_uri`, `data_uris_too_large`, `html_too_large`, plus review issues from a visual check (legibility, layout, relevance, style, visual error).
