from motionile.engine.ai.scenes.models import SceneModule, scene_root_class

MAX_WORDS_PER_PAGE = 12
MAX_CHARS_PER_PAGE = 140
MAX_CHARS_PER_WORD = 40
TITLE_SIZE_MAX_CHARS = 64

ROOT_PLACEHOLDER = "__ROOT__"

FALLBACK_BUILDER = f"""const MAX_WORDS = {MAX_WORDS_PER_PAGE};
const MAX_CHARS = {MAX_CHARS_PER_PAGE};
const MAX_WORD_CHARS = {MAX_CHARS_PER_WORD};
const TITLE_MAX_CHARS = {TITLE_SIZE_MAX_CHARS};
const REVEAL_SECONDS = 0.3;
const PAGE_IN_SECONDS = 0.12;
const PAGE_OUT_SECONDS = 0.2;
const latest = Math.max(ctx.duration - REVEAL_SECONDS, 0);
const clip = (text) => {{
  const letters = Array.from(text);
  return letters.length > MAX_WORD_CHARS ? letters.slice(0, MAX_WORD_CHARS).join("") + "..." : text;
}};
const pages = [];
ctx.words.forEach((word) => {{
  const text = clip(word.text);
  const page = pages[pages.length - 1];
  if (page && page.words.length < MAX_WORDS && page.chars + 1 + text.length <= MAX_CHARS) {{
    page.words.push({{ text, index: word.index }});
    page.chars += 1 + text.length;
  }} else {{
    pages.push({{ words: [{{ text, index: word.index }}], chars: text.length }});
  }}
}});
const stage = document.createElement("div");
stage.className = "mo-fb-stage";
ctx.root.append(stage);
const startOf = (page) => Math.min(ctx.at(page.words[0].index), latest);
pages.forEach((page, pageIndex) => {{
  const element = document.createElement("div");
  element.className = "mo-fb-page " + (page.chars > TITLE_MAX_CHARS ? "mo-fb-subtitle" : "mo-fb-title");
  const line = document.createElement("p");
  line.className = "mo-fb-line";
  line.dir = "auto";
  element.append(line);
  stage.append(element);
  const first = startOf(page);
  ctx.timeline.fromTo(element, {{ opacity: 0 }}, {{ opacity: 1, duration: PAGE_IN_SECONDS, ease: "none" }}, first);
  page.words.forEach((word) => {{
    const node = document.createElement("span");
    node.className = "mo-fb-word";
    node.textContent = word.text;
    line.append(node);
    ctx.timeline.fromTo(
      node,
      {{ opacity: 0, y: 24 }},
      {{ opacity: 1, y: 0, duration: REVEAL_SECONDS, ease: "power3.out" }},
      Math.min(ctx.at(word.index), latest),
    );
  }});
  if (pageIndex < pages.length - 1) {{
    const next = startOf(pages[pageIndex + 1]);
    const earliest = first + PAGE_IN_SECONDS;
    const fadeStart = Math.min(Math.max(next - PAGE_OUT_SECONDS, earliest), ctx.duration - PAGE_OUT_SECONDS);
    ctx.timeline.fromTo(
      element,
      {{ opacity: 1 }},
      {{ opacity: 0, duration: PAGE_OUT_SECONDS, ease: "none", immediateRender: false }},
      Math.max(fadeStart, 0),
    );
  }}
}});
"""

FALLBACK_CSS = """.__ROOT__ {
  display: flex;
  align-items: center;
  justify-content: center;
}
.__ROOT__ .mo-fb-stage {
  position: relative;
  width: 100%;
  height: 100%;
}
.__ROOT__ .mo-fb-page {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
}
.__ROOT__ .mo-fb-title {
  font-size: var(--mo-text-title);
}
.__ROOT__ .mo-fb-subtitle {
  font-size: var(--mo-text-subtitle);
}
.__ROOT__ .mo-fb-line {
  margin: 0;
  max-width: 100%;
  color: var(--mo-text);
  font-weight: 700;
  line-height: 1.3;
  letter-spacing: -0.01em;
  text-align: center;
  overflow-wrap: anywhere;
}
.__ROOT__ .mo-fb-word {
  display: inline-block;
  margin-inline: 0.14em;
}
"""


def fallback_module(scene_id: str) -> SceneModule:
    root = scene_root_class(scene_id)
    return SceneModule(
        scene_id=scene_id,
        builder=FALLBACK_BUILDER,
        css=FALLBACK_CSS.replace(f".{ROOT_PLACEHOLDER}", f".{root}"),
    )
