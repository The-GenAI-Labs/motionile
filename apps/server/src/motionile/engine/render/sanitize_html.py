from typing import cast
from xml.etree.ElementTree import Element

DOCTYPE = "<!DOCTYPE html>"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
XMLNS_NAMESPACE = "http://www.w3.org/2000/xmlns/"
VOID_ELEMENTS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
RAW_TEXT_ELEMENTS = frozenset({"script", "style"})
LEADING_NEWLINE_ELEMENTS = frozenset({"pre", "textarea", "listing"})
NBSP = chr(0xA0)
TEXT_ESCAPES = {"&": "&amp;", NBSP: "&nbsp;", "<": "&lt;", ">": "&gt;"}
ATTRIBUTE_ESCAPES = {"&": "&amp;", NBSP: "&nbsp;", '"': "&quot;", "<": "&lt;", ">": "&gt;"}
NAMESPACE_PREFIXES = {XLINK_NAMESPACE: "xlink:", XML_NAMESPACE: "xml:", XMLNS_NAMESPACE: "xmlns:"}


def is_comment(element: Element) -> bool:
    return callable(cast("object", element.tag))


def split_name(name: str) -> tuple[str, str]:
    if name.startswith("{"):
        namespace, _, local = name[1:].partition("}")
        return namespace, local
    return "", name


def local_name(name: str) -> str:
    return split_name(name)[1]


def escape_with(value: str, table: dict[str, str]) -> str:
    return "".join(table.get(character, character) for character in value)


def attribute_name(name: str) -> str:
    namespace, local = split_name(name)
    return NAMESPACE_PREFIXES.get(namespace, "") + local


def serialize_attributes(element: Element) -> str:
    return "".join(
        f' {attribute_name(name)}="{escape_with(value, ATTRIBUTE_ESCAPES)}"' for name, value in element.attrib.items()
    )


def serialize_content(namespace: str, lowered: str, text: str) -> str:
    if not namespace and lowered in RAW_TEXT_ELEMENTS:
        return text
    prefix = "\n" if text.startswith("\n") and not namespace and lowered in LEADING_NEWLINE_ELEMENTS else ""
    return prefix + escape_with(text, TEXT_ESCAPES)


def expand_element(element: Element, namespace: str, name: str) -> list[str | Element]:
    lowered = name.lower()
    items: list[str | Element] = []
    if element.text:
        items.append(serialize_content(namespace, lowered, element.text))
    for child in element:
        if not is_comment(child):
            items.append(child)
        if child.tail:
            items.append(escape_with(child.tail, TEXT_ESCAPES))
    items.append(f"</{name}>")
    return items


def serialize_element(root: Element) -> str:
    output: list[str] = []
    stack: list[str | Element] = [root]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            output.append(item)
            continue
        namespace, name = split_name(item.tag)
        output.append(f"<{name}{serialize_attributes(item)}>")
        if not namespace and name.lower() in VOID_ELEMENTS:
            continue
        stack.extend(reversed(expand_element(item, namespace, name)))
    return "".join(output)


def serialize_document(root: Element) -> str:
    return f"{DOCTYPE}\n{serialize_element(root)}"
