from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass

import tinycss2
from tinycss2.ast import (
    AtRule,
    Declaration,
    IdentToken,
    LiteralToken,
    Node,
    ParseError,
    QualifiedRule,
    StringToken,
    WhitespaceToken,
)

from motionile.engine.ai.scenes.models import StaticFinding, StaticFindingCode, scene_root_class
from motionile.engine.render.sanitize_css import (
    BAD_MARKER,
    DYNAMIC_MARKER,
    URL_LIKE_STRING,
    iter_strings,
    iter_urls,
    nested_tokens,
)
from motionile.engine.render.sanitize_urls import check_url, normalize_url, snippet

CONDITIONAL_AT_RULES = frozenset({"media", "container", "supports", "layer", "starting-style"})
KEYFRAME_AT_RULES = frozenset({"keyframes", "-webkit-keyframes"})
HARMLESS_AT_RULES = frozenset({"charset"})
COMBINATORS = frozenset({">", "+", "~"})
SIBLING_COMBINATORS = frozenset({"+", "~"})
KEYFRAME_NAME_INFIX = "-"
SELECTOR_SNIPPET_CHARS = 80


@dataclass(frozen=True, slots=True)
class CssScope:
    scene_id: str

    @property
    def root_class(self) -> str:
        return scene_root_class(self.scene_id)

    @property
    def keyframe_prefix(self) -> str:
        return f"{self.root_class}{KEYFRAME_NAME_INFIX}"


def css_finding(code: StaticFindingCode, message: str, line: int | None, detail: str | None) -> StaticFinding:
    return StaticFinding(code=code, message=message, line=line, detail=detail)


def forbidden(message: str, line: int | None, detail: str | None) -> StaticFinding:
    return css_finding(StaticFindingCode.CSS_FORBIDDEN, message, line, detail)


def split_selectors(prelude: Sequence[Node]) -> list[list[Node]]:
    selectors: list[list[Node]] = [[]]
    for token in prelude:
        if isinstance(token, LiteralToken) and token.value == ",":
            selectors.append([])
        else:
            selectors[-1].append(token)
    return [trim(selector) for selector in selectors]


def trim(tokens: list[Node]) -> list[Node]:
    start = 0
    end = len(tokens)
    while start < end and isinstance(tokens[start], WhitespaceToken):
        start += 1
    while end > start and isinstance(tokens[end - 1], WhitespaceToken):
        end -= 1
    return tokens[start:end]


def first_compound(selector: Sequence[Node]) -> list[Node]:
    compound: list[Node] = []
    for token in selector:
        if isinstance(token, WhitespaceToken) or (isinstance(token, LiteralToken) and token.value in COMBINATORS):
            break
        compound.append(token)
    return compound


def has_root_class(compound: Sequence[Node], root_class: str) -> bool:
    for index in range(len(compound) - 1):
        marker = compound[index]
        name = compound[index + 1]
        if (
            isinstance(marker, LiteralToken)
            and marker.value == "."
            and isinstance(name, IdentToken)
            and name.value == root_class
        ):
            return True
    return False


def is_root_only(selector: Sequence[Node], root_class: str) -> bool:
    compound = first_compound(selector)
    return has_root_class(compound, root_class) and len(compound) == len(selector)


def uses_sibling_combinator(selector: Sequence[Node]) -> bool:
    return any(isinstance(token, LiteralToken) and token.value in SIBLING_COMBINATORS for token in selector)


def selector_text(selector: Sequence[Node]) -> str:
    return snippet(tinycss2.serialize(list(selector)).strip())[:SELECTOR_SNIPPET_CHARS]


def selector_findings(rule: QualifiedRule, scope: CssScope) -> Iterator[StaticFinding]:
    for selector in split_selectors(rule.prelude):
        text = selector_text(selector)
        if not has_root_class(first_compound(selector), scope.root_class):
            yield css_finding(
                StaticFindingCode.CSS_UNSCOPED,
                f"Selector `{text}` must start with `.{scope.root_class}`",
                rule.source_line,
                text,
            )
        elif uses_sibling_combinator(selector):
            yield css_finding(
                StaticFindingCode.CSS_UNSCOPED,
                f"Selector `{text}` uses a sibling combinator that can reach other scenes",
                rule.source_line,
                text,
            )


def parse_error_findings(tokens: Iterable[Node]) -> Iterator[StaticFinding]:
    stack = list(tokens)
    while stack:
        token = stack.pop()
        if isinstance(token, ParseError):
            yield css_finding(StaticFindingCode.CSS_SYNTAX, token.message, token.source_line, token.kind)
        else:
            stack.extend(nested_tokens(token))


def url_findings(tokens: Sequence[Node], line: int | None) -> Iterator[StaticFinding]:
    for value in iter_urls(tokens):
        if value == BAD_MARKER:
            continue
        if value == DYNAMIC_MARKER:
            yield forbidden("A url() built from var(), attr() or env() cannot be checked", line, "var()")
        elif not is_allowed_url(value):
            yield forbidden(
                f"url() to `{snippet(value)}` is not allowed; use a data: image or a #fragment", line, snippet(value)
            )


def is_allowed_url(value: str) -> bool:
    normalized = normalize_url(value)
    if normalized.startswith("#"):
        return check_url(value).allowed
    return normalized.lower().startswith("data:image/") and check_url(value).allowed


def custom_property_findings(declaration: Declaration) -> Iterator[StaticFinding]:
    for value in iter_strings(declaration.value):
        if URL_LIKE_STRING.match(value) and not is_allowed_url(value):
            yield forbidden(
                f"The custom property `{declaration.name}` holds a URL string that is not allowed",
                declaration.source_line,
                snippet(value),
            )


def keyword_value(declaration: Declaration, expected: str) -> bool:
    return any(isinstance(token, IdentToken) and token.lower_value == expected for token in declaration.value)


def declaration_findings(declaration: Declaration, root_only: bool) -> Iterator[StaticFinding]:
    line = declaration.source_line
    yield from parse_error_findings(declaration.value)
    yield from url_findings(declaration.value, line)
    if declaration.name.startswith("--"):
        yield from custom_property_findings(declaration)
    if declaration.lower_name == "position" and keyword_value(declaration, "fixed") and not root_only:
        yield forbidden("position: fixed is only allowed on the scene root", line, "position")
    if declaration.important and root_only:
        yield forbidden("!important is not allowed on the scene root", line, declaration.lower_name)


def rule_is_root_only(rule: QualifiedRule, scope: CssScope) -> bool:
    selectors = split_selectors(rule.prelude)
    return bool(selectors) and all(is_root_only(selector, scope.root_class) for selector in selectors)


def block_findings(content: Sequence[Node], scope: CssScope, root_only: bool) -> Iterator[StaticFinding]:
    for item in tinycss2.parse_blocks_contents(content, skip_comments=True, skip_whitespace=True):
        if isinstance(item, Declaration):
            yield from declaration_findings(item, root_only)
        elif isinstance(item, AtRule):
            yield from at_rule_findings(item, scope, require_scope=False)
        elif isinstance(item, QualifiedRule):
            yield from parse_error_findings(item.prelude)
            yield from block_findings(item.content, scope, root_only)
        elif isinstance(item, ParseError):
            yield css_finding(StaticFindingCode.CSS_SYNTAX, item.message, item.source_line, item.kind)


def qualified_rule_findings(rule: QualifiedRule, scope: CssScope, require_scope: bool) -> Iterator[StaticFinding]:
    yield from parse_error_findings(rule.prelude)
    yield from url_findings(rule.prelude, rule.source_line)
    if require_scope:
        yield from selector_findings(rule, scope)
    yield from block_findings(rule.content, scope, require_scope and rule_is_root_only(rule, scope))


def keyframes_name(rule: AtRule) -> str | None:
    for token in rule.prelude:
        if isinstance(token, IdentToken | StringToken):
            return token.value
    return None


def keyframes_findings(rule: AtRule, scope: CssScope) -> Iterator[StaticFinding]:
    name = keyframes_name(rule)
    if name is None or not name.startswith(scope.keyframe_prefix):
        shown = name if name is not None else ""
        yield css_finding(
            StaticFindingCode.CSS_UNSCOPED,
            f"@keyframes `{shown}` must be named `{scope.keyframe_prefix}<name>`",
            rule.source_line,
            shown,
        )
    if rule.content is not None:
        yield from block_findings(rule.content, scope, root_only=False)


def conditional_findings(rule: AtRule, scope: CssScope, require_scope: bool) -> Iterator[StaticFinding]:
    yield from parse_error_findings(rule.prelude)
    yield from url_findings(rule.prelude, rule.source_line)
    if rule.content is None:
        return
    if require_scope:
        yield from rule_list_findings(
            tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True), scope, True
        )
    else:
        yield from block_findings(rule.content, scope, root_only=False)


def at_rule_findings(rule: AtRule, scope: CssScope, require_scope: bool) -> Iterator[StaticFinding]:
    keyword = rule.lower_at_keyword
    if keyword in KEYFRAME_AT_RULES:
        yield from keyframes_findings(rule, scope)
    elif keyword in CONDITIONAL_AT_RULES:
        yield from conditional_findings(rule, scope, require_scope)
    elif keyword not in HARMLESS_AT_RULES:
        yield forbidden(f"@{keyword} is not allowed in a scene stylesheet", rule.source_line, f"@{keyword}")


def rule_list_findings(rules: Iterable[Node], scope: CssScope, require_scope: bool) -> Iterator[StaticFinding]:
    for rule in rules:
        if isinstance(rule, QualifiedRule):
            yield from qualified_rule_findings(rule, scope, require_scope)
        elif isinstance(rule, AtRule):
            yield from at_rule_findings(rule, scope, require_scope)
        elif isinstance(rule, ParseError):
            yield css_finding(StaticFindingCode.CSS_SYNTAX, rule.message, rule.source_line, rule.kind)


def check_css(css: str, scene_id: str) -> list[StaticFinding]:
    rules = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
    findings = list(rule_list_findings(rules, CssScope(scene_id), True))
    unique = {(item.code.value, item.line or 0, item.detail or "", item.message): item for item in findings}
    return [unique[key] for key in sorted(unique)]
