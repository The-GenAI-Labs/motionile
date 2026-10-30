import pytest
from tests.scene_support import make_storyboard, narration_for

from motionile.engine.ai.scenes.composer import compose
from motionile.engine.ai.scenes.fallback import fallback_module
from motionile.engine.ai.scenes.static_checks import check_scene_module
from motionile.engine.ai.scenes.style_tokens import DEFAULT_STYLE_TOKENS, STYLE_TOKEN_SETS, TOKEN_NAMES, StyleTokens
from motionile.engine.render.models import Aspect, ValidationReport
from motionile.engine.render.sandbox import PageSpec, RenderSandbox
from motionile.engine.render.sanitize import sanitize_composition
from motionile.engine.render.validate import validate_composition

pytestmark = [pytest.mark.slow, pytest.mark.asyncio(loop_scope="module")]

SEED = 20261024
CLOSING_TEXT = "That is the whole idea."
DEVANAGARI = "आज हम सीखेंगे कि एक सवाल से पूरा वीडियो कैसे बनता है और हर शब्द आवाज़ के साथ स्क्रीन पर आता है।"
LONG_WORDS = " ".join(["supercalifragilisticexpialidocious" * 2] * 12)
NARRATIONS = {
    "one-word": "Motionile",
    "twelve-words": "one two three four five six seven eight nine ten eleven twelve",
    "sixty-words": " ".join(f"word{index}" for index in range(60)),
    "threehundred-thirty-words": " ".join(f"term{index % 40}" for index in range(330)),
    "devanagari": DEVANAGARI,
    "twelve-very-long-words": LONG_WORDS,
}


async def validate_fallbacks(sandbox: RenderSandbox, narration_text: str, tokens: StyleTokens) -> ValidationReport:
    storyboard = make_storyboard(["opening", "closing"], style=tokens.slug)
    modules = [fallback_module("opening"), fallback_module("closing")]
    for module in modules:
        assert check_scene_module(module) == []
    html = compose(modules, storyboard, tokens)
    narration = narration_for([("opening", narration_text), ("closing", CLOSING_TEXT)])
    sanitized = sanitize_composition(html, scene_ids=["opening", "closing"])
    assert sanitized.findings == ()
    return await validate_composition(sandbox, sanitized.html, narration, list(Aspect), seed=SEED)


@pytest.mark.parametrize("name", list(NARRATIONS))
async def test_fallback_passes_validation_for_every_narration_length(sandbox: RenderSandbox, name: str) -> None:
    report = await validate_fallbacks(sandbox, NARRATIONS[name], DEFAULT_STYLE_TOKENS)

    assert report.errors == ()
    assert report.warnings == ()
    assert report.stats.aspects == 3
    assert report.stats.samples == 3 * 3 * 2


@pytest.mark.parametrize("slug", list(STYLE_TOKEN_SETS))
async def test_fallback_passes_validation_under_every_style(sandbox: RenderSandbox, slug: str) -> None:
    report = await validate_fallbacks(sandbox, NARRATIONS["sixty-words"], STYLE_TOKEN_SETS[slug])

    assert report.errors == ()
    assert report.warnings == ()


@pytest.mark.parametrize("aspect", list(Aspect))
@pytest.mark.parametrize("slug", list(STYLE_TOKEN_SETS))
async def test_style_tokens_override_base_css_in_every_aspect(
    sandbox: RenderSandbox, slug: str, aspect: Aspect
) -> None:
    tokens = STYLE_TOKEN_SETS[slug]
    storyboard = make_storyboard(["opening", "closing"], style=slug)
    html = compose([fallback_module("opening"), fallback_module("closing")], storyboard, tokens)
    narration = narration_for([("opening", NARRATIONS["twelve-words"]), ("closing", CLOSING_TEXT)])

    async with sandbox.page(PageSpec(html=html, narration=narration, aspect=aspect, seed=SEED)) as page:
        computed = await page.evaluate(
            "(names) => names.map((name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim())",
            list(TOKEN_NAMES),
        )

    assert dict(zip(TOKEN_NAMES, computed, strict=True)) == tokens.palette
