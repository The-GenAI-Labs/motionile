from dataclasses import dataclass

from tests.scene_support import ALL_ASPECTS, make_storyboard, narration_for

from motionile.engine.ai.scenes.composer import compose
from motionile.engine.ai.scenes.fallback import fallback_module
from motionile.engine.ai.scenes.style_tokens import DEFAULT_STYLE_TOKENS, StyleTokens
from motionile.engine.ai.skills.examples import EXAMPLE_SCENE_ID, SkillExample
from motionile.engine.audio.narration_models import NarrationDocument

CLOSING_SCENE_ID = "outro"
CLOSING_NARRATION = "Thanks for watching this short explainer."


@dataclass(frozen=True, slots=True)
class ComposedExample:
    html: str
    scene_ids: tuple[str, ...]
    narration: NarrationDocument


def compose_example(example: SkillExample, tokens: StyleTokens = DEFAULT_STYLE_TOKENS) -> ComposedExample:
    scene_ids = (EXAMPLE_SCENE_ID, CLOSING_SCENE_ID)
    modules = [example.scene_module(), fallback_module(CLOSING_SCENE_ID)]
    html = compose(modules, make_storyboard(list(scene_ids), aspects=ALL_ASPECTS, style=tokens.slug), tokens)
    narration = narration_for([(EXAMPLE_SCENE_ID, example.narration), (CLOSING_SCENE_ID, CLOSING_NARRATION)])
    return ComposedExample(html=html, scene_ids=scene_ids, narration=narration)
