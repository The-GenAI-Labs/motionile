import pytest
from tests.scene_support import MINIMUM_NARRATION_WORDS, load_scene_fixture, make_storyboard, narration_for

from motionile.engine.ai.scenes.composer import compose
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.scenes.style_tokens import DEFAULT_STYLE_TOKENS
from motionile.engine.render.models import Aspect, ValidationReport
from motionile.engine.render.sandbox import RenderSandbox
from motionile.engine.render.sanitize import sanitize_composition
from motionile.engine.render.validate import validate_composition

pytestmark = [pytest.mark.slow, pytest.mark.asyncio(loop_scope="module")]

SEED = 20261024
TWELVE_WORDS = "Every great video begins with a single question that the narration answers clearly"
TWENTY_FOUR_WORDS = (
    "Every great video begins with a single question and the narration answers it clearly "
    "while each word appears exactly when it is spoken so the picture follows the voice"
)
OVERFLOW_CODES = {"text_overflow", "safe_area_violation"}


def first_words(text: str, count: int) -> str:
    return " ".join(text.split()[:count])


async def validate_modules(sandbox: RenderSandbox, modules: list[SceneModule], texts: list[str]) -> ValidationReport:
    ids = [module.scene_id for module in modules]
    html = compose(modules, make_storyboard(ids), DEFAULT_STYLE_TOKENS)
    sanitized = sanitize_composition(html, scene_ids=ids)
    assert sanitized.errors == ()
    narration = narration_for(list(zip(ids, texts, strict=True)))
    return await validate_composition(sandbox, sanitized.html, narration, list(Aspect), seed=SEED)


@pytest.mark.parametrize("name", list(MINIMUM_NARRATION_WORDS))
@pytest.mark.parametrize("text", [TWELVE_WORDS, TWENTY_FOUR_WORDS], ids=["twelve-words", "twenty-four-words"])
async def test_scene_fixture_is_valid_in_every_aspect(sandbox: RenderSandbox, name: str, text: str) -> None:
    modules = [load_scene_fixture(name, "first"), load_scene_fixture(name, "second")]

    report = await validate_modules(sandbox, modules, [text, TWELVE_WORDS])

    assert report.errors == ()
    assert report.warnings == ()


@pytest.mark.parametrize("name", list(MINIMUM_NARRATION_WORDS))
async def test_scene_fixture_is_valid_at_its_minimum_narration_length(sandbox: RenderSandbox, name: str) -> None:
    modules = [load_scene_fixture(name, "first"), load_scene_fixture(name, "second")]
    minimum = first_words(TWELVE_WORDS, MINIMUM_NARRATION_WORDS[name])

    report = await validate_modules(sandbox, modules, [minimum, TWELVE_WORDS])

    assert report.errors == ()


async def test_overflowing_fixture_reports_text_overflow_or_safe_area(sandbox: RenderSandbox) -> None:
    modules = [load_scene_fixture("broken-overflow", "first"), load_scene_fixture("default", "second")]

    report = await validate_modules(sandbox, modules, [TWELVE_WORDS, TWELVE_WORDS])

    assert OVERFLOW_CODES & {issue.code for issue in report.errors}
    assert {issue.scene for issue in report.errors} == {"first"}


async def test_low_contrast_fixture_reports_contrast_low(sandbox: RenderSandbox) -> None:
    modules = [load_scene_fixture("broken-contrast", "first"), load_scene_fixture("default", "second")]

    report = await validate_modules(sandbox, modules, [TWELVE_WORDS, TWELVE_WORDS])

    assert "contrast_low" in {issue.code for issue in report.errors}
    assert {issue.scene for issue in report.errors} == {"first"}
