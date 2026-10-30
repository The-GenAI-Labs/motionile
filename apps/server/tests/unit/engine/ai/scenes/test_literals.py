import time
from uuid import uuid4

import pytest
from tests.scene_support import load_scene_fixture
from tests.unit.engine.ai.support import StaticPrompts

from motionile.engine.ai.ports import LoadedSkill, SkillLayer, SkillSummary
from motionile.engine.ai.prompts.canary import OutputScanner
from motionile.engine.ai.scenes.literals import builder_literals, css_literals, scene_literals, svg_literals
from motionile.engine.ai.scenes.models import SceneAsset, SceneModule

GOOD_FIXTURES = (
    "default",
    "kinetic-typography",
    "flow-diagram",
    "code-walkthrough",
    "data-structure",
    "comparison-split",
    "css-animation-scene",
    "responsive-scene",
)


def scanner() -> OutputScanner:
    return OutputScanner(list(StaticPrompts().prompts.values()), ())


def test_builder_strings_are_extracted_without_code_or_identifiers() -> None:
    builder = 'const label = \'Hello world\'; ctx.at(0); const t = `Packets ${1 + 1} travel`; const q = "say \\"hi\\"";'

    found = list(builder_literals(builder))

    assert "Hello world" in found
    assert any(text.startswith("Packets") for text in found)
    assert not any("const" in text or "ctx" in text for text in found)


def test_css_strings_are_extracted_from_both_quote_styles() -> None:
    css = ".mo-s-a::before { content: 'first part'; } .mo-s-a::after { content: \"second part\"; color: red; }"

    assert list(css_literals(css)) == ["first part", "second part"]


def test_svg_text_nodes_are_extracted_without_markup() -> None:
    svg = "<svg xmlns='http://www.w3.org/2000/svg'><text x='1'>Client &amp; server</text><title>Nodes</title></svg>"

    [text] = list(svg_literals(svg))

    assert "Client & server" in text
    assert "Nodes" in text
    assert "<" not in text


def test_a_module_without_strings_has_no_literals() -> None:
    assert scene_literals(SceneModule(scene_id="a", builder="ctx.at(0);")) == ""


def test_literals_of_every_part_are_joined() -> None:
    module = SceneModule(
        scene_id="a",
        builder="const a = 'one';",
        css=".mo-s-a::after { content: 'two'; }",
        assets=[SceneAsset(id="x", svg="<svg><text>three</text></svg>")],
    )

    assert scene_literals(module).split() == ["one", "two", "three"]


@pytest.mark.parametrize("name", GOOD_FIXTURES)
def test_the_golden_scene_fixtures_pass_the_scene_scan(name: str) -> None:
    module = load_scene_fixture(name, "demo")
    code = "\n".join([module.builder, module.css, *(asset.svg for asset in module.assets)])

    assert not scanner().scan_scene(code, scene_literals(module)).blocked


def test_a_long_prompt_run_inside_a_string_is_an_overlap() -> None:
    prompts = StaticPrompts()
    body = prompts.prompts["scene.module"].body
    run = " ".join(" ".join(body.split())[300:].split()[:14])
    module = SceneModule(scene_id="a", builder=f"const note = {run!r};")
    code = module.builder

    assert OutputScanner(list(prompts.prompts.values()), ()).scan_scene(code, scene_literals(module)).kind == "overlap"


def test_skill_text_stays_exempt_in_scene_output() -> None:
    reused = " ".join(f"concept{index}" for index in range(40))
    summary = SkillSummary(
        slug="flow", name="Flow", description="Flow diagrams", layer=SkillLayer.VISUAL, version_id=uuid4()
    )
    skill = LoadedSkill(summary=summary, body=reused, tokens={}, token_count=10)
    candidate = OutputScanner(list(StaticPrompts().prompts.values()), [skill])

    assert candidate.scan_text(reused).kind == "overlap"
    assert not candidate.scan_scene(f"const note = '{reused}';", reused).blocked


def test_the_canary_is_still_found_anywhere_in_the_module_code() -> None:
    prompts = StaticPrompts()
    canary = prompts.prompts["scene.module"].canary
    module = SceneModule(scene_id="a", builder=f"ctx.root.dataset.note = 'x'; // {canary}")

    result = OutputScanner(list(prompts.prompts.values()), ()).scan_scene(module.builder, scene_literals(module))

    assert result.kind == "canary"


def test_scanning_a_large_module_stays_fast() -> None:
    module = SceneModule(
        scene_id="a",
        builder="\n".join(
            f"const text{index} = 'ordinary label number {index} for the diagram';" for index in range(300)
        ),
        css="\n".join(f".mo-s-a .n{index}::after {{ content: 'label {index}'; }}" for index in range(300)),
    )
    code = "\n".join([module.builder, module.css])
    candidate = scanner()

    started = time.perf_counter()
    result = candidate.scan_scene(code, scene_literals(module))
    elapsed = time.perf_counter() - started

    assert not result.blocked
    assert elapsed < 1
