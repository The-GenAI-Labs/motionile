import re

import pytest

from motionile.engine.ai.scenes.fallback import (
    FALLBACK_BUILDER,
    MAX_CHARS_PER_PAGE,
    MAX_WORDS_PER_PAGE,
    fallback_module,
)
from motionile.engine.ai.scenes.models import SCENE_ROOT_CLASS_PREFIX
from motionile.engine.ai.scenes.static_checks import check_scene_module

TOKEN_REFERENCE = re.compile(r"var\((--[a-z-]+)\)")
RAW_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(")
KNOWN_TOKENS = {"--mo-text", "--mo-text-title", "--mo-text-subtitle"}


@pytest.mark.parametrize("scene_id", ["intro", "a", "scene-with-dashes-1", "x" * 32])
def test_the_fallback_passes_the_static_checks_for_any_scene_id(scene_id: str) -> None:
    module = fallback_module(scene_id)

    assert module.scene_id == scene_id
    assert module.root_class == f"{SCENE_ROOT_CLASS_PREFIX}{scene_id}"
    assert check_scene_module(module) == []


def test_the_fallback_is_deterministic_and_independent_of_narration() -> None:
    assert fallback_module("intro").builder == fallback_module("outro").builder
    assert fallback_module("intro") == fallback_module("intro")
    assert fallback_module("intro").assets == []


def test_the_fallback_css_is_scoped_to_its_scene_and_uses_only_tokens() -> None:
    css = fallback_module("intro").css

    assert set(TOKEN_REFERENCE.findall(css)) == KNOWN_TOKENS
    assert RAW_COLOR.search(css) is None
    assert "__ROOT__" not in css
    assert set(re.findall(r"^(\.[^\s{,]+)", css, flags=re.MULTILINE)) == {".mo-s-intro"}


def test_the_window_is_bounded_to_twelve_words() -> None:
    assert MAX_WORDS_PER_PAGE == 12
    assert f"const MAX_WORDS = {MAX_WORDS_PER_PAGE};" in FALLBACK_BUILDER
    assert f"const MAX_CHARS = {MAX_CHARS_PER_PAGE};" in FALLBACK_BUILDER


def test_the_fallback_advances_with_the_narration_clock_and_stays_inside_the_scene() -> None:
    builder = FALLBACK_BUILDER

    assert "ctx.at(word.index)" in builder
    assert "ctx.at(page.words[0].index)" in builder
    assert "ctx.duration" in builder
    assert "ctx.words" in builder
    assert "ctx.text" not in builder
    assert "setTimeout" not in builder
    assert "Math.random" not in builder
