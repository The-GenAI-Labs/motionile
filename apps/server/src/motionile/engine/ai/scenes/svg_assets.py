import contextlib
import re
from xml.parsers import expat

from motionile.engine.ai.scenes.models import SceneAsset, StaticFinding, StaticFindingCode

FORBIDDEN_ELEMENTS = frozenset(
    {
        "script",
        "foreignobject",
        "iframe",
        "object",
        "embed",
        "audio",
        "video",
        "canvas",
        "link",
        "meta",
        "base",
        "form",
        "input",
        "button",
        "textarea",
        "select",
        "img",
        "portal",
    }
)
HTML_BREAKOUT_ELEMENTS = frozenset(
    {
        "b",
        "big",
        "blockquote",
        "body",
        "br",
        "center",
        "code",
        "dd",
        "div",
        "dl",
        "dt",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "head",
        "hr",
        "i",
        "li",
        "listing",
        "menu",
        "nobr",
        "ol",
        "p",
        "pre",
        "ruby",
        "s",
        "small",
        "span",
        "strike",
        "strong",
        "sub",
        "sup",
        "table",
        "tt",
        "u",
        "ul",
        "var",
        "font",
    }
)
ANIMATION_ELEMENTS = frozenset({"animate", "set", "animatetransform", "animatemotion"})
LINK_ATTRIBUTES = frozenset({"href", "xlink:href"})
URL_FUNCTION = re.compile(r"url\(\s*(['\"]?)\s*([^)'\"]*)", re.IGNORECASE)
SCRIPT_URL = re.compile(r"java\s*script\s*:", re.IGNORECASE)
IMPORT_RULE = re.compile(r"@import", re.IGNORECASE)
MAX_PROBLEMS = 10
SNIPPET_CHARS = 60


class RejectedError(Exception):
    pass


def is_safe_url(target: str) -> bool:
    cleaned = target.strip()
    return cleaned.startswith("#") or cleaned.lower().startswith("data:image/")


class SvgChecker:
    def __init__(self, asset_id: str) -> None:
        self.asset_id = asset_id
        self.problems: list[StaticFinding] = []
        self.depth = 0
        self.root_seen = False
        self.style_depth = 0
        self.style_text: list[str] = []
        self.parser = expat.ParserCreate()
        self.parser.buffer_text = True
        self.parser.StartElementHandler = self.start_element
        self.parser.EndElementHandler = self.end_element
        self.parser.CharacterDataHandler = self.character_data
        self.parser.StartDoctypeDeclHandler = self.reject_doctype
        self.parser.ProcessingInstructionHandler = self.reject_instruction

    def report(self, message: str, detail: str | None = None, line: int | None = None) -> None:
        self.problems.append(
            StaticFinding(
                code=StaticFindingCode.ASSET_INVALID,
                message=f"Asset `{self.asset_id}`: {message}",
                line=line if line is not None else self.parser.CurrentLineNumber,
                detail=detail or self.asset_id,
            )
        )
        if len(self.problems) >= MAX_PROBLEMS:
            raise RejectedError

    def check_css_text(self, text: str, origin: str) -> None:
        if IMPORT_RULE.search(text):
            self.report(f"{origin} uses @import", "@import")
        for match in URL_FUNCTION.finditer(text):
            if not is_safe_url(match.group(2)):
                self.report(f"{origin} references an external URL", match.group(2)[:SNIPPET_CHARS])

    def check_attribute(self, element: str, name: str, value: str) -> None:
        lowered = name.lower()
        if lowered.startswith("on") or lowered == "srcdoc":
            self.report(f"`{name}` attributes are not allowed", name)
        elif lowered in LINK_ATTRIBUTES and not value.strip().startswith("#"):
            self.report(f"`{name}` may only reference a #fragment", value[:SNIPPET_CHARS])
        elif lowered == "style":
            self.check_css_text(value, "A style attribute")
        elif lowered == "attributename" and element.lower() in ANIMATION_ELEMENTS:
            target = value.strip().lower()
            if target in LINK_ATTRIBUTES or target.startswith("on"):
                self.report(f"`{element}` may not animate `{value}`", value)
        if SCRIPT_URL.search(value):
            self.report("javascript: URLs are not allowed", name)
        if lowered != "style":
            for match in URL_FUNCTION.finditer(value):
                if not is_safe_url(match.group(2)):
                    self.report(f"`{name}` references an external URL", match.group(2)[:SNIPPET_CHARS])

    def check_element(self, name: str) -> None:
        lowered = name.lower()
        if self.depth == 0:
            if name != "svg":
                self.report(f"The root element must be <svg>, not <{name}>", name)
            self.root_seen = True
        if lowered in FORBIDDEN_ELEMENTS:
            self.report(f"<{name}> is not allowed", name)
        elif lowered in HTML_BREAKOUT_ELEMENTS:
            self.report(f"<{name}> is an HTML element and would break out of the SVG", name)

    def start_element(self, name: str, attributes: dict[str, str]) -> None:
        self.check_element(name)
        for attribute, value in sorted(attributes.items()):
            self.check_attribute(name, attribute, value)
        if name.lower() == "style":
            self.style_depth += 1
        self.depth += 1

    def end_element(self, name: str) -> None:
        self.depth -= 1
        if name.lower() == "style":
            self.style_depth -= 1
            self.check_css_text("".join(self.style_text), "A <style> element")
            self.style_text.clear()

    def character_data(self, text: str) -> None:
        if self.style_depth:
            self.style_text.append(text)

    def reject_doctype(self, *_: object) -> None:
        self.report("DOCTYPE and entity declarations are not allowed", "doctype")
        raise RejectedError

    def reject_instruction(self, *_: object) -> None:
        self.report("Processing instructions are not allowed", "instruction")

    def run(self, svg: str) -> list[StaticFinding]:
        if svg.lstrip().startswith("<?"):
            self.report("Processing instructions are not allowed", "instruction", line=1)
        try:
            self.parser.Parse(svg, True)
        except expat.ExpatError as error:
            with contextlib.suppress(RejectedError):
                self.report(
                    f"The SVG is not well-formed XML: {expat.ErrorString(error.code)}", "xml", line=error.lineno
                )
        except RejectedError:
            pass
        if not self.root_seen and not self.problems:
            with contextlib.suppress(RejectedError):
                self.report("The SVG has no <svg> root element", "svg", line=1)
        return self.problems


def check_svg_asset(asset: SceneAsset) -> list[StaticFinding]:
    return SvgChecker(asset.id).run(asset.svg)
