import pytest

from motionile.engine.ai.scenes.models import SceneAsset, SceneModule, StaticFindingCode
from motionile.engine.ai.scenes.static_checks import check_scene_module
from motionile.engine.ai.scenes.svg_assets import check_svg_asset

VALID_SVGS = [
    '<svg viewBox="0 0 10 10"><rect width="10" height="10"/></svg>',
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4" fill="red"/></svg>',
    '<svg viewBox="0 0 10 10"><defs><linearGradient id="g"><stop offset="0" stop-color="#fff"/></linearGradient></defs>'
    '<rect width="10" height="10" fill="url(#g)"/><use href="#g"/></svg>',
    '<svg viewBox="0 0 10 10" xmlns:xlink="http://www.w3.org/1999/xlink"><use xlink:href="#a"/></svg>',
    '<svg viewBox="0 0 10 10"><use xlink:href="#a"/></svg>',
    '<svg viewBox="0 0 10 10"><style>.a { fill: url(#g); } .b { fill: red; }</style><g class="a"/></svg>',
    '<svg viewBox="0 0 10 10"><rect style="fill: url(#g)" width="1" height="1"/></svg>',
    '<svg viewBox="0 0 10 10"><text x="1" y="5">Hello &amp; welcome</text></svg>',
    '<svg viewBox="0 0 10 10"><path d="M0 0L10 10" stroke="black"/><!-- note --></svg>',
    '  <svg viewBox="0 0 10 10"><g><title>t</title><desc>d</desc></g></svg>  ',
    '<svg viewBox="0 0 10 10"><animate attributeName="opacity" from="0" to="1" dur="1s"/></svg>',
]


def asset_findings(svg: str) -> list[str]:
    return [finding.message for finding in check_svg_asset(SceneAsset(id="art", svg=svg))]


@pytest.mark.parametrize("svg", VALID_SVGS)
def test_valid_svgs_have_no_findings(svg: str) -> None:
    assert check_svg_asset(SceneAsset(id="art", svg=svg)) == []


@pytest.mark.parametrize(
    ("svg", "fragment"),
    [
        ("<svg><script>alert(1)</script></svg>", "<script>"),
        ("<svg><foreignObject><div>x</div></foreignObject></svg>", "<foreignObject>"),
        ('<svg><iframe src="#a"/></svg>', "<iframe>"),
        ('<svg><object data="#a"/></svg>', "<object>"),
        ('<svg><embed src="#a"/></svg>', "<embed>"),
        ('<svg><video src="#a"/></svg>', "<video>"),
        ('<svg><img src="#a"/></svg>', "<img>"),
        ("<svg><g><p>text</p></g></svg>", "<p>"),
        ("<svg><div>text</div></svg>", "<div>"),
        ("<svg><table/></svg>", "<table>"),
        ('<svg onload="alert(1)"/>', "`onload`"),
        ('<svg><rect onclick="alert(1)"/></svg>', "`onclick`"),
        ('<svg><rect onmouseover="x"/></svg>', "`onmouseover`"),
        ('<svg><a href="https://evil.example">x</a></svg>', "`href`"),
        ('<svg><a xlink:href="https://evil.example">x</a></svg>', "`xlink:href`"),
        ('<svg><use href="sprite.svg#a"/></svg>', "`href`"),
        ('<svg><use href="javascript:alert(1)"/></svg>', "`href`"),
        ('<svg><image href="data:image/png;base64,AAAA"/></svg>', "`href`"),
        ("<svg><style>@import url(https://evil.example/a.css);</style></svg>", "@import"),
        ("<svg><style>.a { fill: url(https://evil.example/a.png); }</style></svg>", "external URL"),
        ('<svg><rect style="fill: url(https://evil.example/a.png)"/></svg>', "external URL"),
        ('<svg><rect fill="url(https://evil.example/a.png)"/></svg>', "external URL"),
        ('<svg><rect style="@import url(a.css)"/></svg>', "@import"),
        ('<svg><animate attributeName="href" to="https://evil.example"/></svg>', "may not animate"),
        ('<svg><set attributeName="onclick" to="alert(1)"/></svg>', "may not animate"),
        ('<svg><text title="java script:alert(1)">x</text></svg>', "javascript:"),
        ('<svg><rect srcdoc="x"/></svg>', "`srcdoc`"),
        ("<div><svg/></div>", "root element must be <svg>"),
        ("<svg/><svg/>", "not well-formed"),
        ("<svg><rect></svg>", "not well-formed"),
        ("<svg><rect width=10/></svg>", "not well-formed"),
        ("<svg>&nbsp;</svg>", "not well-formed"),
        ("<svg>", "not well-formed"),
        ("not xml", "not well-formed"),
        ('<?xml version="1.0"?><svg/>', "Processing instructions"),
        ("<svg><?pi data?></svg>", "Processing instructions"),
        ('<!DOCTYPE svg [<!ENTITY a "b">]><svg>&a;</svg>', "DOCTYPE"),
        ('<!DOCTYPE svg SYSTEM "http://evil.example/x.dtd"><svg/>', "DOCTYPE"),
    ],
)
def test_unsafe_or_malformed_svgs_are_reported(svg: str, fragment: str) -> None:
    messages = asset_findings(svg)

    assert messages
    assert any(fragment in message for message in messages)


def test_a_billion_laughs_document_is_rejected_without_expanding() -> None:
    svg = '<!DOCTYPE svg [<!ENTITY a "lol"><!ENTITY b "&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;">]><svg>&c;</svg>'

    assert any("DOCTYPE" in message for message in asset_findings(svg))


def test_findings_name_the_asset_and_the_line() -> None:
    svg = "<svg>\n  <g>\n    <script>1</script>\n  </g>\n</svg>"

    found = check_svg_asset(SceneAsset(id="diagram", svg=svg))

    assert [(item.code, item.line, item.detail) for item in found] == [(StaticFindingCode.ASSET_INVALID, 3, "script")]
    assert "diagram" in found[0].message


def test_findings_are_capped() -> None:
    svg = "<svg>" + "<script/>" * 50 + "</svg>"

    assert len(check_svg_asset(SceneAsset(id="art", svg=svg))) == 10


def test_module_checks_include_every_asset() -> None:
    module = SceneModule(
        scene_id="x",
        builder="return 1;",
        assets=[
            SceneAsset(id="good", svg='<svg viewBox="0 0 1 1"/>'),
            SceneAsset(id="bad", svg="<svg><script/></svg>"),
        ],
    )

    found = check_scene_module(module)

    assert [(item.code, item.detail) for item in found] == [(StaticFindingCode.ASSET_INVALID, "script")]
    assert "bad" in found[0].message
