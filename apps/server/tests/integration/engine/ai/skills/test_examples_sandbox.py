import pytest
from tests.skill_support import compose_example
from tests.unit.engine.ai.skills.support import all_examples, example_id

from motionile.engine.ai.scenes.style_tokens import DEFAULT_STYLE_TOKENS, STYLE_TOKEN_SETS, StyleTokens
from motionile.engine.ai.skills.examples import SkillExample
from motionile.engine.render.models import Aspect, ValidationReport
from motionile.engine.render.sandbox import RenderSandbox
from motionile.engine.render.sanitize import sanitize_composition
from motionile.engine.render.validate import validate_composition

pytestmark = [pytest.mark.slow, pytest.mark.asyncio(loop_scope="module")]

SEED = 20261024
EXAMPLES = all_examples()
EXAMPLE_IDS = [example_id(example) for example in EXAMPLES]
STYLES = [pytest.param(tokens, id=slug) for slug, tokens in STYLE_TOKEN_SETS.items() if tokens.has_overrides]


async def validate_example(sandbox: RenderSandbox, example: SkillExample, tokens: StyleTokens) -> ValidationReport:
    composed = compose_example(example, tokens)
    sanitized = sanitize_composition(composed.html, scene_ids=list(composed.scene_ids))
    assert sanitized.errors == ()
    return await validate_composition(sandbox, sanitized.html, composed.narration, list(Aspect), seed=SEED)


@pytest.mark.parametrize("example", EXAMPLES, ids=EXAMPLE_IDS)
async def test_an_example_is_valid_in_every_aspect(sandbox: RenderSandbox, example: SkillExample) -> None:
    report = await validate_example(sandbox, example, DEFAULT_STYLE_TOKENS)

    assert [(issue.code, issue.scene, issue.message) for issue in report.errors] == []
    assert report.warnings == ()


@pytest.mark.parametrize("tokens", STYLES)
@pytest.mark.parametrize("example", EXAMPLES, ids=EXAMPLE_IDS)
async def test_an_example_keeps_its_contrast_in_every_style(
    sandbox: RenderSandbox, example: SkillExample, tokens: StyleTokens
) -> None:
    report = await validate_example(sandbox, example, tokens)

    assert [(issue.code, issue.scene, issue.message) for issue in report.errors] == []
