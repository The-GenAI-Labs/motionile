from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from motionile.engine.ai.job_options import AspectName
from motionile.engine.ai.scenes.fallback import fallback_module
from motionile.engine.ai.scenes.models import SceneAsset, SceneModule
from motionile.engine.ai.scenes.style_tokens import DEFAULT_STYLE_TOKENS, STYLE_TOKEN_SETS, StyleTokens
from motionile.engine.ai.storyboard import Storyboard
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.render.synthetic import SyntheticScene, build_synthetic_narration

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCENE_FIXTURES = FIXTURES / "llm" / "scene"
COMPOSER_FIXTURES = FIXTURES / "ai" / "composer"
SCENE_ID_PLACEHOLDER = "{{sceneId}}"
ALL_ASPECTS: tuple[AspectName, ...] = ("16:9", "9:16", "1:1")
MINIMUM_NARRATION_WORDS = {
    "default": 1,
    "kinetic-typography": 1,
    "flow-diagram": 4,
    "code-walkthrough": 3,
    "data-structure": 8,
    "comparison-split": 8,
    "css-animation-scene": 1,
    "responsive-scene": 7,
}


def make_storyboard(
    scene_ids: Sequence[str],
    *,
    aspects: Sequence[AspectName] = ALL_ASPECTS,
    title: str = "Test video",
    language: str = "en",
    style: str = "minimal-dark",
) -> Storyboard:
    return Storyboard.model_validate(
        {
            "title": title,
            "summary": "A deterministic test storyboard.",
            "audienceLevel": "beginner",
            "language": language,
            "targetDurationMs": 20_000,
            "aspects": list(aspects),
            "styleSkill": style,
            "scenes": [
                {
                    "id": scene_id,
                    "position": position,
                    "goal": "Explain one idea",
                    "narration": "One two three four five six seven eight.",
                    "visualBrief": "Show the idea",
                    "layoutNotes": dict.fromkeys(aspects, "Center it"),
                    "targetDurationMs": 5_000,
                }
                for position, scene_id in enumerate(scene_ids)
            ],
        }
    )


def scene_fixture_text(name: str) -> str:
    return (SCENE_FIXTURES / f"{name}.json").read_text(encoding="utf-8")


def load_scene_fixture(name: str, scene_id: str) -> SceneModule:
    text = scene_fixture_text(name).replace(SCENE_ID_PLACEHOLDER, scene_id)
    return SceneModule.model_validate_json(text)


def narration_for(texts: Sequence[tuple[str, str]]) -> NarrationDocument:
    return build_synthetic_narration([SyntheticScene(scene_id, text) for scene_id, text in texts])


@dataclass(frozen=True)
class ComposeCase:
    modules: tuple[SceneModule, ...]
    storyboard: Storyboard
    tokens: StyleTokens


FLOW_SVG = (
    '<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">'
    '<defs><linearGradient id="fade"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#000"/>'
    '</linearGradient></defs><circle cx="50" cy="50" r="40" fill="url(#fade)"/></svg>'
)
PLAIN_SVG = '<svg viewBox="0 0 10 10"><rect width="10" height="10"/></svg>'


def golden_cases() -> dict[str, ComposeCase]:
    minimal_modules = (
        SceneModule(scene_id="intro", builder="ctx.timeline.from(ctx.root, { opacity: 0, duration: 0.4 }, 0);"),
        SceneModule(
            scene_id="outro",
            builder="const last = ctx.words.length - 1;\nctx.timeline.from(ctx.root, { opacity: 0 }, ctx.at(last));",
            css=".mo-s-outro { display: flex; }",
        ),
    )
    styled_modules = (
        SceneModule(
            scene_id="first",
            builder='const marker = "</script><!-- x -->";\nctx.root.dataset.marker = marker;\n',
            css=".mo-s-first .title { color: var(--mo-accent); }\n.mo-s-first::after { content: '</style>'; }",
            assets=[SceneAsset(id="flow", svg=FLOW_SVG), SceneAsset(id="plain", svg=PLAIN_SVG)],
        ),
        fallback_module("second"),
        SceneModule(
            scene_id="third",
            builder="ctx.timeline.to(ctx.root.querySelector('[data-asset=\"plain\"]'), { rotation: 90 }, 0.2);",
            css=(
                "@media (min-width: 1px) {\n  .mo-s-third .box { opacity: 1; }\n}\n"
                "@keyframes mo-s-third-spin { to { transform: rotate(1turn); } }"
            ),
            assets=[SceneAsset(id="plain", svg=PLAIN_SVG)],
        ),
    )
    return {
        "minimal": ComposeCase(
            minimal_modules,
            make_storyboard(["intro", "outro"], title='Minimal & <clean> "video"'),
            DEFAULT_STYLE_TOKENS,
        ),
        "styled": ComposeCase(
            styled_modules,
            make_storyboard(["first", "second", "third"], aspects=("16:9", "1:1"), language="hi", style="whiteboard"),
            STYLE_TOKEN_SETS["whiteboard"],
        ),
    }
