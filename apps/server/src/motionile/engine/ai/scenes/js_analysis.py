from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import tree_sitter_javascript
from tree_sitter import Language, Node, Parser, Tree

WRAPPER_HEAD = "function __motionile_builder__(ctx) {\n"
WRAPPER_TAIL = "\n}\n"
MAX_SYNTAX_PROBLEMS = 5
SNIPPET_CHARS = 60

FUNCTION_NODE_TYPES = frozenset(
    {
        "function_declaration",
        "function_expression",
        "generator_function",
        "generator_function_declaration",
        "arrow_function",
        "method_definition",
    }
)
FUNCTION_DECLARATION_TYPES = frozenset({"function_declaration", "generator_function_declaration"})
NAMED_FUNCTION_EXPRESSION_TYPES = frozenset({"function_expression", "generator_function"})
BLOCK_NODE_TYPES = frozenset({"statement_block", "switch_body"})
PATTERN_CONTAINER_TYPES = frozenset({"object_pattern", "array_pattern", "rest_pattern", "formal_parameters"})
PATTERN_DEFAULT_TYPES = frozenset({"assignment_pattern", "object_assignment_pattern"})
PATTERN_NAME_TYPES = frozenset({"identifier", "shorthand_property_identifier_pattern"})
REFERENCE_NODE_TYPES = frozenset(
    {"identifier", "shorthand_property_identifier", "shorthand_property_identifier_pattern"}
)
LEXICAL_KINDS = frozenset({"let", "const"})
CONTEXT_NAME = "ctx"
IMPLICIT_BINDINGS = (CONTEXT_NAME, "arguments")

JAVASCRIPT = Language(tree_sitter_javascript.language())


@dataclass(frozen=True, slots=True)
class SyntaxProblem:
    line: int
    message: str


@dataclass(frozen=True, slots=True)
class ParsedBuilder:
    tree: Tree
    function: Node | None
    body: Node | None
    lines: tuple[str, ...]
    problems: tuple[SyntaxProblem, ...]

    @property
    def is_valid(self) -> bool:
        return not self.problems and self.body is not None


@dataclass(frozen=True, slots=True)
class FreeReference:
    name: str
    node: Node

    @property
    def line(self) -> int:
        return line_of(self.node)


@dataclass(frozen=True, slots=True)
class ReferenceAnalysis:
    free: tuple[FreeReference, ...]
    context_ids: frozenset[int]


class Scope:
    __slots__ = ("names", "parent")

    def __init__(self, parent: "Scope | None") -> None:
        self.parent = parent
        self.names: set[str] = set()

    def owner(self, name: str) -> "Scope | None":
        scope: Scope | None = self
        while scope is not None:
            if name in scope.names:
                return scope
            scope = scope.parent
        return None

    def declares(self, name: str) -> bool:
        return self.owner(name) is not None


def normalize_source(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def text_of(node: Node) -> str:
    return (node.text or b"").decode("utf-8", errors="replace")


def line_of(node: Node) -> int:
    return node.start_point.row


def walk(root: Node) -> Iterator[Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def error_problems(tree: Tree, lines: tuple[str, ...], last_line: int) -> list[SyntaxProblem]:
    problems: list[SyntaxProblem] = []
    stack = [tree.root_node]
    while stack and len(problems) < MAX_SYNTAX_PROBLEMS:
        node = stack.pop()
        line = min(line_of(node), last_line)
        if node.is_missing:
            problems.append(SyntaxProblem(line, f"Missing `{node.type}` near line {line}"))
        elif node.type == "ERROR":
            problems.append(SyntaxProblem(line, f"Unexpected syntax near `{line_snippet(lines, node)}`"))
        elif node.has_error:
            stack.extend(reversed(node.children))
    return sorted(problems, key=lambda problem: (problem.line, problem.message))


def line_snippet(lines: tuple[str, ...], node: Node) -> str:
    index = line_of(node)
    text = lines[index].strip() if 0 <= index < len(lines) else ""
    return text[:SNIPPET_CHARS]


def structure_problems(tree: Tree, last_line: int) -> list[SyntaxProblem]:
    children = tree.root_node.children
    if len(children) == 1 and children[0].type == "function_declaration":
        return []
    extra = children[1] if len(children) > 1 else tree.root_node
    return [
        SyntaxProblem(
            min(line_of(extra), last_line),
            "Braces do not balance: the builder closes its own function early or leaves a block open",
        )
    ]


def parse_builder(builder: str) -> ParsedBuilder:
    normalized = normalize_source(builder)
    source = WRAPPER_HEAD + normalized + WRAPPER_TAIL
    tree = Parser(JAVASCRIPT).parse(source.encode("utf-8"))
    lines = tuple(source.split("\n"))
    last_line = normalized.count("\n") + 1
    problems = error_problems(tree, lines, last_line)
    if not problems:
        problems = structure_problems(tree, last_line)
    function = tree.root_node.children[0] if not problems else None
    body = function.child_by_field_name("body") if function is not None else None
    return ParsedBuilder(tree=tree, function=function, body=body, lines=lines, problems=tuple(problems))


def pattern_names(pattern: Node | None) -> Iterator[str]:
    stack: list[Node | None] = [pattern]
    while stack:
        node = stack.pop()
        if node is None:
            continue
        if node.type in PATTERN_NAME_TYPES:
            yield text_of(node)
        elif node.type == "pair_pattern":
            stack.append(node.child_by_field_name("value"))
        elif node.type in PATTERN_DEFAULT_TYPES:
            stack.append(node.child_by_field_name("left"))
        elif node.type in PATTERN_CONTAINER_TYPES:
            stack.extend(node.named_children)


def declarator_names(declaration: Node) -> Iterator[str]:
    for child in declaration.named_children:
        if child.type == "variable_declarator":
            yield from pattern_names(child.child_by_field_name("name"))


def statement_name(statement: Node) -> Iterator[str]:
    name = statement.child_by_field_name("name")
    if name is not None:
        yield text_of(name)


def lexical_names(statements: Iterable[Node]) -> Iterator[str]:
    for statement in statements:
        if statement.type == "lexical_declaration":
            yield from declarator_names(statement)
        elif statement.type in FUNCTION_DECLARATION_TYPES or statement.type == "class_declaration":
            yield from statement_name(statement)


def switch_statements(body: Node) -> Iterator[Node]:
    for case in body.named_children:
        yield from case.named_children


def block_statements(node: Node) -> Iterable[Node]:
    return switch_statements(node) if node.type == "switch_body" else node.named_children


def hoisted_var_names(root: Node) -> Iterator[str]:
    stack = list(root.named_children)
    while stack:
        node = stack.pop()
        if node.type in FUNCTION_NODE_TYPES:
            continue
        if node.type == "variable_declaration":
            yield from declarator_names(node)
        elif node.type == "for_in_statement":
            kind = node.child_by_field_name("kind")
            if kind is not None and kind.type == "var":
                yield from pattern_names(node.child_by_field_name("left"))
        stack.extend(node.named_children)


def function_scope(node: Node, parent: Scope) -> Scope:
    scope = Scope(parent)
    scope.names.update(pattern_names(node.child_by_field_name("parameters")))
    scope.names.update(pattern_names(node.child_by_field_name("parameter")))
    if node.type in NAMED_FUNCTION_EXPRESSION_TYPES:
        scope.names.update(statement_name(node))
    if node.type != "arrow_function":
        scope.names.add("arguments")
    body = node.child_by_field_name("body")
    if body is not None and body.type == "statement_block":
        scope.names.update(hoisted_var_names(body))
    return scope


def block_scope(node: Node, parent: Scope) -> Scope:
    scope = Scope(parent)
    scope.names.update(lexical_names(block_statements(node)))
    return scope


def loop_scope(node: Node, parent: Scope) -> Scope:
    scope = Scope(parent)
    scope.names.update(lexical_names(node.named_children))
    if node.type == "for_in_statement":
        kind = node.child_by_field_name("kind")
        if kind is not None and kind.type in LEXICAL_KINDS:
            scope.names.update(pattern_names(node.child_by_field_name("left")))
    return scope


def catch_scope(node: Node, parent: Scope) -> Scope:
    scope = Scope(parent)
    scope.names.update(pattern_names(node.child_by_field_name("parameter")))
    return scope


def class_expression_scope(node: Node, parent: Scope) -> Scope:
    scope = Scope(parent)
    scope.names.update(statement_name(node))
    return scope


def enter_scope(node: Node, scope: Scope) -> Scope:
    node_type = node.type
    if node_type in FUNCTION_NODE_TYPES:
        return function_scope(node, scope)
    if node_type in BLOCK_NODE_TYPES:
        return block_scope(node, scope)
    if node_type in {"for_statement", "for_in_statement"}:
        return loop_scope(node, scope)
    if node_type == "catch_clause":
        return catch_scope(node, scope)
    if node_type == "class" and node.is_named:
        return class_expression_scope(node, scope)
    return scope


def root_scope(body: Node) -> Scope:
    scope = Scope(None)
    scope.names.update(IMPLICIT_BINDINGS)
    scope.names.update(hoisted_var_names(body))
    scope.names.update(lexical_names(body.named_children))
    return scope


def analyze_references(parsed: ParsedBuilder) -> ReferenceAnalysis:
    body = parsed.body
    if body is None:
        return ReferenceAnalysis((), frozenset())
    root = root_scope(body)
    stack = [(child, root) for child in reversed(body.children)]
    free: list[FreeReference] = []
    context_ids: set[int] = set()
    while stack:
        node, scope = stack.pop()
        inner = enter_scope(node, scope)
        if node.type in REFERENCE_NODE_TYPES:
            name = text_of(node)
            if not inner.declares(name):
                free.append(FreeReference(name, node))
            elif name == CONTEXT_NAME and inner.owner(name) is root:
                context_ids.add(node.id)
        stack.extend((child, inner) for child in reversed(node.children))
    return ReferenceAnalysis(tuple(free), frozenset(context_ids))
