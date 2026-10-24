from uuid import uuid4

import pytest

from motionile.engine.ai.ports import ActivePrompt
from motionile.engine.ai.prompts import PromptRenderError, render_active, render_prompt


def test_renders_declared_variables_and_the_canary() -> None:
    rendered = render_prompt("Topic: {{ topic }}. Marker {{ canary }}.\n", {"topic": "tides"}, "mo-canary-abc")

    assert rendered == "Topic: tides. Marker mo-canary-abc.\n"


def test_keeps_the_trailing_newline() -> None:
    assert render_prompt("{{ canary }}\n", {}, "c").endswith("\n")
    assert not render_prompt("{{ canary }}", {}, "c").endswith("\n")


def test_unknown_variables_are_rejected() -> None:
    with pytest.raises(PromptRenderError, match="unknown variables: extra"):
        render_prompt("{{ canary }}", {"extra": "value"}, "c")


def test_missing_variables_are_rejected() -> None:
    with pytest.raises(PromptRenderError, match="missing variables: topic"):
        render_prompt("{{ topic }} {{ canary }}", {}, "c")


def test_the_canary_cannot_be_passed_as_a_variable() -> None:
    with pytest.raises(PromptRenderError, match="canary"):
        render_prompt("{{ canary }}", {"canary": "x"}, "c")


def test_values_are_never_rendered_as_templates() -> None:
    hostile = "{{ canary }} {% for item in range(3) %}x{% endfor %} {{ ''.__class__ }}"

    rendered = render_prompt("{{ query }} | {{ canary }}", {"query": hostile}, "mo-canary-real")

    assert rendered == f"{hostile} | mo-canary-real"


def test_the_sandbox_blocks_unsafe_attribute_access_in_templates() -> None:
    with pytest.raises(PromptRenderError):
        render_prompt("{{ canary.__class__.__mro__ }}", {}, "c")


def test_the_sandbox_blocks_calling_unsafe_callables() -> None:
    with pytest.raises(PromptRenderError):
        render_prompt("{{ canary.format.__globals__ }}", {}, "c")


def test_there_is_no_loader_for_includes() -> None:
    with pytest.raises(PromptRenderError):
        render_prompt("{% include 'secrets.txt' %}{{ canary }}", {}, "c")


def test_syntax_errors_are_typed() -> None:
    with pytest.raises(PromptRenderError, match="invalid"):
        render_prompt("{% if %}{{ canary }}", {}, "c")


def test_no_autoescape() -> None:
    assert render_prompt("{{ text }}{{ canary }}", {"text": "<b>&</b>"}, "c") == "<b>&</b>c"


def test_render_active_uses_the_stored_canary() -> None:
    prompt = ActivePrompt(
        key="k.v",
        version_id=uuid4(),
        version=1,
        body="Marker {{ canary }}; {{ extra }}\n",
        canary="mo-canary-stored",
        variables=("canary", "extra"),
    )

    assert render_active(prompt, {"extra": "e"}) == "Marker mo-canary-stored; e\n"
