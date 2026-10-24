import re
from collections.abc import Iterator
from dataclasses import dataclass

from tree_sitter import Node

from motionile.engine.ai.scenes.js_analysis import (
    FreeReference,
    ParsedBuilder,
    analyze_references,
    line_of,
    text_of,
    walk,
)
from motionile.engine.ai.scenes.models import StaticFinding, StaticFindingCode

ALLOWED_GLOBALS = frozenset(
    {
        "ctx",
        "gsap",
        "Math",
        "Array",
        "Object",
        "Number",
        "String",
        "Boolean",
        "JSON",
        "Set",
        "Map",
        "Symbol",
        "Infinity",
        "NaN",
        "undefined",
        "document",
        "parseInt",
        "parseFloat",
        "isNaN",
        "isFinite",
        "RegExp",
        "Error",
    }
)
FORBIDDEN_GLOBALS = frozenset(
    {
        "window",
        "globalThis",
        "self",
        "top",
        "parent",
        "frames",
        "navigator",
        "location",
        "history",
        "fetch",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "Worker",
        "SharedWorker",
        "WebAssembly",
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "caches",
        "postMessage",
        "BroadcastChannel",
        "MessageChannel",
        "setTimeout",
        "setInterval",
        "setImmediate",
        "clearTimeout",
        "clearInterval",
        "requestAnimationFrame",
        "cancelAnimationFrame",
        "requestIdleCallback",
        "queueMicrotask",
        "Date",
        "performance",
        "eval",
        "Function",
        "require",
        "process",
        "module",
        "exports",
    }
)
DOCUMENT_METHODS = frozenset(
    {
        "createElement",
        "createElementNS",
        "createTextNode",
        "createDocumentFragment",
        "querySelector",
        "querySelectorAll",
        "getElementById",
    }
)
GUARDED_COMPUTED_OBJECTS = frozenset(
    {
        "document",
        "ctx",
        "Math",
        "Object",
        "gsap",
        "JSON",
        "Array",
        "Number",
        "String",
        "Boolean",
        "Set",
        "Map",
        "Symbol",
    }
)
FORBIDDEN_PROPERTIES = {
    "constructor": "reaches the Function constructor",
    "__proto__": "reaches the prototype chain",
    "__defineGetter__": "reaches the prototype chain",
    "__defineSetter__": "reaches the prototype chain",
    "__lookupGetter__": "reaches the prototype chain",
    "__lookupSetter__": "reaches the prototype chain",
    "ownerDocument": "reaches the document",
    "defaultView": "reaches the window",
    "contentWindow": "reaches the window",
    "contentDocument": "reaches the document",
    "getRootNode": "reaches the document",
    "cookie": "reads or writes cookies",
    "random": "is not deterministic; derive values from ctx",
    "ticker": "drives animation outside the scene timeline",
    "delayedCall": "drives animation outside the scene timeline",
    "insertAdjacentHTML": "injects markup",
}
HTML_SINK_PROPERTIES = frozenset({"innerHTML", "outerHTML", "srcdoc"})
FORBIDDEN_NODE_TYPES = {
    "await": "await",
    "async": "async functions",
    "yield": "yield",
    "with": "with statements",
    "import": "import",
    "export": "export",
    "this": "this",
}
FORBIDDEN_ELEMENTS = frozenset(
    {"script", "iframe", "object", "embed", "link", "meta", "base", "form", "video", "audio", "foreignobject", "style"}
)
ASSIGNMENT_TYPES = frozenset({"assignment_expression", "augmented_assignment_expression"})
ATTRIBUTE_SETTERS = {"setAttribute": 0, "setAttributeNS": 1}
ELEMENT_FACTORIES = {"createElement": 0, "createElementNS": 1}
HTML_COMMENT_OPEN = "<!--"
HTML_COMMENT_CLOSE = re.compile(r"^\s*-->")
SNIPPET_CHARS = 60


@dataclass(frozen=True, slots=True)
class BuilderContext:
    parsed: ParsedBuilder
    guarded_ids: frozenset[int]


def builder_finding(code: StaticFindingCode, message: str, line: int, detail: str) -> StaticFinding:
    return StaticFinding(code=code, message=message, line=line, detail=detail)


def forbidden(message: str, line: int, detail: str) -> StaticFinding:
    return builder_finding(StaticFindingCode.BUILDER_FORBIDDEN_SYNTAX, message, line, detail)


STRING_TYPES = frozenset({"string", "template_string"})


def has_escape(node: Node | None) -> bool:
    return (
        node is not None
        and node.type in STRING_TYPES
        and any(child.type == "escape_sequence" for child in node.children)
    )


def string_value(node: Node | None) -> str | None:
    if node is None or node.type not in STRING_TYPES or has_escape(node):
        return None
    if any(child.type == "template_substitution" for child in node.children):
        return None
    return "".join(text_of(child) for child in node.children if child.type == "string_fragment")


def is_static_key(node: Node | None) -> bool:
    if node is None:
        return False
    return node.type == "number" or string_value(node) is not None


def reference_findings(reference: FreeReference) -> Iterator[StaticFinding]:
    name = reference.name
    if name == "document":
        yield from document_findings(reference)
    elif name in FORBIDDEN_GLOBALS:
        yield forbidden(f"`{name}` is not available inside a scene builder", reference.line, name)
    elif name not in ALLOWED_GLOBALS:
        yield builder_finding(
            StaticFindingCode.BUILDER_IDENTIFIER,
            f"`{name}` is not defined; declare it inside the builder or use ctx, gsap, Math, Array, Object, document",
            reference.line,
            name,
        )


def document_findings(reference: FreeReference) -> Iterator[StaticFinding]:
    parent = reference.node.parent
    if parent is not None and parent.type == "member_expression":
        target = parent.child_by_field_name("object")
        property_node = parent.child_by_field_name("property")
        if target is not None and target.id == reference.node.id and property_node is not None:
            method = text_of(property_node)
            if method in DOCUMENT_METHODS:
                return
            yield forbidden(f"`document.{method}` is not available; use ctx.root", reference.line, f"document.{method}")
            return
    yield forbidden("`document` may only be used to create or query elements", reference.line, "document")


def computed_access_findings(node: Node, context: BuilderContext) -> Iterator[StaticFinding]:
    target = node.child_by_field_name("object")
    index = node.child_by_field_name("index")
    if has_escape(index):
        yield forbidden("Escaped property names are not allowed", line_of(node), "escape")
        return
    literal = string_value(index)
    if literal is not None:
        yield from property_findings(literal, node)
        return
    if is_static_key(index):
        return
    if target is not None and target.type == "identifier" and target.id in context.guarded_ids:
        name = text_of(target)
        if name in GUARDED_COMPUTED_OBJECTS:
            yield forbidden(f"Computed property access on `{name}` is not allowed", line_of(node), name)


def is_assignment_target(node: Node) -> bool:
    parent = node.parent
    if parent is None or parent.type not in ASSIGNMENT_TYPES:
        return False
    left = parent.child_by_field_name("left")
    return left is not None and left.id == node.id


def property_findings(name: str, node: Node) -> Iterator[StaticFinding]:
    reason = FORBIDDEN_PROPERTIES.get(name)
    if reason is not None:
        yield forbidden(f"`.{name}` {reason}", line_of(node), name)
    elif name in HTML_SINK_PROPERTIES and is_assignment_target(node):
        yield forbidden(
            f"Assigning `.{name}` injects markup; build elements with document.createElement", line_of(node), name
        )


def member_findings(node: Node) -> Iterator[StaticFinding]:
    property_node = node.child_by_field_name("property")
    if property_node is not None:
        yield from property_findings(text_of(property_node), node)


def pattern_findings(node: Node) -> Iterator[StaticFinding]:
    if node.type == "shorthand_property_identifier_pattern":
        name = text_of(node)
    else:
        key = node.child_by_field_name("key")
        name = text_of(key) if key is not None else ""
    if name in FORBIDDEN_PROPERTIES:
        yield forbidden(f"Destructuring `{name}` {FORBIDDEN_PROPERTIES[name]}", line_of(node), name)


def call_literal(node: Node, position: int) -> str | None:
    arguments = node.child_by_field_name("arguments")
    if arguments is None or arguments.type != "arguments":
        return None
    items = arguments.named_children
    return string_value(items[position]) if position < len(items) else None


def call_findings(node: Node) -> Iterator[StaticFinding]:
    function = node.child_by_field_name("function")
    if function is None or function.type != "member_expression":
        return
    property_node = function.child_by_field_name("property")
    if property_node is None:
        return
    method = text_of(property_node)
    if method in ATTRIBUTE_SETTERS:
        attribute = call_literal(node, ATTRIBUTE_SETTERS[method])
        if attribute is not None and (attribute.lower().startswith("on") or attribute.lower() == "srcdoc"):
            yield forbidden(f"Setting the `{attribute}` attribute is not allowed", line_of(node), attribute)
    elif method in ELEMENT_FACTORIES:
        tag = call_literal(node, ELEMENT_FACTORIES[method])
        if tag is not None and tag.lower() in FORBIDDEN_ELEMENTS:
            yield forbidden(f"Creating a `{tag}` element is not allowed", line_of(node), tag)


def node_findings(node: Node, context: BuilderContext) -> Iterator[StaticFinding]:
    node_type = node.type
    if node_type in FORBIDDEN_NODE_TYPES:
        yield forbidden(f"`{node_type}` is not allowed in a scene builder", line_of(node), node_type)
    elif node_type == "member_expression":
        yield from member_findings(node)
    elif node_type == "subscript_expression":
        yield from computed_access_findings(node, context)
    elif node_type in {"shorthand_property_identifier_pattern", "pair_pattern"}:
        yield from pattern_findings(node)
    elif node_type == "call_expression":
        yield from call_findings(node)


def comment_marker_findings(lines: tuple[str, ...]) -> Iterator[StaticFinding]:
    for index, text in enumerate(lines[1:-2], start=1):
        if HTML_COMMENT_OPEN in text or HTML_COMMENT_CLOSE.match(text):
            snippet = text.strip()[:SNIPPET_CHARS]
            yield forbidden("HTML comment markers are not allowed in a scene builder", index, snippet)


def syntax_findings(parsed: ParsedBuilder) -> list[StaticFinding]:
    return [
        builder_finding(StaticFindingCode.BUILDER_SYNTAX, problem.message, problem.line, "syntax")
        for problem in parsed.problems
    ]


def policy_findings(parsed: ParsedBuilder) -> list[StaticFinding]:
    body = parsed.body
    if body is None:
        return []
    analysis = analyze_references(parsed)
    guarded_ids = frozenset(reference.node.id for reference in analysis.free) | analysis.context_ids
    context = BuilderContext(parsed, guarded_ids)
    findings: list[StaticFinding] = []
    for reference in analysis.free:
        findings.extend(reference_findings(reference))
    for node in walk(body):
        findings.extend(node_findings(node, context))
    findings.extend(comment_marker_findings(parsed.lines))
    return findings


def check_builder(parsed: ParsedBuilder) -> list[StaticFinding]:
    findings = syntax_findings(parsed) if parsed.problems else policy_findings(parsed)
    unique = {(item.code.value, item.line, item.detail, item.message): item for item in findings}
    return [unique[key] for key in sorted(unique, key=sort_key)]


def sort_key(key: tuple[str, int | None, str | None, str]) -> tuple[int, str, str, str]:
    code, line, detail, message = key
    return (line or 0, code, detail or "", message)
