import itertools
import re

import pytest
from tests.scene_support import COMPOSER_FIXTURES, ComposeCase, golden_cases, make_storyboard

from motionile.engine.ai.scenes.composer import ComposeError, compose
from motionile.engine.ai.scenes.models import SceneAsset, SceneModule
from motionile.engine.ai.scenes.style_tokens import DEFAULT_STYLE_TOKENS, STYLE_TOKEN_SETS
from motionile.engine.render.sanitize import sanitize_composition

CASES = golden_cases()


def composed(case: ComposeCase) -> str:
    return compose(case.modules, case.storyboard, case.tokens)


@pytest.mark.parametrize("name", list(CASES))
def test_output_matches_the_golden_file_byte_for_byte(name: str) -> None:
    expected = (COMPOSER_FIXTURES / f"{name}.html").read_bytes()

    assert composed(CASES[name]).encode("utf-8") == expected


@pytest.mark.parametrize("name", list(CASES))
def test_composing_twice_gives_identical_bytes(name: str) -> None:
    assert composed(CASES[name]) == composed(CASES[name])


@pytest.mark.parametrize("name", list(CASES))
def test_input_order_does_not_change_the_output(name: str) -> None:
    case = CASES[name]
    expected = composed(case)

    for ordering in itertools.permutations(case.modules):
        assert compose(ordering, case.storyboard, case.tokens) == expected


@pytest.mark.parametrize("name", list(CASES))
def test_composed_documents_pass_the_sanitizer_without_findings(name: str) -> None:
    case = CASES[name]

    result = sanitize_composition(composed(case), scene_ids=[scene.id for scene in case.storyboard.scenes])

    assert result.findings == ()
    assert result.composition_calls == 1
    assert result.scene_ids == tuple(scene.id for scene in case.storyboard.scenes)


def test_the_document_has_the_documented_shape() -> None:
    html = composed(CASES["styled"])

    assert html.startswith(
        '<!doctype html>\n<html lang="hi">\n<head>\n<meta charset="utf-8">\n<title>Test video</title>'
    )
    assert '<link rel="stylesheet" href="https://runtime.motionile.local/v1/base.css">' in html
    assert '<script src="https://runtime.motionile.local/v1/gsap/gsap.min.js"></script>' in html
    assert '<script src="https://runtime.motionile.local/v1/motionile.js"></script>' in html
    assert '<main class="mo-stage">' in html
    assert '<section class="mo-scene mo-s-first" data-scene="first">' in html
    assert '<div data-asset="flow"><svg' in html
    assert 'aspects: ["16:9", "1:1"]' in html
    assert html.count("Motionile.composition(") == 1
    assert html.endswith("</html>\n")


def test_scenes_follow_the_storyboard_order_in_sections_and_registrations() -> None:
    html = composed(CASES["styled"])

    sections = re.findall(r'<section class="mo-scene mo-s-(\w+)" data-scene="\1">', html)
    registered = re.findall(r'^      id: "(\w+)",$', html, flags=re.MULTILINE)
    assert sections == registered == ["first", "second", "third"]


def test_scene_styles_do_not_use_the_scene_attribute() -> None:
    html = composed(CASES["styled"])

    assert html.count("data-scene=") == 3
    assert 'data-mo-scene-style="first"' in html


def test_token_overrides_are_emitted_only_when_tokens_exist() -> None:
    plain = composed(CASES["minimal"])
    styled = composed(CASES["styled"])

    assert "mo-style-tokens" not in plain
    assert styled.count('<style id="mo-style-tokens">') == 1
    assert '<style id="mo-style-tokens">html[data-aspect]{--mo-bg:#f7f5ee;' in styled
    assert styled.index("mo-style-tokens") < styled.index('data-mo-scene-style="first"')


def test_every_shipped_token_set_composes() -> None:
    case = CASES["minimal"]
    storyboard = make_storyboard(["intro", "outro"])

    for tokens in STYLE_TOKEN_SETS.values():
        html = compose(case.modules, storyboard, tokens)
        assert ("mo-style-tokens" in html) is tokens.has_overrides


def test_the_title_is_html_escaped() -> None:
    html = composed(CASES["minimal"])

    assert '<title>Minimal &amp; &lt;clean&gt; "video"</title>' in html


def test_a_builder_cannot_close_the_script_element() -> None:
    hostile = SceneModule(
        scene_id="intro",
        builder='const text = "</script><script>alert(1)</script>"; const open = "<!--";\nctx.root.append(text);',
    )
    case = CASES["minimal"]

    html = compose([hostile, case.modules[1]], case.storyboard, DEFAULT_STYLE_TOKENS)

    assert html.count("</script>") == 3
    assert "<\\/script><script>alert(1)<\\/script>" in html
    assert "<\\!--" in html
    assert sanitize_composition(html, scene_ids=["intro", "outro"]).findings == ()


def test_css_cannot_close_the_style_element() -> None:
    hostile = SceneModule(scene_id="intro", builder="return 1;", css=".mo-s-intro::after { content: '</style><b>'; }")
    case = CASES["minimal"]

    html = compose([hostile, case.modules[1]], case.storyboard, DEFAULT_STYLE_TOKENS)

    assert "</style><b>" not in html
    assert sanitize_composition(html, scene_ids=["intro", "outro"]).findings == ()


def test_windows_line_endings_are_normalised() -> None:
    case = CASES["minimal"]
    crlf = SceneModule(
        scene_id="intro", builder="const a = 1;\r\nconst b = 2;\r\n", css=".mo-s-intro {\r\n  color: red;\r\n}\r\n"
    )

    html = compose([crlf, case.modules[1]], case.storyboard, DEFAULT_STYLE_TOKENS)

    assert "\r" not in html


def test_a_missing_module_is_a_compose_error() -> None:
    case = CASES["minimal"]

    with pytest.raises(ComposeError, match="No module for scene outro"):
        compose(case.modules[:1], case.storyboard, DEFAULT_STYLE_TOKENS)


def test_an_extra_module_is_a_compose_error() -> None:
    case = CASES["minimal"]
    extra = SceneModule(scene_id="bonus", builder="return 1;")

    with pytest.raises(ComposeError, match="not in the storyboard: bonus"):
        compose([*case.modules, extra], case.storyboard, DEFAULT_STYLE_TOKENS)


def test_a_duplicate_module_is_a_compose_error() -> None:
    case = CASES["minimal"]

    with pytest.raises(ComposeError, match="more than one module"):
        compose([*case.modules, case.modules[0]], case.storyboard, DEFAULT_STYLE_TOKENS)


def test_an_unsafe_asset_is_a_compose_error() -> None:
    case = CASES["minimal"]
    unsafe = SceneModule(
        scene_id="intro",
        builder="return 1;",
        assets=[SceneAsset(id="art", svg="<svg></svg><script>alert(1)</script>")],
    )

    with pytest.raises(ComposeError, match="not a safe SVG"):
        compose([unsafe, case.modules[1]], case.storyboard, DEFAULT_STYLE_TOKENS)


def test_a_scene_without_css_gets_no_style_element() -> None:
    html = composed(CASES["minimal"])

    assert html.count("data-mo-scene-style") == 1
