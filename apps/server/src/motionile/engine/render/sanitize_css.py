import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field

import tinycss2
from tinycss2.ast import (
    AtRule,
    CurlyBracketsBlock,
    Declaration,
    FunctionBlock,
    Node,
    ParenthesesBlock,
    ParseError,
    QualifiedRule,
    SquareBracketsBlock,
    StringToken,
    URLToken,
)

from motionile.engine.render.models import IssueCode
from motionile.engine.render.sanitize_urls import UrlVerdict, check_url, snippet

URL_FUNCTIONS = frozenset({"url", "src"})
IMAGE_FUNCTIONS = frozenset({"image-set", "-webkit-image-set", "image", "cross-fade", "-webkit-cross-fade"})
DYNAMIC_FUNCTIONS = frozenset({"var", "attr", "env"})
DYNAMIC_MARKER = "\x00dynamic"
URL_LIKE_STRING = re.compile(
    r"^\s*(?:data\s*:|(?:https?|ftp|file|javascript|wss?|blob|about|chrome|view-source)\s*:|//)", re.IGNORECASE
)
BAD_MARKER = "\x00bad"


@dataclass(frozen=True)
class CssProblem:
    code: IssueCode
    message: str
    url: str


@dataclass
class CssScan:
    problems: list[CssProblem] = field(default_factory=list[CssProblem])
    data_bytes: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.problems)


def nested_tokens(token: Node) -> Sequence[Node]:
    if isinstance(token, FunctionBlock):
        return token.arguments
    if isinstance(token, ParenthesesBlock | SquareBracketsBlock | CurlyBracketsBlock):
        return token.content
    return ()


def contains_dynamic(tokens: Iterable[Node]) -> bool:
    return any(
        (isinstance(token, FunctionBlock) and token.lower_name in DYNAMIC_FUNCTIONS)
        or contains_dynamic(nested_tokens(token))
        for token in tokens
    )


def function_urls(block: FunctionBlock) -> Iterator[str]:
    name = block.lower_name
    if name in URL_FUNCTIONS:
        if contains_dynamic(block.arguments):
            yield DYNAMIC_MARKER
        yield from (item.value for item in block.arguments if isinstance(item, StringToken))
        return
    if name in IMAGE_FUNCTIONS:
        if contains_dynamic(block.arguments):
            yield DYNAMIC_MARKER
        for item in block.arguments:
            if isinstance(item, StringToken):
                yield item.value
            else:
                yield from iter_urls([item])
        return
    yield from iter_urls(block.arguments)


def iter_urls(tokens: Iterable[Node]) -> Iterator[str]:
    for token in tokens:
        if isinstance(token, URLToken):
            yield token.value
        elif isinstance(token, FunctionBlock):
            yield from function_urls(token)
        elif isinstance(token, ParseError):
            if token.kind in {"bad-url", "bad-string"}:
                yield BAD_MARKER
        else:
            yield from iter_urls(nested_tokens(token))


def judge_url(value: str, scan: CssScan) -> None:
    if value == DYNAMIC_MARKER:
        scan.problems.append(CssProblem(IssueCode.FORBIDDEN_URL, "CSS url() with a dynamic value", "var()"))
        return
    if value == BAD_MARKER:
        scan.problems.append(CssProblem(IssueCode.FORBIDDEN_URL, "CSS contains a malformed url()", ""))
        return
    check = check_url(value)
    scan.data_bytes += check.data_bytes
    if check.verdict is UrlVerdict.FORBIDDEN:
        scan.problems.append(
            CssProblem(IssueCode.FORBIDDEN_URL, f"CSS URL not allowed: {check.reason}", snippet(value))
        )
    elif check.verdict is UrlVerdict.INVALID_DATA:
        scan.problems.append(
            CssProblem(IssueCode.INVALID_DATA_URI, f"CSS data URI not allowed: {check.reason}", snippet(value))
        )


def judge_tokens(tokens: Iterable[Node], scan: CssScan) -> bool:
    before = len(scan.problems)
    for value in iter_urls(tokens):
        judge_url(value, scan)
    return len(scan.problems) == before


def import_candidates(prelude: Sequence[Node]) -> Iterator[str]:
    for token in prelude:
        if isinstance(token, StringToken):
            yield token.value
        else:
            yield from iter_urls([token])


def clean_block(content: Sequence[Node], scan: CssScan) -> str:
    parts: list[str] = []
    for item in tinycss2.parse_blocks_contents(content, skip_comments=True, skip_whitespace=True):
        text = clean_item(item, scan)
        if text:
            parts.append(text)
    return ";".join(parts)


def iter_strings(tokens: Iterable[Node]) -> Iterator[str]:
    for token in tokens:
        if isinstance(token, StringToken):
            yield token.value
        else:
            yield from iter_strings(nested_tokens(token))


def judge_custom_property(declaration: Declaration, scan: CssScan) -> None:
    for value in iter_strings(declaration.value):
        if URL_LIKE_STRING.match(value):
            judge_url(value, scan)


def clean_declaration(declaration: Declaration, scan: CssScan) -> str:
    before = len(scan.problems)
    judge_tokens(declaration.value, scan)
    if declaration.name.startswith("--"):
        judge_custom_property(declaration, scan)
    if len(scan.problems) > before:
        return ""
    return declaration.serialize()


def clean_at_rule(rule: AtRule, scan: CssScan) -> str:
    if rule.lower_at_keyword == "import":
        before = len(scan.problems)
        for value in import_candidates(rule.prelude):
            judge_url(value, scan)
        return "" if len(scan.problems) > before else rule.serialize()
    if not judge_tokens(rule.prelude, scan):
        return ""
    if rule.content is None:
        return rule.serialize()
    return f"@{rule.at_keyword}{tinycss2.serialize(rule.prelude)}{{{clean_block(rule.content, scan)}}}"


def clean_qualified_rule(rule: QualifiedRule, scan: CssScan) -> str:
    return f"{tinycss2.serialize(rule.prelude)}{{{clean_block(rule.content, scan)}}}"


def clean_item(item: Node, scan: CssScan) -> str:
    if isinstance(item, Declaration):
        return clean_declaration(item, scan)
    if isinstance(item, AtRule):
        return clean_at_rule(item, scan)
    if isinstance(item, QualifiedRule):
        return clean_qualified_rule(item, scan)
    return ""


def clean_stylesheet(css: str, scan: CssScan) -> str:
    rules = tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True)
    cleaned = "\n".join(text for text in (clean_item(rule, scan) for rule in rules) if text)
    return cleaned if scan.changed else css


def clean_inline_style(css: str, scan: CssScan) -> str:
    cleaned = clean_block(tinycss2.parse_component_value_list(css), scan)
    return cleaned if scan.changed else css


def scan_value(value: str, scan: CssScan) -> bool:
    return judge_tokens(tinycss2.parse_component_value_list(value), scan)
