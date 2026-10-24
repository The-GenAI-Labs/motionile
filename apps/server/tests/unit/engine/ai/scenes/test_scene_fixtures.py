import json
import re

import pytest
from tests.scene_support import (
    MINIMUM_NARRATION_WORDS,
    SCENE_FIXTURES,
    SCENE_ID_PLACEHOLDER,
    load_scene_fixture,
    scene_fixture_text,
)

from motionile.engine.ai.scenes.models import SceneModule, StaticFindingCode
from motionile.engine.ai.scenes.static_checks import check_scene_module

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
BROKEN_FIXTURES = {
    "broken-syntax": {StaticFindingCode.BUILDER_SYNTAX},
    "broken-unscoped-css": {StaticFindingCode.CSS_UNSCOPED},
    "broken-forbidden-api": {StaticFindingCode.BUILDER_FORBIDDEN_SYNTAX},
}
SANDBOX_ONLY_FIXTURES = ("broken-overflow", "broken-contrast")
MAX_FIXTURE_MINIMUM_WORDS = 10


def test_the_fixture_directory_holds_exactly_the_documented_fixtures() -> None:
    names = {path.stem for path in SCENE_FIXTURES.glob("*.json")}

    assert names == {*GOOD_FIXTURES, *BROKEN_FIXTURES, *SANDBOX_ONLY_FIXTURES}


@pytest.mark.parametrize("name", [*GOOD_FIXTURES, *BROKEN_FIXTURES, *SANDBOX_ONLY_FIXTURES])
def test_a_fixture_is_the_camel_case_wire_form_of_a_scene_module_with_a_placeholder(name: str) -> None:
    raw = json.loads(scene_fixture_text(name))

    assert set(raw) == {"version", "sceneId", "builder", "css", "assets"}
    assert raw["sceneId"] == SCENE_ID_PLACEHOLDER
    assert SCENE_ID_PLACEHOLDER in raw["css"]
    assert SceneModule.model_validate_json(scene_fixture_text(name).replace(SCENE_ID_PLACEHOLDER, "demo"))


@pytest.mark.parametrize("name", GOOD_FIXTURES)
@pytest.mark.parametrize("scene_id", ["demo", "scene-two", "a"])
def test_good_fixtures_pass_the_static_checks_for_any_scene_id(name: str, scene_id: str) -> None:
    module = load_scene_fixture(name, scene_id)

    assert module.scene_id == scene_id
    assert check_scene_module(module) == []


@pytest.mark.parametrize("name", GOOD_FIXTURES)
def test_good_fixtures_are_narration_independent(name: str) -> None:
    builder = load_scene_fixture(name, "demo").builder

    assert "ctx.words" in builder
    assert "ctx.at(" in builder
    assert 'ctx.at("' not in builder
    assert "ctx.at('" not in builder
    assert "ctx.end(" not in builder
    assert "__narration" not in builder


@pytest.mark.parametrize("name", GOOD_FIXTURES)
def test_good_fixtures_use_only_tokens_for_colour(name: str) -> None:
    css = load_scene_fixture(name, "demo").css

    assert "#" not in css.replace("url(#", "")
    assert "rgb(" not in css


@pytest.mark.parametrize("name", GOOD_FIXTURES)
def test_good_fixtures_prefix_their_keyframes_with_the_scene_root(name: str) -> None:
    css = load_scene_fixture(name, "demo").css

    for keyframes in re.findall(r"@keyframes\s+([^\s{]+)", css):
        assert keyframes.startswith("mo-s-demo-")


@pytest.mark.parametrize(("name", "codes"), list(BROKEN_FIXTURES.items()))
def test_broken_fixtures_fail_the_static_checks_for_exactly_one_reason(
    name: str, codes: set[StaticFindingCode]
) -> None:
    findings = check_scene_module(load_scene_fixture(name, "demo"))

    assert {finding.code for finding in findings} == codes


@pytest.mark.parametrize("name", SANDBOX_ONLY_FIXTURES)
def test_overflow_and_contrast_fixtures_are_clean_for_the_static_checks(name: str) -> None:
    assert check_scene_module(load_scene_fixture(name, "demo")) == []


def test_the_forbidden_api_fixture_names_each_forbidden_identifier() -> None:
    findings = check_scene_module(load_scene_fixture("broken-forbidden-api", "demo"))

    assert {finding.detail for finding in findings} == {"window", "Date", "fetch"}


def test_the_syntax_fixture_reports_line_numbers() -> None:
    findings = check_scene_module(load_scene_fixture("broken-syntax", "demo"))

    assert all(finding.line is not None and finding.line >= 1 for finding in findings)


def test_the_unscoped_fixture_names_the_offending_selectors() -> None:
    findings = check_scene_module(load_scene_fixture("broken-unscoped-css", "demo"))

    assert {finding.detail for finding in findings} == {"body", ".mo-b-line"}


def test_documented_minimum_narration_lengths_stay_within_ten_words() -> None:
    assert set(MINIMUM_NARRATION_WORDS) == set(GOOD_FIXTURES)
    assert max(MINIMUM_NARRATION_WORDS.values()) <= MAX_FIXTURE_MINIMUM_WORDS
