# Render engine

This is the reference for the render pipeline: the composition contract and the `runtime@1` API that Phase 9's generator and the MCP clients write against, the determinism rules, the sanitizer, the sandbox and the validator with every error code, the pipeline and its stages, the storage layout, media delivery and the benchmark. Audio (providers, alignment, caching, mixing, loudness, subtitles) is in [`audio.md`](audio.md).

Decisions behind it: [ADR 0021](adr/0021-renders-as-an-aggregate.md) (renders), [0024](adr/0024-deterministic-capture-through-web-animations-and-frozen-clock.md) (determinism), [0025](adr/0025-narration-first-composition-contract.md) (contract), [0026](adr/0026-render-sandbox-design.md) (sandbox), [0028](adr/0028-media-delivery-and-microphone-policy.md) (delivery).

## 1. How a render works

```
composition HTML + narration (text per scene, or uploaded audio per scene) + options
  → prepare    fetch, sanitize, static contract checks (scene elements against the narration scenes)
  → voicing    synthesize narration per scene (through tts_cache) or probe uploaded audio, assemble window.__narration
  → mixing     concatenate scene audio, optional music with ducking, two-pass loudness to -16 LUFS, AAC 48 kHz
  → capturing  browser validation against the real narration, then per aspect frame by frame in a network-isolated Chromium, streamed to ffmpeg as segments
  → encoding   join segments, mux audio, optional subtitle burn-in, probe and verify
  → finalizing thumbnails, subtitles, upload, renditions
```

The same composition renders to 16:9, 9:16 and 1:1 by changing the viewport. Narration comes first; the composition builds its timeline from the real scene durations and word timings, so animation matches the audio by construction.

## 2. The composition document

A composition is one self-contained HTML document of at most 1 MB.

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Kinetic headline</title>
    <link rel="stylesheet" href="https://runtime.motionile.local/v1/base.css" />
    <style>
      .headline {
        font-size: var(--mo-text-title);
        font-weight: 700;
        text-align: center;
      }
      .headline .word {
        display: inline-block;
        margin-inline: 0.12em;
      }
    </style>
    <script src="https://runtime.motionile.local/v1/gsap/gsap.min.js"></script>
    <script src="https://runtime.motionile.local/v1/motionile.js"></script>
  </head>
  <body>
    <main class="mo-stage">
      <section class="mo-scene mo-center" data-scene="intro">
        <h1 class="headline" id="headline"></h1>
      </section>
    </main>
    <script>
      Motionile.composition({
        aspects: ["16:9", "9:16", "1:1"],
        scenes: [
          {
            id: "intro",
            build(ctx) {
              const headline = ctx.root.querySelector("#headline");
              const nodes = ctx.words.map((word) => {
                const span = document.createElement("span");
                span.className = "word";
                span.textContent = word.text;
                headline.append(span);
                return span;
              });
              nodes.forEach((node, index) => {
                ctx.timeline.from(
                  node,
                  { opacity: 0, y: 48, duration: 0.35, ease: "power3.out" },
                  ctx.at(index),
                );
              });
            },
          },
        ],
      });
    </script>
  </body>
</html>
```

## 3. `runtime@1`

Served only from local files at the virtual origin `https://runtime.motionile.local/v1/`. The renderer answers these requests itself; nothing is fetched from the network.

| Path                                                                                                                                          | Contents                                                                                                             |
| --------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `gsap/gsap.min.js`                                                                                                                            | GSAP core                                                                                                            |
| `gsap/TextPlugin.min.js`, `SplitText.min.js`, `DrawSVGPlugin.min.js`, `MorphSVGPlugin.min.js`, `MotionPathPlugin.min.js`, `CustomEase.min.js` | The plugins compositions may use. `motionile.js` registers every plugin that is loaded.                              |
| `gsap/LICENSE.md`                                                                                                                             | GSAP's license, shipped with the bundle. The pinned version is recorded in `engine/render/runtime/v1/manifest.json`. |
| `fonts/fonts.css` and `fonts/*.woff2`                                                                                                         | Geist, Geist Mono and Noto Sans (Latin), Noto Sans Devanagari for Hindi. `base.css` imports `fonts.css`.             |
| `base.css`                                                                                                                                    | Brand tokens, safe-area variables, layout primitives, typography scales per aspect                                   |
| `motionile.js`                                                                                                                                | The `window.Motionile` API below                                                                                     |

The fonts ship their Latin and Devanagari subsets only, so a glyph outside them (arrows, box drawing) falls back to a system font; draw such symbols with SVG or CSS. The font families are `Geist`, `Geist Mono`, `Noto Sans` and `Noto Sans Devanagari`. `base.css` sets `font-family: "Geist", "Noto Sans", "Noto Sans Devanagari", sans-serif` on the stage.

### 3.1 Tokens in `base.css`

Colors: `--mo-bg` (page), `--mo-surface`, `--mo-elevated`, `--mo-border`, `--mo-text-muted`, `--mo-text-secondary`, `--mo-text`, `--mo-accent`, `--mo-danger`, `--mo-success`. They carry the brand palette of `docs/context.md` section 2. A composition uses these and never raw colors for text on the stage background.

Type scale in pixels at the native viewport, by aspect (`html[data-aspect]`):

| Token                | 16:9 | 9:16 | 1:1 |
| -------------------- | ---- | ---- | --- |
| `--mo-text-small`    | 28   | 34   | 30  |
| `--mo-text-body`     | 36   | 44   | 40  |
| `--mo-text-subtitle` | 48   | 60   | 54  |
| `--mo-text-title`    | 72   | 88   | 80  |
| `--mo-text-display`  | 120  | 140  | 128 |
| `--mo-text-code`     | 30   | 34   | 32  |

The minimum rendered text size is the value of `--mo-text-small` for the aspect. Text below it fails validation with `font_too_small`.

Safe areas in pixels at the native viewport. The bottom inset reserves the caption band that burned-in subtitles use.

| Aspect | Viewport    | Left and right | Top | Bottom |
| ------ | ----------- | -------------- | --- | ------ |
| 16:9   | 1920 × 1080 | 96             | 64  | 160    |
| 9:16   | 1080 × 1920 | 72             | 160 | 420    |
| 1:1    | 1080 × 1080 | 72             | 72  | 200    |

They are exposed as `--mo-safe-left`, `--mo-safe-right`, `--mo-safe-top`, `--mo-safe-bottom`, plus `--mo-unit` (1% of the shorter side) for proportional spacing.

### 3.2 Layout primitives

`.mo-stage` fills the viewport, hides overflow and is a size container named `stage`, so `@container stage (aspect-ratio < 1)` styles portrait layouts and `(aspect-ratio <= 1)` portrait and square layouts. `.mo-scene` is absolutely positioned over the full stage and starts hidden; the runtime shows a scene only during its time range by setting `data-mo-active` on it (an inactive scene is `visibility: hidden !important`, so it keeps its layout and a builder can measure it). `.mo-safe` positions its box inside the safe area. `.mo-center`, `.mo-stack`, `.mo-row`, `.mo-split` (two columns in landscape, stacked in portrait and square through `@container stage (aspect-ratio <= 1)`), `.mo-card`, `.mo-code` and the text classes `.mo-title`, `.mo-body`, `.mo-caption`, `.mo-muted`, `.mo-accent` complete the set.

## 4. `window.__narration`

The renderer injects this object before any page script runs. Times are integer milliseconds.

```json
{
  "version": 1,
  "totalDurationMs": 7210,
  "scenes": [
    {
      "id": "intro",
      "index": 0,
      "startMs": 0,
      "durationMs": 3610,
      "text": "Every video begins with a question.",
      "words": [
        {
          "index": 0,
          "text": "Every",
          "startMs": 0,
          "endMs": 310,
          "sceneStartMs": 0,
          "sceneEndMs": 310
        },
        {
          "index": 1,
          "text": "video",
          "startMs": 310,
          "endMs": 640,
          "sceneStartMs": 310,
          "sceneEndMs": 640
        }
      ]
    }
  ]
}
```

A scene's `durationMs` is its audio duration plus the padding setting (no padding after the last scene). `startMs` of a scene is the sum of the previous durations. `startMs` and `endMs` of a word are absolute; `sceneStartMs` and `sceneEndMs` are relative to the scene start. `totalDurationMs` is the sum of the scene durations and excludes the tail.

## 5. `Motionile.composition`

```js
Motionile.composition({ scenes, aspects });
```

- `aspects`: the aspects the composition supports, a non-empty subset of `"16:9"`, `"9:16"`, `"1:1"`. A render option that asks for another aspect fails with `aspect_unsupported`.
- `scenes`: an array of `{ id, build }`. `id` equals a narration scene ID and the `data-scene` attribute of one element; the order equals the narration order. `build(ctx)` fills `ctx.timeline`.

The call validates its argument and returns at once; it throws if called twice. The build itself is asynchronous: it waits for the fonts, reads `window.__narration`, creates one child timeline per scene sized to the scene's duration, calls (and awaits) each builder, adds the child timelines to a master timeline at the scene starts, pads the master to the narration duration, pauses every timeline and Web Animation and publishes the globals below. `window.__ready` is set synchronously and settles when the build ends, so fonts are loaded before a builder measures anything. A scene's absolute start is `window.__narration.scenes[ctx.index].startMs`; CSS delays need it.

### 5.1 The scene context

All times in `ctx` are **seconds relative to the scene start**, because GSAP uses seconds.

| Member                | Meaning                                                                                                                                                                                                                                 |
| --------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ctx.id`, `ctx.index` | Scene ID and zero-based position                                                                                                                                                                                                        |
| `ctx.root`            | The scene element (`[data-scene]`)                                                                                                                                                                                                      |
| `ctx.duration`        | Scene duration in seconds, including trailing padding                                                                                                                                                                                   |
| `ctx.text`            | The scene's narration text                                                                                                                                                                                                              |
| `ctx.words`           | Array of `{ index, text, start, end }` in seconds                                                                                                                                                                                       |
| `ctx.at(target)`      | Start time of a word. `target` is a word index, or a string matched case-insensitively against word text (first match; `at("word", 2)` takes the third match). It throws when nothing matches, which fails the render with `page_error` |
| `ctx.end(target)`     | End time of a word, with the same lookup                                                                                                                                                                                                |
| `ctx.aspect`          | `"16:9"`, `"9:16"` or `"1:1"`                                                                                                                                                                                                           |
| `ctx.stage`           | `{ width, height }` in pixels                                                                                                                                                                                                           |
| `ctx.safeArea`        | `{ x, y, width, height }` in pixels inside the stage                                                                                                                                                                                    |
| `ctx.timeline`        | The scene's child GSAP timeline, time zero at the scene start                                                                                                                                                                           |

A builder runs once per page load, and the page is loaded once per aspect, so a builder may branch on `ctx.aspect`.

### 5.2 Globals

| Global                 | Contents                                                                                                                                                              |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `window.__timeline`    | The paused master timeline, set when the build ends                                                                                                                   |
| `window.__composition` | `{ version: 1, durationMs, aspects, scenes: [{ id, startMs, endMs, contentEndMs }] }`. `contentEndMs` is where the scene's own animations end, for the overflow check |
| `window.__ready`       | A promise that resolves when fonts are loaded, images are decoded and the timeline is built; it rejects when the build throws                                         |

`<html data-aspect>` carries the aspect from the first byte of the document.

### 5.3 Rules a composition must follow

These are documented, and the sanitizer, the sandbox or the validator enforces each one.

1. Exactly one `Motionile.composition` call (`composition_missing`, `composition_multiple`).
2. Scripts and styles load only from `https://runtime.motionile.local/v1/`; images only as `data:` URIs or runtime assets; no `<iframe>`, `<object>`, `<embed>`, `<form>`, `<base>`, `<audio>`, `<video>` (`forbidden_element`, `forbidden_url`).
3. No network, storage, worker, navigation or permission APIs: no `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `navigator.sendBeacon`, `Worker`, service workers, `localStorage`, `indexedDB`, `window.open`, `location` changes, WebRTC (`script_api`, `network_violation`).
4. Every scene's animations fit inside its duration (`scene_overflow`).
5. Animation is a function of time only. Use GSAP tweens on the scene timeline, or CSS animations, CSS transitions and the Web Animations API that are in effect from the first frame. All of them are seeked to the global composition time, so an `animation-delay` is measured from time zero of the document and must include the scene's start. Do not start animations from timeline callbacks, and keep callbacks idempotent functions of time (`non_deterministic_state`).
6. Do not read `Date`, `performance.now` or `Math.random` for anything visible. Time is frozen and `Math.random` is seeded, but a render must not depend on them.
7. Text stays inside its box, inside the safe area, never overlaps other text, is at least `--mo-text-small`, meets WCAG AA contrast and stays on screen (`text_overflow`, `safe_area_violation`, `text_overlap`, `font_too_small`, `contrast_low`, `element_offscreen`).
8. Do not rely on scene order in the DOM for layout; scenes are stacked and shown one at a time.

## 6. Determinism

The same composition, audio and options give frame-identical output ([ADR 0024](adr/0024-deterministic-capture-through-web-animations-and-frozen-clock.md)).

For each frame at time `t`:

1. Seek `window.__timeline` to `t`.
2. Pause every animation from `document.getAnimations()` and set its `currentTime` to `t` (CSS animations, CSS transitions, Web Animations API).
3. Advance the frozen clock by one frame.
4. Wait for two animation frames.
5. Take the screenshot.

Time is frozen with Playwright's clock (`Date`, `performance.now`, timers, `requestAnimationFrame`) and `Math.random` is a seeded generator installed before any page script. Screenshots never use `animations: "disabled"`. Frames are streamed to ffmpeg's standard input and never written to disk.

Parallel capture splits the timeline into contiguous chunks of `RENDER_CHUNK_SECONDS` seconds each, captured by `RENDER_PARALLEL_PAGES` pages. Chunk boundaries do not depend on the number of pages, so the same frames come out of one page or many. Each chunk is encoded as its own segment that starts on a keyframe, and segments are joined with ffmpeg's concat demuxer without re-encoding. Segments are encoded without B-frames and with a closed GOP, so each starts at time zero and the join is exact; the encoder thread count is pinned so the bitstream does not depend on the machine.

## 7. Static checks: the sanitizer

`engine/render/sanitize.py` parses the document with a spec-compliant HTML5 parser, then rejects or strips the constructs below and returns the cleaned document plus findings. Findings have `code`, `severity` (`error` or `warning`), `message`, `selector` and `detail`. Any error finding fails the render with `invalid_composition` after the report is stored.

| Code                    | Severity | Rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ----------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `forbidden_element`     | error    | `iframe`, `frame`, `frameset`, `object`, `embed`, `form`, `base`, `meta` with `http-equiv`, `link` other than runtime stylesheets, `audio`, `video`, `portal`, `applet`, `noscript`, `noembed`, `noframes`, `xmp`, `plaintext`, `script` with a type other than JavaScript or module                                                                                                                                                                                                                                                                                 |
| `forbidden_attribute`   | error    | Event-handler attributes (`on*`), `srcdoc`, `formaction`, `ping`, `target` on links, SVG `animate` and `set` elements that target `href` or an event handler                                                                                                                                                                                                                                                                                                                                                                                                         |
| `forbidden_url`         | error    | `javascript:` URLs and any URL outside the runtime origin and `data:` images in `src`, `href`, `xlink:href`, `srcset`, `poster`, `action`, CSS `url()`, `image-set()` and `@import` (in `<style>` and `style=""`). A `var()`, `attr()` or `env()` anywhere inside `url()`, `src()`, `image()`, `image-set()` or `cross-fade()` is rejected because its value cannot be checked, and so is a string in a custom property that starts with a URL scheme (`http:`, `https:`, `ftp:`, `file:`, `javascript:`, `ws:`, `blob:`, `data:` that is not a valid image) or `//` |
| `html_too_large`        | error    | More than 1 MB of markup, not counting `data:` URIs (the whole document may not exceed 3 MB)                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `data_uris_too_large`   | error    | More than 2 MB of `data:` URIs in total                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `too_many_elements`     | error    | More than 5,000 elements                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `invalid_data_uri`      | error    | A `data:` URI that is not an image or font, or is not valid base64                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `script_api`            | warning  | The script screen found `fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`, `sendBeacon`, `eval`, `Function`, `import()`, `importScripts`, `Worker`, `SharedWorker`, `serviceWorker`, storage, cookie, `window.open`, `location` or `history` use, `RTCPeerConnection` or computed access to `window` or `globalThis`. It is defense in depth only; the sandbox is the real control                                                                                                                                                                               |
| `scene_mismatch`        | error    | With the narration's scene IDs given: the `[data-scene]` elements are extra, duplicated or out of order                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `scene_element_missing` | error    | With the narration's scene IDs given: a scene has no `[data-scene]` element                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `composition_multiple`  | error    | More than one `Motionile.composition` call in the scripts                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| `parse_error`           | warning  | The parser recovered from malformed markup; the cleaned document is what the browser would build                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

Stripped elements and attributes are removed from the cleaned document and reported, so the repaired generator can see what happened. `script_api` findings are warnings so a false positive never blocks a render by itself; a real attempt still fails in the sandbox.

## 8. The sandbox

`engine/render/sandbox.py` ([ADR 0026](adr/0026-render-sandbox-design.md)).

- **Browser:** Playwright Chromium with its sandbox enabled; `--no-sandbox` is never passed. The worker container runs as a non-root user with Playwright's recommended seccomp profile.
- **Process:** Chromium starts with an explicit environment and nothing else: `PATH`, `HOME` (the work directory when configured), `SYSTEMROOT`, `TEMP`, `TMP` and `TMPDIR` as the process has them, plus `LANG=C.UTF-8` and `TZ=UTC`. The engine reads no environment itself; `modules/media` builds `RenderEngineConfig.browser_environment` from `Settings.process_environment`, so a worker secret (database, provider or signing keys) never reaches the browser process. When the browser or the Playwright driver does not stop within `shutdown_timeout_seconds`, the sandbox lists the processes whose command line carries its own `--motionile-render-id=<marker>`, adds their descendants and kills them, children first; it never touches a process without the marker.
- **Context:** a fresh browser context per render and per aspect; no permissions; downloads, service workers, WebRTC, geolocation and notifications disabled; JavaScript enabled; `deviceScaleFactor` 1.
- **Document:** the renderer fulfills the composition at `https://runtime.motionile.local/composition.html` with a strict `Content-Security-Policy` header (`default-src 'none'`, `script-src` and `style-src` from the runtime origin plus `'unsafe-inline'`, `img-src` and `font-src` from `data:` and the runtime origin, `connect-src 'none'`, `frame-src 'none'`, `worker-src 'none'`, `media-src 'none'`, `object-src 'none'`, `form-action 'none'`, `base-uri 'none'`, `sandbox allow-scripts`) and a restrictive `Permissions-Policy`.
- **Network:** every request is intercepted. Only the runtime origin and `data:` are fulfilled, from local files; everything else is aborted and recorded. A CSP violation report counts as an attempt too. Any attempt fails the render with `network_violation`. Chromium also runs with a host resolver rule that fails every name and a black-hole proxy.
- **Violations:** besides aborted requests and CSP reports, a violation is any use of a blocked API (`fetch`, `XMLHttpRequest`, `WebSocket`, `EventSource`, workers, WebRTC, storage, `navigator.sendBeacon`, `window.open`), any navigation, reload, popup, worker or download, and any browser message that says the sandbox or a policy blocked something. Service workers are off because the sandboxed document has an opaque origin, `worker-src` is `'none'` and the init script stubs `navigator.serviceWorker`; Playwright's `service_workers="block"` context option is not set because its injected script then throws under the CSP `sandbox` header and every render fails with `page_error`. A preflight is answered only for the exact runtime origin (scheme, host and port), so a look-alike host such as `runtime.motionile.local.evil.example` is a violation.
- **Limits:** timeouts on page load, `__ready` and every per-frame evaluation; a hung page is killed and the render fails with `timeout`. `pageerror` events and console errors fail the render with `page_error` and the messages in the report. A browser crash fails with `browser_crash`. A runaway allocation ends either in a crash (heap limit) or in `timeout` (the page is killed when its evaluation exceeds the limit); the container's memory limit is the backstop.

| Error code          | Cause                                                                         |
| ------------------- | ----------------------------------------------------------------------------- |
| `network_violation` | Any request to anything but the runtime origin or `data:`, including CSP hits |
| `timeout`           | Page load, `__ready`, a frame or a stage exceeded its limit                   |
| `page_error`        | An uncaught exception, a rejected `__ready` or a console error                |
| `browser_crash`     | The browser process or the page crashed or ran out of memory                  |

## 9. Validation

`engine/render/validate.py` produces a `ValidationReport`:

```json
{
  "version": 1,
  "valid": false,
  "issues": [
    {
      "code": "font_too_small",
      "severity": "error",
      "kind": "layout",
      "message": "Text is 24px; the minimum for 9:16 is 34px",
      "scene": "intro",
      "timeMs": 1800,
      "aspect": "9:16",
      "selector": "#footnote",
      "detail": { "fontSizePx": 24, "minimumPx": 34 }
    }
  ],
  "stats": { "scenes": 3, "aspects": 3, "samples": 27, "durationMs": 7210 }
}
```

`valid` is false when any issue has severity `error`. Errors block the render with `validation_failed`; warnings are reported. `kind` is `sanitize`, `contract`, `layout` or `runtime`. Phase 9 adds the vision-model review and automatic repair on top of this report.

### 9.1 Contract checks

| Code                      | Severity | Rule                                                                                 |
| ------------------------- | -------- | ------------------------------------------------------------------------------------ |
| `composition_missing`     | error    | `window.__timeline` or `window.__composition` does not exist once `__ready` resolved |
| `scene_mismatch`          | error    | The composition's scene IDs differ from the narration's, in content or order         |
| `scene_element_missing`   | error    | A scene has no `[data-scene]` element                                                |
| `aspect_unsupported`      | error    | A requested aspect is not in the composition's `aspects`                             |
| `duration_mismatch`       | error    | The timeline duration differs from the narration duration by more than 50 ms         |
| `scene_boundary_mismatch` | error    | A scene's start or end differs from the narration by more than 50 ms                 |
| `scene_overflow`          | error    | A scene's animations end after the scene's end by more than 50 ms                    |
| `non_deterministic_state` | error    | Two samples at the same time, taken in a different order, produce different pixels   |

### 9.2 Sampled-frame layout checks

Samples are taken at the start, middle and end of every scene, per aspect (50 ms after the start and 50 ms before the end, so a scene's own state is visible). A second probe one frame later finds elements that are still animating; those are skipped at that sample, so checks judge settled states. Text boxes are measured per line box (line height, not glyph extents). Contrast takes the 1st percentile of a pixel grid behind each text box, with text hidden.

| Code                  | Severity | Rule                                                                                                                                                                                                    |
| --------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `text_overflow`       | error    | Visible text overflows its own element box by more than 2 px                                                                                                                                            |
| `safe_area_violation` | error    | Visible text extends outside the safe area of the aspect                                                                                                                                                |
| `text_overlap`        | error    | Two visible text boxes that are not nested intersect by more than 16 px²                                                                                                                                |
| `font_too_small`      | error    | A visible text element's font size is below `--mo-text-small` for the aspect                                                                                                                            |
| `contrast_low`        | error    | Text contrast is below WCAG AA (4.5:1, or 3:1 for text of at least 24 px, or 18.66 px bold), computed from rendered colors: the text color with its opacity against the pixels rendered behind the text |
| `element_offscreen`   | error    | An important element (visible text, or any element with `data-important`) lies outside the viewport                                                                                                     |
| `empty_scene`         | warning  | The middle sample of a scene shows no visible content                                                                                                                                                   |

## 10. The pipeline

`render.run` is a procrastinate task on the `render` queue. `modules/media` orchestrates; `engine/render` and `engine/audio` do the work.

| Stage        | Status       | Work                                                                                                                                             | Checkpoint outputs under `work/renders/<id>/`    |
| ------------ | ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------ |
| `preparing`  | `preparing`  | Fetch the composition, sanitize it, check that its `[data-scene]` elements match the narration scenes of the options, store the cleaned document | `composition.clean.html`, `report.sanitize.json` |
| `voicing`    | `voicing`    | Synthesize each scene through `tts_cache` or probe uploaded audio, normalize to 48 kHz, assemble `window.__narration`                            | `scene-<n>.wav`, `narration.json`                |
| `mixing`     | `mixing`     | Concatenate, add music with ducking, two-pass loudness, encode AAC                                                                               | `audio.m4a`                                      |
| `capturing`  | `capturing`  | Run the browser contract and layout validation against the real narration, then per aspect capture chunks in parallel into video-only segments   | `report.json`, `segments/<aspect>/<chunk>.mp4`   |
| `encoding`   | `encoding`   | Per aspect, join segments, mux audio, optional subtitle burn-in, `+faststart`, ffprobe verification                                              | `video/<aspect>.mp4`                             |
| `finalizing` | `finalizing` | Thumbnails (WebP and JPEG), subtitles (WebVTT, SRT), upload to `media/`, create assets and renditions                                            | none; the renditions are the result              |

Contract and layout validation need the narration, so they run at the start of `capturing`, before any frame is captured; a failing validation ends the render before the expensive part. The sanitizer and the scene check run earlier, in `preparing`.

- **Checkpoints.** A stage writes its outputs under deterministic keys and records completion in `renders.checkpoints` (`completedAt`, `keys` and stage data such as `paddingMs` and `totalFrames`) in the same transaction that moves the status to the next stage; the mixed audio and the final renditions are stored as assets inside that transaction. A retry resumes at the first incomplete stage; within `capturing` it skips every segment object whose `plan` metadata (a fingerprint of frame rate, chunk length, frame count and encoder settings) matches, and reuses `report.json` instead of validating again; `encoding` skips every aspect whose `video/<aspect>.mp4` exists and downloads missing segments from storage on demand. Uploaded scene audio is kept at `work/renders/<id>/upload-<sceneId>.<ext>` and recorded in the `upload` checkpoint when the render is created.
- **Progress.** Each update writes `stage` and `progress` to the render (progress never decreases) and publishes a JSON message `{ "renderId", "status", "stage", "progress", "at" }` to the Redis channel built by `render_channel(keys, renderId)`, which is `<REDIS_KEY_PREFIX>:render:<id>`. A terminal message also carries `errorCode` and `errorMessage` when the render failed. A heartbeat touches `updated_at` every 30 seconds while a stage runs, so only a dead worker looks stalled. Progress weights: prepare 5, voicing 15, mixing 10, capturing 55, encoding 10, finalizing 5.
- **Cancellation.** `cancel_render` sets `cancel_requested_at` and a Redis flag (`<prefix>:render.cancel:<id>`); a queued render becomes `cancelled` at once. Capture checks the flag between frames and the database every five seconds, other stages between steps. A cancelled render ends `cancelled`; cancelling a finished render returns it unchanged.
- **Guardrails.** Per-stage timeouts, a free-disk check before capture (`RENDER_MIN_FREE_DISK_MB`), temporary directory cleanup even on failure, a maximum narration of 120 seconds plus a 1-second tail, and at most 3 aspects.
- **Failures.** Deterministic failures (`invalid_composition`, `validation_failed`, `network_violation`, `timeout`, `page_error`, `browser_crash`, `duration_limit_exceeded`, `insufficient_disk`, `tts_failed`, `output_check_failed`, `music_track_unavailable`) end the render `failed`. Infrastructure failures re-raise so the task retries and resumes. `media.fail_stalled_renders` fails a render whose `updated_at` has not moved for `RENDER_STALL_SECONDS` with `render_stalled`.

### 10.1 Output

- Video: H.264 High profile, `yuv420p`, constant frame rate, BT.709 color tags (`colorspace`, `color_primaries`, `color_trc` = `bt709`, limited range), `+faststart`, CRF and preset from settings.
- Audio: AAC at 48 kHz, −16 LUFS integrated, −1.5 dBTP true peak.
- The video lasts the narration plus the tail (`RENDER_TAIL_MS`, default 1000 ms) of the final state; the audio is padded with silence to the same length and the music fades out over it.
- Thumbnail: a poster frame per aspect at `RENDER_POSTER_MS` (clamped to the duration), WebP and JPEG.
- Every output is probed with ffprobe: duration, frame count, resolution, codecs, pixel format, color tags, and audio and video durations within 100 ms of each other. A mismatch fails the render with `output_check_failed`.

## 11. Storage layout

Only `media/` is served by the CDN.

| Prefix                                 | Contents                                                                                                                                |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `media/u/<userId>/renders/<renderId>/` | `16x9.mp4`, `9x16.mp4`, `1x1.mp4`; `poster-<aspect>.webp` and `.jpg`; `subtitles.vtt`, `subtitles.srt`; `audio.m4a`; `composition.html` |
| `work/renders/<renderId>/`             | Stage checkpoints and intermediate files; a bucket lifecycle rule expires them after 7 days                                             |
| `voice/u/<userId>/<voiceId>/`          | Voice samples and the consent recording; private, never on the CDN                                                                      |
| `tts/`                                 | Cached narration audio (`tts/<hash-prefix>/<hash>.<ext>`)                                                                               |
| `music/`                               | Licensed tracks                                                                                                                         |
| `voice-preview/`                       | Cached voice preview clips of built-in voices and cloned voices                                                                         |

The composition is stored as `text/plain`, so a browser that opens its CDN URL shows the text and never executes it on the CDN origin. Aspect labels in keys use `x` instead of `:` (`16x9`).

## 12. Delivery

`MediaDelivery` ([ADR 0028](adr/0028-media-delivery-and-microphone-policy.md)) has two implementations selected by `MEDIA_DELIVERY_MODE`.

**`cloudfront`**

- `GET /v1/media/session` sets `CloudFront-Policy`, `CloudFront-Signature` and `CloudFront-Key-Pair-Id`. The custom policy's resource is `https://cdn.<domain>/media/u/<userId>/*`; the lifetime is `MEDIA_COOKIE_TTL_SECONDS` (default and maximum 3600). The policy is signed with RSA-SHA1 using the private key from settings with `cryptography` (CloudFront requires SHA-1 for signed cookies and URLs) and encoded with CloudFront's URL-safe base64 (`+` → `-`, `=` → `_`, `/` → `~`). Cookies are `Secure`, `HttpOnly`, `SameSite=Lax`, `Path=/` and use the cookie domain from settings.
- Logout, logout from every device and revoking the current session expire the three cookies in the response with the same domain, path and attributes they were set with, only while `MEDIA_DELIVERY_MODE` is `cloudfront`. A copy of a cookie kept elsewhere stays valid until its own expiry, which is why the maximum lifetime is one hour.
- The same signer produces signed URLs for `/share/*`, and `signed_url(key, ttl)` for platforms that download media themselves.
- A user's cookie cannot fetch another user's path: the policy resource is the only access control, and CloudFront rejects anything outside it.

**`presigned`** (local MinIO and any non-AWS deployment)

- `GET /v1/media/session` returns `{ "mode": "presigned" }` and no cookies; rendition responses carry per-asset presigned GET URLs that live for `MEDIA_SIGNED_URL_TTL_SECONDS` (default 900, at most 3600). Both delivery modes check the key against the owner's `media/u/<userId>/` prefix when the caller passes the owner, so an asset row that points at another user's key is never linked. Clients request the rendition list again to refresh them.

Rendition responses include, for the active mode, the playable `url`, the `posterUrl`, the `subtitlesUrl` and the `attribution` of the music track when one was used. Range requests work for seeking in both modes and are verified by a test against MinIO.

## 13. Test bed API

All routes require `render.testbed`, are scoped to the caller's own renders and charge no credits.

| Method and path                               | Purpose                                                                                                                                                                                                                              |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `POST /v1/admin/render/testbed`               | `multipart/form-data` with `composition` (HTML file) and `options` (JSON string of `RenderOptions`); uploaded scene audio travels as extra file parts named in `options.narration.scenes[].audioPart`. Returns `202` with the render |
| `GET /v1/admin/render/testbed/{id}`           | Status, stage, progress, validation report, per-stage timings, error and renditions with playable URLs                                                                                                                               |
| `GET /v1/admin/render/testbed/{id}/events`    | Server-sent events: a snapshot, then every progress message of the render's channel, then the terminal state                                                                                                                         |
| `POST /v1/admin/render/testbed/{id}/cancel`   | Cooperative cancellation                                                                                                                                                                                                             |
| `GET /v1/admin/render/testbed/golden`         | The golden compositions: name, title, description, scene IDs and narration text                                                                                                                                                      |
| `POST /v1/admin/render/testbed/golden/{name}` | Renders a golden composition with `options` in the body; creates the render like `POST /v1/admin/render/testbed`                                                                                                                     |

`RenderOptions`:

```json
{
  "aspects": ["16:9", "9:16", "1:1"],
  "fps": 30,
  "narration": {
    "mode": "synthesize",
    "voiceId": "018f...",
    "scenes": [{ "sceneId": "intro", "text": "Every video begins with a question." }]
  },
  "musicTrackId": null,
  "subtitles": true,
  "burnInSubtitles": false
}
```

For uploaded audio, `narration` is `{ "mode": "upload", "scenes": [{ "sceneId": "intro", "audioPart": "audio-intro" }] }` with the audio in the multipart part of that name. `aspects` has one to three unique values, `fps` defaults to `RENDER_FPS`, and `burnInSubtitles` requires `subtitles`. The request carries `voiceId`; the stored options carry the resolved voice (`voiceId`, `provider`, `providerVoiceId`, `language`) and the concrete `fps`, plus `musicTrackId`. A render has at most 60 scenes, 2,000 characters per scene and 20,000 characters in total.

`POST /v1/admin/render/testbed/golden/{name}` takes `voiceId`, `aspects` (default all three), `fps`, `musicTrackId`, `subtitles` and `burnInSubtitles`; the narration comes from the golden `narration.json`. Names are checked against the directory listing, so a path never leaves `RENDER_GOLDEN_DIRECTORY` (default `apps/server/tests/fixtures/compositions`). `GET /v1/admin/render/testbed/music-tracks` lists the active tracks (`id`, `title`, `mood`, `bpm`, `durationMs`, `attribution`) for the picker. Creation is limited by the `render.create` policy (10 per hour per user), the multipart body to 128 MiB with a 4 MiB composition and 25 MiB per audio part, and a part that no scene names is rejected as an extra field. The body is read as a counted stream: a declared `Content-Length` above the cap is refused with `413` before any read, and a longer stream is cut off at the cap instead of being spooled to disk. Voice and music uploads use the same parser (`modules/media/bounded_upload.py`) with their own caps (`VOICES_SAMPLE_MAX_BYTES` and 50 MiB), and read the body only after authentication and rate limiting. The proxy adds `request_body { max_size 160MiB }` to the API site as a backstop above the largest cap (128 MiB); keep `VOICES_SAMPLE_MAX_BYTES` below that value or raise the proxy limit with it. Rejected audio answers `render_audio_rejected` with the reason in `reason`.

`GET /v1/admin/render/testbed/{id}/events` sends `event: snapshot` first, then `event: progress` for each message of the render's channel, `: heartbeat` comments every 15 seconds, and ends after the terminal message or when the client disconnects. It re-reads the render every 10 seconds, so a lost message cannot leave it hanging. Each user may hold at most 5 streams at once (a Redis sorted set of leases per user, 90-second lease renewed every 10 seconds, released when the stream ends); the sixth opens `429 too_many_streams`. The stream re-resolves the user's permissions before the snapshot and at every 10-second check, and ends silently when `render.testbed` was revoked.

User-facing reads for renders and their renditions are `GET /v1/renders/{renderId}` and `GET /v1/renders/{renderId}/renditions`, scoped to the owner. Phase 9 adds job endpoints on top.

## 14. Golden compositions

`apps/server/tests/fixtures/compositions/<name>/` holds `composition.html` and `narration.json` (`{ "language", "scenes": [{ "sceneId", "text" }] }`). They are the reference examples for Phase 9's skills and the inputs of the engine tests and the admin one-click runs. The worker image copies the directory to `/app/golden` and `RENDER_GOLDEN_DIRECTORY` points at it.

| Name                  | Shows                                                     |
| --------------------- | --------------------------------------------------------- |
| `kinetic-typography`  | Words appearing in sync with narration (`ctx.at`)         |
| `flow-diagram`        | A diagram that builds one step at a time, SVG draw        |
| `code-walkthrough`    | Code with line highlighting following the narration       |
| `data-structure`      | An array or tree operation animated step by step          |
| `comparison-split`    | A split-screen comparison that stacks in portrait         |
| `css-animation-scene` | CSS animation and transitions driven by the frozen clock  |
| `responsive-scene`    | One scene that is laid out correctly in all three aspects |

## 15. Configuration

| Variable                                                                                           | Default              | Meaning                                                                                                                                                                                              |
| -------------------------------------------------------------------------------------------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `RENDER_FPS`                                                                                       | `30`                 | Frame rate                                                                                                                                                                                           |
| `RENDER_X264_CRF`, `RENDER_X264_PRESET`                                                            | `20`, `veryfast`     | x264 quality and speed; presets from `veryfast` to `veryslow` (the faster presets drop the High profile)                                                                                             |
| `RENDER_PARALLEL_PAGES`                                                                            | CPU count (max 8)    | Pages capturing chunks in parallel                                                                                                                                                                   |
| `RENDER_CHUNK_SECONDS`                                                                             | `5`                  | Length of a capture chunk and its segment                                                                                                                                                            |
| `RENDER_SCENE_PADDING_MS`                                                                          | `400`                | Silence between scenes                                                                                                                                                                               |
| `RENDER_TAIL_MS`                                                                                   | `1000`               | Hold of the final frame                                                                                                                                                                              |
| `RENDER_MAX_DURATION_MS`                                                                           | `120000`             | Maximum narration duration                                                                                                                                                                           |
| `RENDER_POSTER_MS`                                                                                 | `2000`               | Poster frame time                                                                                                                                                                                    |
| `RENDER_PAGE_LOAD_TIMEOUT_SECONDS`, `RENDER_READY_TIMEOUT_SECONDS`, `RENDER_FRAME_TIMEOUT_SECONDS` | `15`, `15`, `10`     | Sandbox timeouts                                                                                                                                                                                     |
| `RENDER_STAGE_TIMEOUT_SECONDS`                                                                     | `1800`               | Wall-clock limit per stage                                                                                                                                                                           |
| `RENDER_STALL_SECONDS`                                                                             | `900`                | Age of the last progress update before a render counts as stalled                                                                                                                                    |
| `RENDER_MIN_FREE_DISK_MB`                                                                          | `2048`               | Free space required before capture                                                                                                                                                                   |
| `RENDER_BROWSER_MEMORY_MB`                                                                         | `768`                | JavaScript heap limit of the browser                                                                                                                                                                 |
| `RENDER_WORK_DIRECTORY`                                                                            | system temp          | Parent of per-render temporary directories                                                                                                                                                           |
| `RENDER_GOLDEN_DIRECTORY`                                                                          | repository fixtures  | Directory of golden compositions                                                                                                                                                                     |
| `APP_ROLE`                                                                                         | `service`            | `render_worker` for the render worker: deployed validation then skips the auth, billing, Turnstile, catalog, CORS, pagination and CloudFront signing-key requirements, which that process never uses |
| `RENDER_FFMPEG_PATH`, `RENDER_FFPROBE_PATH`                                                        | `ffmpeg`, `ffprobe`  | Binaries                                                                                                                                                                                             |
| `MEDIA_DELIVERY_MODE`                                                                              | `presigned`          | `cloudfront` or `presigned`                                                                                                                                                                          |
| `CDN_DOMAIN`, `CLOUDFRONT_KEY_PAIR_ID`, `CLOUDFRONT_PRIVATE_KEY`                                   | none                 | CloudFront host, key pair ID and PEM RSA private key; required in `cloudfront` mode                                                                                                                  |
| `MEDIA_COOKIE_DOMAIN`                                                                              | `AUTH_COOKIE_DOMAIN` | Domain of the signed cookies                                                                                                                                                                         |
| `MEDIA_COOKIE_TTL_SECONDS`, `MEDIA_SIGNED_URL_TTL_SECONDS`                                         | `3600`, `900`        | Cookie and presigned URL lifetimes; each at most 3600 seconds                                                                                                                                        |

Audio and voice settings are in [`audio.md`](audio.md).

## 16. Benchmark

`apps/server/scripts/benchmark_render.py` renders a synthetic composition (11 scenes, 65.4 seconds, fake narration timings) end to end through capture, segment encoding, join, mux and output verification for each aspect, and prints the time per video minute.

```
python scripts/benchmark_render.py --duration 60 --fps 30 --pages 8
```

Measured on a development machine (8 logical CPUs, Windows 11, Chromium headless shell 153, ffmpeg master build, `RENDER_PARALLEL_PAGES=8`, `RENDER_X264_PRESET=veryfast`, `RENDER_X264_CRF=20`, 30 fps):

| Aspect | Frames | Wall time | Seconds per video minute | Frames per second |
| ------ | ------ | --------- | ------------------------ | ----------------- |
| 16:9   | 1,962  | 164.8 s   | 148.8                    | 12.1              |
| 9:16   | 1,962  | 169.7 s   | 153.2                    | 11.7              |
| 1:1    | 1,962  | 126.3 s   | 114.1                    | 15.8              |

All three aspects render a 65-second 1080p video in under the 3-minute target on this machine, with a margin of about 1.2 times.

**Profile of one frame in a single page:** about 170 ms, made of roughly 80 ms for the seek and the page render, 50 ms for the CDP PNG screenshot, 27 ms for the two animation frames and 9 ms for the clock step. With eight pages the Chromium renderers and the ffmpeg PNG decode plus x264 encode compete for the same eight cores, so the run is CPU bound, not I/O bound. The bottleneck is the browser, not ffmpeg.

**Ways to gain headroom if the staging instance misses the target:** more cores (capture scales close to linearly with `RENDER_PARALLEL_PAGES` until the CPU saturates), caching frames of scenes that do not change, or a faster x264 preset such as `veryfast` already in use. JPEG intermediates would be faster but change the pixels and the color conversion, so they are not used.

The target on the staging instance (a 60-second, 1080p, 30 fps render per aspect in at most 3 minutes) is measured by running the same script on the `worker-render` host after deployment; record the result here when it is run.
