import pytest
from tests.scene_support import narration_for

from evals.browser import SandboxChecker
from evals.sync.fixtures import fixture_composition, fixture_module, fixture_storyboard
from evals.sync.probe import ASSOCIATION_MS, TOLERANCE_MS, measure_offsets, within_tolerance
from motionile.engine.ai.scenes.composer import compose
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.scenes.style_tokens import DEFAULT_STYLE_TOKENS
from motionile.engine.render.sandbox import RenderSandbox

pytestmark = [pytest.mark.slow, pytest.mark.asyncio(loop_scope="module")]

TEXT = "Every great video begins with a single question that the narration answers clearly"
SHIFTED_BUILDER = (
    "const words = ctx.words;\n"
    "words.forEach((word) => {\n"
    "  const node = document.createElement('span');\n"
    "  node.className = 'mo-title';\n"
    "  node.textContent = word.text;\n"
    "  ctx.root.append(node);\n"
    "  ctx.timeline.from(node, { opacity: 0, duration: 0.2 }, ctx.at(word.index) + 0.2);\n"
    "});\n"
)


async def test_the_scene_fixtures_start_their_animations_on_their_words(sandbox: RenderSandbox) -> None:
    html, narration = fixture_composition()

    offsets = await measure_offsets(sandbox, html, narration, ["16:9", "9:16"])

    assert len(offsets) > 20
    assert within_tolerance(offsets) / len(offsets) > 0.95


async def test_an_animation_shifted_by_two_hundred_milliseconds_is_measured_outside_the_tolerance(
    sandbox: RenderSandbox,
) -> None:
    module = SceneModule(scene_id="shifted", builder=SHIFTED_BUILDER)
    storyboard = fixture_storyboard(["shifted", "other"])
    modules = [module, fixture_module("default", "other")]
    composed = compose(modules, storyboard, DEFAULT_STYLE_TOKENS)

    offsets = await measure_offsets(sandbox, composed, narration_for([("shifted", TEXT), ("other", TEXT)]), ["16:9"])

    shifted = [offset for offset in offsets if abs(offset) > TOLERANCE_MS]
    assert len(shifted) >= len(TEXT.split())
    assert all(abs(offset) <= ASSOCIATION_MS for offset in shifted)


async def test_the_sandbox_checker_flags_an_overflowing_scene_and_accepts_a_good_one(sandbox: RenderSandbox) -> None:
    storyboard = fixture_storyboard(["good", "bad"])
    html = compose(
        [fixture_module("default", "good"), fixture_module("broken-overflow", "bad")], storyboard, DEFAULT_STYLE_TOKENS
    )
    narration = narration_for([("good", TEXT), ("bad", TEXT)])

    check = await SandboxChecker(sandbox).check(html, narration, ["16:9"])

    assert not check.valid
    assert {issue.scene_id for issue in check.issues if issue.is_blocking} == {"bad"}


async def test_the_sandbox_checker_samples_two_frames_per_scene_and_aspect(sandbox: RenderSandbox) -> None:
    html, narration = fixture_composition()

    frames = await SandboxChecker(sandbox).sample_frames(html, narration, ["16:9"])

    assert len(frames) == 2 * len(narration.scenes)
    assert all(frame.png.startswith(b"\x89PNG") for frame in frames)
