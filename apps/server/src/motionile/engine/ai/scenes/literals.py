import html
import re
from collections.abc import Iterator

from tree_sitter import Node, Parser

from motionile.engine.ai.scenes.js_analysis import JAVASCRIPT, text_of, walk
from motionile.engine.ai.scenes.models import SceneModule

STRING_NODE_TYPES = frozenset({"string", "template_string"})
STRING_PART_TYPES = frozenset({"string_fragment"})
CSS_STRING = re.compile(r"""\"((?:[^\"\\]|\\.)*)\"|'((?:[^'\\]|\\.)*)'""", re.DOTALL)
SVG_TAG = re.compile(r"<[^>]*>", re.DOTALL)
SEPARATOR = " "


def literal_text(node: Node) -> str:
    return SEPARATOR.join(text_of(child) for child in node.children if child.type in STRING_PART_TYPES)


def builder_literals(builder: str) -> Iterator[str]:
    tree = Parser(JAVASCRIPT).parse(builder.encode("utf-8"))
    for node in walk(tree.root_node):
        if node.type in STRING_NODE_TYPES:
            text = literal_text(node)
            if text.strip():
                yield text


def css_literals(css: str) -> Iterator[str]:
    for match in CSS_STRING.finditer(css):
        text = match.group(1) or match.group(2) or ""
        if text.strip():
            yield text


def svg_literals(svg: str) -> Iterator[str]:
    text = html.unescape(SVG_TAG.sub(SEPARATOR, svg))
    if text.strip():
        yield text


def scene_literals(module: SceneModule) -> str:
    parts = [
        *builder_literals(module.builder),
        *css_literals(module.css),
        *(text for asset in module.assets for text in svg_literals(asset.svg)),
    ]
    return SEPARATOR.join(parts)
