import base64
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from motionile.engine.render.models import InvalidCompositionError
from motionile.engine.render.sanitize import (
    MAX_DATA_URI_BYTES,
    MAX_ELEMENTS,
    MAX_HTML_BYTES,
    sanitize_composition,
)
from motionile.engine.render.sanitize_script import count_composition_calls, screen_script
from motionile.engine.render.sanitize_urls import check_url, is_runtime_url, split_srcset

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
SANITIZER_FIXTURES = FIXTURES / "sanitizer"
COMPOSITION_FIXTURES = FIXTURES / "compositions"
EXPECTATIONS = json.loads((SANITIZER_FIXTURES / "expectations.json").read_text(encoding="utf-8"))

SHELL = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8"><title>t</title>'
    '<link rel="stylesheet" href="https://runtime.motionile.local/v1/base.css">'
    "</head><body><main>{body}</main><script>{script}</script></body></html>"
)


def shell(body: str = "", script: str = "") -> str:
    return SHELL.format(body=body, script=script)


def error_codes(html: str, scene_ids: Sequence[str] | None = None) -> set[str]:
    result = sanitize_composition(html, scene_ids=scene_ids)
    return {finding.code for finding in result.errors}


def test_every_fixture_has_an_expectation_and_every_expectation_a_fixture() -> None:
    files = {path.name for path in SANITIZER_FIXTURES.glob("*.html")}

    assert files == set(EXPECTATIONS)


@pytest.mark.parametrize("name", sorted(EXPECTATIONS))
def test_fixture_is_rejected_with_its_code_and_stripped_from_the_output(name: str) -> None:
    expectation = EXPECTATIONS[name]
    html = (SANITIZER_FIXTURES / name).read_text(encoding="utf-8")

    result = sanitize_composition(html)

    assert expectation["code"] in {finding.code for finding in result.errors}
    assert not result.valid
    lowered = result.html.lower()
    for needle in expectation["absent"]:
        assert needle.lower() not in lowered, f"{needle!r} survived in the cleaned document"


@pytest.mark.parametrize("name", sorted(EXPECTATIONS))
def test_cleaned_output_is_a_fixed_point(name: str) -> None:
    html = (SANITIZER_FIXTURES / name).read_text(encoding="utf-8")
    first = sanitize_composition(html)

    second = sanitize_composition(first.html)

    removable_codes = {"forbidden_element", "forbidden_attribute", "forbidden_url", "invalid_data_uri"}
    assert not [finding for finding in second.errors if finding.code in removable_codes]
    assert second.html == first.html


@pytest.mark.parametrize("path", sorted(COMPOSITION_FIXTURES.glob("*/composition.html")), ids=lambda p: p.parent.name)
def test_golden_compositions_pass_without_errors_or_findings(path: Path) -> None:
    narration = json.loads((path.parent / "narration.json").read_text(encoding="utf-8"))
    scene_ids = [scene["sceneId"] for scene in narration["scenes"]]

    result = sanitize_composition(path.read_text(encoding="utf-8"), scene_ids=scene_ids)

    assert result.errors == ()
    assert result.findings == ()
    assert result.composition_calls == 1
    assert list(result.scene_ids) == scene_ids
    assert result.html.startswith("<!DOCTYPE html>")


def test_a_clean_document_keeps_its_scripts_styles_and_text() -> None:
    html = shell(
        body='<section data-scene="a"><h1 id="t">Hi &amp; bye</h1></section>',
        script='Motionile.composition({aspects: ["16:9"], scenes: []});',
    )

    result = sanitize_composition(html)

    assert result.valid
    assert "Hi &amp; bye" in result.html
    assert 'data-scene="a"' in result.html
    assert 'Motionile.composition({aspects: ["16:9"], scenes: []});' in result.html


def test_stripped_elements_keep_the_surrounding_text() -> None:
    html = shell(body="<p>before<iframe src='https://evil.test'></iframe>after<!-- note --> end</p>")

    cleaned = sanitize_composition(html).html

    assert "beforeafter end" in cleaned
    assert "note" not in cleaned


def test_findings_carry_selector_and_detail() -> None:
    result = sanitize_composition(shell(body='<div id="card"><img src="https://evil.test/a.png"></div>'))

    finding = next(item for item in result.errors if item.code == "forbidden_url")

    assert finding.kind == "sanitize"
    assert finding.severity == "error"
    assert finding.selector is not None
    assert finding.selector.endswith("div#card > img")
    assert finding.detail["url"] == "https://evil.test/a.png"


def test_raise_for_errors_raises_invalid_composition() -> None:
    result = sanitize_composition(shell(body="<iframe></iframe>"))

    with pytest.raises(InvalidCompositionError) as raised:
        result.raise_for_errors()

    assert raised.value.code == "invalid_composition"
    assert {issue.code for issue in raised.value.issues} == {"forbidden_element"}


def test_html_larger_than_the_limit_is_rejected_without_output() -> None:
    result = sanitize_composition(shell(body="x" * (MAX_HTML_BYTES + 1)))

    assert [finding.code for finding in result.errors] == ["html_too_large"]
    assert result.html == ""


def test_more_than_the_maximum_elements_is_rejected() -> None:
    result = sanitize_composition(shell(body="<i></i>" * (MAX_ELEMENTS + 10)))

    assert [finding.code for finding in result.errors] == ["too_many_elements"]
    assert result.html == ""


def test_the_element_limit_is_inclusive_of_the_exact_count() -> None:
    result = sanitize_composition(shell(body="<i></i>" * 100))

    assert result.valid


def test_data_uris_over_the_total_limit_are_rejected() -> None:
    payload = base64.b64encode(b"a" * 300_000).decode()
    uri = f"data:image/png;base64,{payload}"
    body = "".join(f'<img src="{uri}" alt="">' for _ in range(MAX_DATA_URI_BYTES // len(uri) + 2))

    result = sanitize_composition(shell(body=body))

    assert [finding.code for finding in result.errors] == ["data_uris_too_large"]


def test_data_uris_do_not_count_towards_the_markup_limit() -> None:
    payload = base64.b64encode(b"a" * 300_000).decode()
    body = "".join(f'<img src="data:image/png;base64,{payload}" alt="">' for _ in range(2))

    assert sanitize_composition(shell(body=body)).valid


def test_valid_base64_data_images_and_fonts_are_allowed() -> None:
    png = base64.b64encode(b"png-bytes").decode()
    font = base64.b64encode(b"font-bytes").decode()
    html = shell(
        body=f'<img src="data:image/png;base64,{png}" alt="">',
    ).replace(
        "</head>", f"<style>@font-face {{ font-family: X; src: url(data:font/woff2;base64,{font}); }}</style></head>"
    )

    assert sanitize_composition(html).valid


def test_percent_encoded_svg_data_images_are_allowed() -> None:
    uri = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'%3E%3C/svg%3E"

    assert sanitize_composition(shell(body=f'<img src="{uri}" alt="">')).valid


def test_scene_ids_match_in_order() -> None:
    html = shell(body='<section data-scene="a"></section><section data-scene="b"></section>')

    assert sanitize_composition(html, scene_ids=["a", "b"]).valid


def test_scene_element_missing_and_mismatch_are_reported() -> None:
    html = shell(body='<section data-scene="a"></section><section data-scene="c"></section>')

    result = sanitize_composition(html, scene_ids=["a", "b"])

    assert {finding.code for finding in result.errors} == {"scene_element_missing", "scene_mismatch"}


def test_scene_order_mismatch_is_reported() -> None:
    html = shell(body='<section data-scene="b"></section><section data-scene="a"></section>')

    result = sanitize_composition(html, scene_ids=["a", "b"])

    assert [finding.code for finding in result.errors] == ["scene_mismatch"]


def test_duplicate_scene_elements_are_a_mismatch() -> None:
    html = shell(body='<section data-scene="a"></section><section data-scene="a"></section>')

    assert error_codes(html, scene_ids=["a"]) == {"scene_mismatch"}


def test_scene_ids_are_not_checked_when_not_given() -> None:
    assert sanitize_composition(shell(body='<section data-scene="x"></section>')).valid


def test_two_composition_calls_are_an_error_but_one_in_a_string_is_not() -> None:
    twice = shell(script="Motionile.composition({}); Motionile.composition({});")
    once_with_noise = shell(
        script='const note = "Motionile.composition("; Motionile.composition({}); // Motionile.composition('
    )

    assert error_codes(twice) == {"composition_multiple"}
    assert sanitize_composition(once_with_noise).composition_calls == 1


def test_script_screen_reports_warnings_only() -> None:
    result = sanitize_composition(shell(script='fetch("x"); new WebSocket("y"); eval("1"); window["lo"+"cation"];'))

    apis = {str(finding.detail["api"]) for finding in result.findings if finding.code == "script_api"}

    assert result.valid
    assert {"fetch", "WebSocket", "eval", "computed window access"} <= apis
    assert all(finding.severity == "warning" for finding in result.findings)


def test_parse_errors_are_warnings() -> None:
    result = sanitize_composition("<p>unclosed <b>markup</i>")

    assert result.valid
    assert any(finding.code == "parse_error" and finding.severity == "warning" for finding in result.findings)


def test_report_wraps_findings() -> None:
    result = sanitize_composition(shell(body="<iframe></iframe>", script="fetch('x')"))

    report = result.report()

    assert not report.valid
    assert {issue.code for issue in report.issues} == {"forbidden_element", "script_api"}


def test_foreign_attributes_survive_serialization() -> None:
    html = shell(body='<svg viewBox="0 0 1 1"><use xlink:href="#a"></use></svg>')

    cleaned = sanitize_composition(html).html

    assert 'xlink:href="#a"' in cleaned
    assert 'viewBox="0 0 1 1"' in cleaned


def test_attribute_values_are_escaped_so_markup_cannot_break_out() -> None:
    html = shell(body='<p title="&quot;&gt;&lt;img src=x&gt;">text</p>')

    cleaned = sanitize_composition(html).html

    assert "<img" not in cleaned
    assert "&lt;img" in cleaned


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://runtime.motionile.local/v1/base.css", True),
        ("/v1/base.css", True),
        ("#fragment", True),
        ("", True),
        ("data:image/png;base64,AAAA", True),
        ("https://runtime.motionile.local/v1/../x", False),
        ("https://runtime.motionile.local/v1/%2e%2e/x", False),
        ("https://runtime.motionile.local:444/v1/x", False),
        ("http://runtime.motionile.local/v1/x", False),
        ("//evil.test/v1/x", False),
        ("javascript:alert(1)", False),
        ("JaVaScRiPt:alert(1)", False),
        ("java\tscript:alert(1)", False),
        (" \x01javascript:alert(1)", False),
        ("vbscript:x", False),
        ("blob:https://runtime.motionile.local/abc", False),
        ("data:text/html,<b>", False),
        ("https://[::1", False),
    ],
)
def test_check_url_policy(url: str, allowed: bool) -> None:
    assert check_url(url).allowed is allowed


def test_is_runtime_url_excludes_data_and_fragments() -> None:
    assert is_runtime_url("https://runtime.motionile.local/v1/base.css")
    assert not is_runtime_url("data:image/png;base64,AAAA")
    assert not is_runtime_url("#a")


def test_srcset_parsing_keeps_commas_inside_data_urls() -> None:
    value = "data:image/png;base64,AAAA 1x, https://runtime.motionile.local/v1/a.png 2x"

    assert split_srcset(value) == ["data:image/png;base64,AAAA", "https://runtime.motionile.local/v1/a.png"]


def test_script_screen_ignores_strings_and_comments() -> None:
    source = 'const text = "fetch(1)"; // fetch(2)\n/* XMLHttpRequest */ const ok = 1;'

    assert screen_script(source) == []
    assert count_composition_calls("Motionile . composition ( {} )") == 1
