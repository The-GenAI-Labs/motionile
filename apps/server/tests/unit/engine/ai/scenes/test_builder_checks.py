import time

import pytest

from motionile.engine.ai.scenes.models import SceneModule, StaticFinding, StaticFindingCode
from motionile.engine.ai.scenes.static_checks import check_scene_module

SYNTAX = StaticFindingCode.BUILDER_SYNTAX
IDENTIFIER = StaticFindingCode.BUILDER_IDENTIFIER
FORBIDDEN = StaticFindingCode.BUILDER_FORBIDDEN_SYNTAX
MAX_CHECK_SECONDS = 0.02


def findings_for(builder: str) -> list[StaticFinding]:
    return check_scene_module(SceneModule(scene_id="demo", builder=builder))


def summary(builder: str) -> set[tuple[StaticFindingCode, str | None]]:
    return {(finding.code, finding.detail) for finding in findings_for(builder)}


CLEAN_BUILDERS = [
    "ctx.timeline.from(ctx.root, { opacity: 0 }, ctx.at(0));",
    "const nodes = ctx.words.map((word) => word.text); return nodes;",
    "const { width, height } = ctx.safeArea; const [first, ...rest] = ctx.words;"
    " return width + height + first.index + rest.length;",
    "const { a = 1, b: [c = 2], ...others } = ctx; return a + c + others.id.length;",
    "for (const word of ctx.words) { const text = word.text; ctx.root.append(document.createTextNode(text)); }",
    "for (let index = 0; index < 3; index += 1) { gsap.set(ctx.root, { x: index }); }",
    "for (var index = 0; index < 3; index += 1) {} return index;",
    "for (const key in ctx) { void key; }",
    "try { ctx.at('missing'); } catch (error) { return error.message; }",
    "try { ctx.at('missing'); } catch ({ message }) { return message; }",
    "function helper(value) { return value * 2; } return helper(2);",
    "return helper(2); function helper(value) { return value * 2; }",
    "const make = function named(depth) { return depth > 0 ? named(depth - 1) : 0; }; return make(2);",
    "class Marker { static make(value) { return value; } } return Marker;",
    "const Box = class Inner { static create() { return new Inner(); } }; return Box;",
    "label: for (const word of ctx.words) { if (word.index) { break label; } }",
    "switch (ctx.aspect) { case '16:9': { const wide = true; return wide; } default: return false; }",
    "const total = Math.max(1, Number('2')) + parseInt('3', 10) + parseFloat('1.5'); return total;",
    "const items = new Set(['a']); const lookup = new Map([['a', 1]]); return items.size + lookup.size;",
    "const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');"
    " svg.setAttribute('viewBox', '0 0 1 1'); return svg;",
    "const node = document.querySelector('#x'); const same = document.getElementById('x'); return node ?? same;",
    "const fn = (arguments_) => arguments_; return fn(1);",
    "function legacy() { return arguments.length; } return legacy();",
    "const key = 'x'; const table = { [key]: 1, shorthand: key, key }; return table[key];",
    "const matcher = /[.!?]$/; return matcher.test(ctx.text);",
    "return JSON.stringify(Object.entries({ a: 1 }).map(([name, value]) => name + String(value)));",
    "return undefined ?? Infinity ?? NaN;",
]


@pytest.mark.parametrize("builder", CLEAN_BUILDERS)
def test_clean_builders_have_no_findings(builder: str) -> None:
    assert findings_for(builder) == []


UNDECLARED = [
    ("foo.bar();", "foo"),
    ("const value = undeclared + 1;", "undeclared"),
    ("getComputedStyle(ctx.root);", "getComputedStyle"),
    ("console.log(ctx.text);", "console"),
    ("{ const scoped = 1; } return scoped;", "scoped"),
    ("(() => { const inner = 1; })(); return inner;", "inner"),
    ("for (let i = 0; i < 1; i += 1) {} return i;", "i"),
    ("try {} catch (error) {} return error;", "error"),
    ("const { a } = ctx; return b;", "b"),
    ("unknown = 5;", "unknown"),
    ("const { x = missing } = ctx; return x;", "missing"),
    ("return { shorthand };", "shorthand"),
    ("Intl.NumberFormat('en');", "Intl"),
    ("new Proxy({}, {});", "Proxy"),
    ("structuredClone({});", "structuredClone"),
    ("class A extends Missing {} return A;", "Missing"),
]


@pytest.mark.parametrize(("builder", "name"), UNDECLARED)
def test_undeclared_identifiers_are_reported_with_their_line(builder: str, name: str) -> None:
    found = [finding for finding in findings_for(builder) if finding.detail == name]

    assert len(found) == 1
    assert found[0].code is IDENTIFIER
    assert found[0].line == 1


def test_property_names_after_a_dot_are_not_references() -> None:
    assert findings_for("const el = ctx.root; el.window; el.undeclared; el.parent.fetch;") == []


def test_object_keys_and_method_names_are_not_references() -> None:
    assert findings_for("const o = { fetch: 1, window() { return 1; }, setTimeout: 2 }; return o.fetch;") == []


def test_identifier_findings_report_the_builder_line_number() -> None:
    builder = "const ok = 1;\n\nconst bad = missing;\nreturn ok + bad;"

    finding = findings_for(builder)[0]

    assert (finding.code, finding.line, finding.detail) == (IDENTIFIER, 3, "missing")


FORBIDDEN_CASES = [
    ("await Promise.resolve(1);", "await"),
    ("const run = async () => 1; return run;", "async"),
    ("function* generator() { yield 1; } return generator;", "yield"),
    ("with (ctx) { return text; }", "with"),
    ("import('x');", "import"),
    ("eval('1');", "eval"),
    ("new Function('return 1');", "Function"),
    ("Function('return 1')();", "Function"),
    ("window.open('x');", "window"),
    ("globalThis.fetch('x');", "globalThis"),
    ("self.postMessage(1);", "self"),
    ("top.location = 'x';", "top"),
    ("parent.document;", "parent"),
    ("navigator.sendBeacon('x');", "navigator"),
    ("location.href = 'x';", "location"),
    ("history.back();", "history"),
    ("fetch('x');", "fetch"),
    ("new XMLHttpRequest();", "XMLHttpRequest"),
    ("new WebSocket('x');", "WebSocket"),
    ("new Worker('x');", "Worker"),
    ("localStorage.setItem('a', 'b');", "localStorage"),
    ("sessionStorage.clear();", "sessionStorage"),
    ("indexedDB.open('x');", "indexedDB"),
    ("postMessage(1, '*');", "postMessage"),
    ("setTimeout(() => {}, 1);", "setTimeout"),
    ("setInterval(() => {}, 1);", "setInterval"),
    ("requestAnimationFrame(() => {});", "requestAnimationFrame"),
    ("queueMicrotask(() => {});", "queueMicrotask"),
    ("Date.now();", "Date"),
    ("new Date();", "Date"),
    ("performance.now();", "performance"),
    ("Math.random();", "random"),
    ("Math['random']();", "random"),
    ("gsap.utils.random(0, 1);", "random"),
    ("gsap.ticker.add(() => {});", "ticker"),
    ("gsap.delayedCall(1, () => {});", "delayedCall"),
    ("document.body.append(ctx.root);", "document.body"),
    ("document.write('x');", "document.write"),
    ("document.cookie;", "document.cookie"),
    ("const doc = document; return doc;", "document"),
    ("document[ctx.name]();", "document"),
    ("ctx[ctx.name];", "ctx"),
    ("Math[ctx.name]();", "Math"),
    ("Object[ctx.name]();", "Object"),
    ("ctx.root.innerHTML = '<b>x</b>';", "innerHTML"),
    ("ctx.root.outerHTML = '<b>x</b>';", "outerHTML"),
    ("ctx.root.innerHTML += 'x';", "innerHTML"),
    ("ctx.root.insertAdjacentHTML('beforeend', 'x');", "insertAdjacentHTML"),
    ("const frame = document.createElement('iframe'); frame.srcdoc = 'x';", "iframe"),
    ("document.createElement('script');", "script"),
    ("document.createElementNS('http://www.w3.org/2000/svg', 'foreignObject');", "foreignObject"),
    ("ctx.root.setAttribute('onclick', 'x');", "onclick"),
    ("ctx.root.setAttribute('srcdoc', 'x');", "srcdoc"),
    ("ctx.root.ownerDocument.defaultView;", "ownerDocument"),
    ("ctx.root.constructor.constructor('return 1')();", "constructor"),
    ("ctx['constructor'];", "constructor"),
    ("ctx.root[`constructor`];", "constructor"),
    ("const { constructor } = ctx.root; return constructor;", "constructor"),
    ("const { constructor: make } = ctx.root; return make;", "constructor"),
    ("ctx.root.__proto__.x = 1;", "__proto__"),
    ("ctx['cons\\u0074ructor'];", "escape"),
    ("return this;", "this"),
    ("const a = 1; // <!-- hidden\nreturn a;", "const a = 1; // <!-- hidden"),
    ("const a = 1;\n--> comment\nreturn a;", "--> comment"),
    ("const tag = (parts) => parts; Function`return 1`;", "Function"),
]


@pytest.mark.parametrize(("builder", "detail"), FORBIDDEN_CASES)
def test_forbidden_constructs_are_reported(builder: str, detail: str) -> None:
    found = [finding for finding in findings_for(builder) if finding.code is FORBIDDEN]

    assert detail in {finding.detail for finding in found}


def test_assigning_a_local_named_like_a_forbidden_global_is_allowed() -> None:
    assert findings_for("const window = { width: 1 }; const parent = ctx.root; return window.width + parent.id;") == []


def test_reading_inner_html_is_not_an_assignment() -> None:
    assert findings_for("return ctx.root.innerHTML.length;") == []


def test_dynamic_attribute_names_are_allowed_but_literal_handlers_are_not() -> None:
    allowed = "Object.entries({ a: 1 }).forEach(([key, value]) => ctx.root.setAttribute(key, value));"

    assert findings_for(allowed) == []
    assert summary("ctx.root.setAttribute('onload', 'x');") == {(FORBIDDEN, "onload")}


def test_computed_access_with_literal_keys_is_allowed() -> None:
    assert findings_for("return ctx.words[0].text + ctx['id'] + ctx.words[ctx.words.length - 1].text;") == []


def test_syntax_errors_are_reported_with_line_numbers_and_nothing_else() -> None:
    builder = "const a = 1;\nconst b = ;\nconsole.log(a"

    found = findings_for(builder)

    assert {finding.code for finding in found} == {SYNTAX}
    assert [finding.line for finding in found] == [2, 3]


def test_a_builder_that_closes_its_function_early_is_a_syntax_error() -> None:
    found = findings_for("}\nfetch('x');\nfunction again() {")

    assert [(finding.code, finding.line) for finding in found] == [(SYNTAX, 2)]
    assert "Braces do not balance" in found[0].message


def test_an_unclosed_block_is_a_syntax_error_on_the_last_line() -> None:
    found = findings_for("if (ctx.words.length) {\n  ctx.at(0);")

    assert [finding.code for finding in found] == [SYNTAX]
    assert found[0].line == 2


def test_a_trailing_line_comment_does_not_swallow_the_closing_brace() -> None:
    assert findings_for("const a = 1; // trailing") == []


def test_windows_line_endings_keep_line_numbers() -> None:
    found = findings_for("const a = 1;\r\nconst b = missing;\r\n")

    assert [(finding.code, finding.line) for finding in found] == [(IDENTIFIER, 2)]


def test_findings_are_deterministic_and_sorted_by_line() -> None:
    builder = "fetch('x');\nunknownB();\nunknownA();\nwindow.open();"

    first = findings_for(builder)
    second = findings_for(builder)

    assert first == second
    assert [finding.line for finding in first] == sorted(finding.line or 0 for finding in first)


def test_a_typical_module_is_checked_within_the_time_budget() -> None:
    builder = "\n".join(
        [
            "const total = ctx.words.length;",
            "const nodes = ctx.words.map((word) => {",
            "  const node = document.createElement('span');",
            "  node.textContent = word.text;",
            "  ctx.root.append(node);",
            "  return node;",
            "});",
            *[
                f"nodes.forEach((node, index) => ctx.timeline.from(node, {{ opacity: 0, y: {step} }}, ctx.at(index)));"
                for step in range(40)
            ],
        ]
    )
    result = findings_for(builder)

    durations: list[float] = []
    for _ in range(5):
        started = time.perf_counter()
        result = findings_for(builder)
        durations.append(time.perf_counter() - started)

    assert result == []
    assert min(durations) < MAX_CHECK_SECONDS


def test_a_deeply_nested_builder_does_not_exhaust_the_stack() -> None:
    depth = 3000
    builder = "return " + "(" * depth + "1" + ")" * depth + ";"

    findings_for(builder)
