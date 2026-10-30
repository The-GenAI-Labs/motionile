import pytest

from motionile.engine.ai.scenes.css_scope import check_css
from motionile.engine.ai.scenes.models import StaticFinding, StaticFindingCode

UNSCOPED = StaticFindingCode.CSS_UNSCOPED
FORBIDDEN = StaticFindingCode.CSS_FORBIDDEN
SYNTAX = StaticFindingCode.CSS_SYNTAX


def codes(css: str) -> list[StaticFindingCode]:
    return [finding.code for finding in check_css(css, "x")]


def findings(css: str) -> list[StaticFinding]:
    return check_css(css, "x")


SCOPED_CSS = [
    "",
    ".mo-s-x { display: flex; }",
    ".mo-s-x .a { color: var(--mo-text); }",
    ".mo-s-x > .a { color: red; }",
    ".mo-s-x.mo-center { text-align: center; }",
    ".mo-center.mo-s-x { text-align: center; }",
    ".mo-s-x:hover .a, .mo-s-x .b::after { opacity: 0.5; }",
    ".mo-s-x .a:not(.b) { opacity: 0.5; }",
    "@media (min-width: 10px) { .mo-s-x .a { opacity: 1; } }",
    "@container stage (aspect-ratio < 1) { .mo-s-x .a { opacity: 1; } }",
    "@supports (display: grid) { .mo-s-x .a { display: grid; } }",
    "@layer base { .mo-s-x .a { opacity: 1; } }",
    "@layer base, theme;",
    "@keyframes mo-s-x-spin { from { transform: rotate(0); } to { transform: rotate(1turn); } }",
    "@-webkit-keyframes mo-s-x-spin { to { opacity: 1; } }",
    ".mo-s-x .a { animation: mo-s-x-spin 1s infinite; }",
    ".mo-s-x .a { background: url(data:image/png;base64,iVBORw0KGgo=); }",
    ".mo-s-x .a { fill: url(#gradient); }",
    ".mo-s-x .a { color: red; .b { color: blue; } }",
    ".mo-s-x { position: absolute; }",
    ".mo-s-x .a { position: relative; }",
    "@charset 'utf-8'; .mo-s-x { display: block; }",
    "/* nothing */ .mo-s-x { display: block; }",
    ".mo-s-x { --size: 3; width: calc(var(--size) * 10px); }",
    ".mo-s-x::before { content: 'Note: this is text'; }",
]


@pytest.mark.parametrize("css", SCOPED_CSS)
def test_scoped_css_has_no_findings(css: str) -> None:
    assert findings(css) == []


@pytest.mark.parametrize(
    "css",
    [
        "html { color: red; }",
        "body { margin: 0; }",
        ":root { --mo-bg: red; }",
        "* { box-sizing: border-box; }",
        ".a { color: red; }",
        ".mo-s-y .a { color: red; }",
        ".mo-s-x-other .a { color: red; }",
        ".mo-s-xx { color: red; }",
        "body .mo-s-x { color: red; }",
        ".a .mo-s-x { color: red; }",
        ".mo-s-x, .a { color: red; }",
        ".mo-s-x .a, body { color: red; }",
        ":is(.mo-s-x, body) { color: red; }",
        ":where(.mo-s-x) .a { color: red; }",
        ".mo-s-x ~ .mo-s-y .a { color: red; }",
        ".mo-s-x + .a { color: red; }",
        "@media (min-width: 10px) { body { color: red; } }",
        "@container stage (aspect-ratio < 1) { .a { color: red; } }",
        "@supports (display: grid) { html { display: grid; } }",
        "@layer base { * { margin: 0; } }",
        "@keyframes spin { to { opacity: 1; } }",
        "@keyframes mo-s-y-spin { to { opacity: 1; } }",
        "@keyframes mo-s-x { to { opacity: 1; } }",
        "@keyframes 'other' { to { opacity: 1; } }",
    ],
)
def test_unscoped_css_is_reported(css: str) -> None:
    assert UNSCOPED in codes(css)


def test_each_unscoped_selector_of_a_list_is_reported_with_its_line() -> None:
    css = ".mo-s-x .ok { color: red; }\n\nbody, .a, .mo-s-x .fine { color: red; }"

    found = findings(css)

    assert [(finding.code, finding.line, finding.detail) for finding in found] == [
        (UNSCOPED, 3, ".a"),
        (UNSCOPED, 3, "body"),
    ]


@pytest.mark.parametrize(
    ("css", "detail"),
    [
        ("@import url('https://evil.example/a.css');", "@import"),
        ("@import 'a.css';", "@import"),
        ("@font-face { font-family: x; src: url(data:font/woff2;base64,AAAA); }", "@font-face"),
        ("@namespace svg url(http://www.w3.org/2000/svg);", "@namespace"),
        ("@property --x { syntax: '<length>'; inherits: false; initial-value: 0px; }", "@property"),
        ("@page { margin: 0; }", "@page"),
        ("@counter-style x { system: cyclic; symbols: 'a'; }", "@counter-style"),
        (".mo-s-x { background: url(https://evil.example/a.png); }", "https://evil.example/a.png"),
        (".mo-s-x { background: url('https://evil.example/a.png'); }", "https://evil.example/a.png"),
        (".mo-s-x { background: url(//evil.example/a.png); }", "//evil.example/a.png"),
        (".mo-s-x { background: url(data:text/html;base64,AAAA); }", "data:text/html;base64,AAAA"),
        (".mo-s-x { background: image-set('https://evil.example/a.png' 1x); }", "https://evil.example/a.png"),
        (".mo-s-x { background: image-set(var(--img) 1x); }", "var()"),
        (".mo-s-x { --img: 'https://evil.example/a.png'; }", "https://evil.example/a.png"),
        (".mo-s-x { cursor: url(https://evil.example/c.cur), auto; }", "https://evil.example/c.cur"),
        (
            "@media (min-width: 1px) { .mo-s-x { background: url(https://evil.example/a.png); } }",
            "https://evil.example/a.png",
        ),
        (".mo-s-x { color: red; .b { background: url(https://evil.example/a.png); } }", "https://evil.example/a.png"),
        ("@keyframes mo-s-x-a { to { background: url(https://evil.example/a.png); } }", "https://evil.example/a.png"),
        (".mo-s-x .a { position: fixed; }", "position"),
        (".mo-s-x { color: red !important; }", "color"),
        (".mo-s-x, .mo-s-x { visibility: visible !important; }", "visibility"),
    ],
)
def test_forbidden_css_is_reported(css: str, detail: str) -> None:
    found = [finding for finding in findings(css) if finding.code is FORBIDDEN]

    assert detail in {finding.detail for finding in found}


def test_an_unquoted_url_with_parentheses_is_a_syntax_error() -> None:
    assert SYNTAX in codes(".mo-s-x { background: url(var(--img)); }")


def test_important_is_allowed_below_the_root_and_fixed_on_the_root() -> None:
    assert findings(".mo-s-x .a { color: red !important; }") == []
    assert findings(".mo-s-x { position: fixed; }") == []


@pytest.mark.parametrize(
    "css",
    [
        ".mo-s-x { color: }}",
        "}",
        ".mo-s-x .a { background: url(; }",
        ".mo-s-x { content: 'unterminated }",
        ".mo-s-x { color red; }",
    ],
)
def test_syntax_errors_are_reported(css: str) -> None:
    assert SYNTAX in codes(css)


def test_findings_are_deterministic() -> None:
    css = "body{color:red}\n@import 'a.css';\nhtml{margin:0}\n.mo-s-x{background:url(http://a/b.png)}"

    assert findings(css) == findings(css)
    assert findings(css) == sorted(
        findings(css), key=lambda item: (item.code.value, item.line or 0, item.detail or "", item.message)
    )
