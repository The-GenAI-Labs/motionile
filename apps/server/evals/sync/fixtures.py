from pathlib import Path
from typing import Final

from evals.clients import FIXTURES_ROOT
from motionile.engine.ai.job_options import AspectName
from motionile.engine.ai.scenes.composer import compose
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.scenes.style_tokens import DEFAULT_STYLE_TOKENS
from motionile.engine.ai.storyboard import Storyboard
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.render.synthetic import SyntheticScene, build_synthetic_narration

FIXTURE_NAMES: Final = (
    "kinetic-typography",
    "flow-diagram",
    "code-walkthrough",
    "data-structure",
    "comparison-split",
    "default",
    "responsive-scene",
    "css-animation-scene",
)
SCENE_ID_PLACEHOLDER: Final = "{{sceneId}}"
FIXTURE_ASPECTS: Final[tuple[AspectName, ...]] = ("16:9", "9:16", "1:1")
FIXTURE_NARRATION: Final = (
    "Every great video begins with a single question and the narration answers it clearly "
    "while each word appears exactly when it is spoken so the picture follows the voice"
)


def fixture_module(name: str, scene_id: str, root: Path = FIXTURES_ROOT) -> SceneModule:
    text = (root / "scene" / f"{name}.json").read_text(encoding="utf-8")
    return SceneModule.model_validate_json(text.replace(SCENE_ID_PLACEHOLDER, scene_id))


def fixture_storyboard(scene_ids: list[str]) -> Storyboard:
    return Storyboard.model_validate(
        {
            "title": "Scene fixtures",
            "summary": "Every scene fixture in one composition.",
            "audienceLevel": "beginner",
            "language": "en",
            "targetDurationMs": 60_000,
            "aspects": list(FIXTURE_ASPECTS),
            "styleSkill": "minimal-dark",
            "scenes": [
                {
                    "id": scene_id,
                    "position": position,
                    "goal": "Explain one idea",
                    "narration": FIXTURE_NARRATION,
                    "visualBrief": "Show the idea",
                    "layoutNotes": dict.fromkeys(FIXTURE_ASPECTS, "Center it"),
                    "targetDurationMs": 5_000,
                }
                for position, scene_id in enumerate(scene_ids)
            ],
        }
    )


def fixture_composition(root: Path = FIXTURES_ROOT) -> tuple[str, NarrationDocument]:
    scene_ids = [f"fixture-{position + 1}" for position in range(len(FIXTURE_NAMES))]
    modules = [fixture_module(name, scene_id, root) for name, scene_id in zip(FIXTURE_NAMES, scene_ids, strict=True)]
    html = compose(modules, fixture_storyboard(scene_ids), DEFAULT_STYLE_TOKENS)
    narration = build_synthetic_narration([SyntheticScene(scene_id, FIXTURE_NARRATION) for scene_id in scene_ids])
    return html, narration
