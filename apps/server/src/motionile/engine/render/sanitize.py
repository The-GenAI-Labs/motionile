from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, cast
from xml.etree.ElementTree import Element

import html5lib
from pydantic import JsonValue

from motionile.engine.render.models import (
    InvalidCompositionError,
    IssueCode,
    ValidationIssue,
    ValidationReport,
    ValidationStats,
    Where,
    make_issue,
)
from motionile.engine.render.sanitize_css import (
    CssScan,
    clean_inline_style,
    clean_stylesheet,
    scan_value,
)
from motionile.engine.render.sanitize_html import is_comment, local_name, serialize_document
from motionile.engine.render.sanitize_script import count_composition_calls, screen_script
from motionile.engine.render.sanitize_urls import UrlVerdict, check_url, is_runtime_url, snippet, split_srcset

MAX_HTML_BYTES = 1_048_576
MAX_DATA_URI_BYTES = 2_097_152
MAX_ELEMENTS = 5_000
MAX_PARSE_ERROR_DETAILS = 5

FORBIDDEN_ELEMENTS = frozenset(
    {
        "iframe",
        "frame",
        "frameset",
        "object",
        "embed",
        "form",
        "base",
        "audio",
        "video",
        "portal",
        "applet",
        "noscript",
        "noembed",
        "noframes",
        "xmp",
        "plaintext",
    }
)
URL_ATTRIBUTES = frozenset(
    {
        "src",
        "href",
        "poster",
        "action",
        "data",
        "background",
        "cite",
        "longdesc",
        "manifest",
        "codebase",
        "archive",
        "icon",
        "profile",
        "dynsrc",
        "lowsrc",
    }
)
SRCSET_ATTRIBUTES = frozenset({"srcset", "imagesrcset"})
ALWAYS_FORBIDDEN_ATTRIBUTES = frozenset({"srcdoc", "formaction", "ping"})
TARGET_ELEMENTS = frozenset({"a", "area", "link", "form"})
ANIMATION_ELEMENTS = frozenset({"animate", "set", "animatetransform", "animatemotion"})
SCRIPT_TYPES = frozenset({"", "text/javascript", "application/javascript", "module"})
CSS_FUNCTION_MARKERS = ("url(", "image-set(", "@import")
SCENE_ATTRIBUTE = "data-scene"
PERSISTENT_CODES = frozenset(
    {
        IssueCode.COMPOSITION_MULTIPLE.value,
        IssueCode.DATA_URIS_TOO_LARGE.value,
        IssueCode.TOO_MANY_ELEMENTS.value,
        IssueCode.HTML_TOO_LARGE.value,
    }
)


type ParseErrorEntry = tuple[tuple[int, int], str, dict[str, object]]


class TreeParser(Protocol):
    errors: list[ParseErrorEntry]

    def parse(self, stream: str) -> Element: ...


class LimitExceededError(Exception):
    pass


@dataclass(frozen=True)
class SanitizeResult:
    html: str
    findings: tuple[ValidationIssue, ...]
    composition_calls: int = 0
    scene_ids: tuple[str, ...] = ()

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(finding for finding in self.findings if finding.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(finding for finding in self.findings if finding.severity == "warning")

    @property
    def valid(self) -> bool:
        return not self.errors

    def report(self) -> ValidationReport:
        return ValidationReport(issues=self.findings, stats=ValidationStats(scenes=len(self.scene_ids)))

    def raise_for_errors(self) -> None:
        if self.errors:
            raise InvalidCompositionError(self.errors)


@dataclass
class SanitizeRun:
    findings: list[ValidationIssue] = field(default_factory=list[ValidationIssue])
    element_count: int = 0
    data_bytes: int = 0
    composition_calls: int = 0
    scene_ids: list[str] = field(default_factory=list[str])

    def add(
        self,
        code: IssueCode,
        message: str,
        selector: str | None = None,
        detail: dict[str, JsonValue] | None = None,
    ) -> None:
        self.findings.append(make_issue(code, message, Where(selector=selector), detail))


def json_list(values: Iterable[str]) -> list[JsonValue]:
    return list(values)


def segment_for(element: Element, name: str, position: int, repeated: bool) -> str:
    identifier = element.attrib.get("id")
    if identifier and identifier.isidentifier():
        return f"{name}#{identifier}"
    return f"{name}:nth-of-type({position})" if repeated else name


def judge_attribute_url(run: SanitizeRun, value: str, attribute: str, selector: str) -> bool:
    check = check_url(value)
    run.data_bytes += check.data_bytes
    if check.verdict is UrlVerdict.FORBIDDEN:
        run.add(
            IssueCode.FORBIDDEN_URL,
            f"{attribute} is not allowed: {check.reason}",
            selector,
            {"attribute": attribute, "url": snippet(value), "reason": check.reason},
        )
    elif check.verdict is UrlVerdict.INVALID_DATA:
        run.add(
            IssueCode.INVALID_DATA_URI,
            f"{attribute} data URI is not allowed: {check.reason}",
            selector,
            {"attribute": attribute, "url": snippet(value), "reason": check.reason},
        )
    return check.allowed


def report_css_problems(run: SanitizeRun, scan: CssScan, selector: str, origin: str) -> None:
    run.data_bytes += scan.data_bytes
    for problem in scan.problems:
        run.add(problem.code, problem.message, selector, {"origin": origin, "url": problem.url})


def clean_style_element(run: SanitizeRun, element: Element, selector: str) -> None:
    text = element.text or ""
    scan = CssScan()
    cleaned = clean_stylesheet(text, scan)
    report_css_problems(run, scan, selector, "style element")
    element.text = cleaned


def clean_style_attribute(run: SanitizeRun, element: Element, value: str, selector: str) -> None:
    scan = CssScan()
    cleaned = clean_inline_style(value, scan)
    report_css_problems(run, scan, selector, "style attribute")
    if scan.changed and not cleaned:
        del element.attrib["style"]
    else:
        element.attrib["style"] = cleaned


def sanitize_url_attribute(run: SanitizeRun, element: Element, key: str, local: str, selector: str) -> None:
    value = element.attrib[key]
    if local in SRCSET_ATTRIBUTES:
        verdicts = [judge_attribute_url(run, candidate, local, selector) for candidate in split_srcset(value)]
        allowed = all(verdicts)
    else:
        allowed = judge_attribute_url(run, value, local, selector)
    if not allowed:
        del element.attrib[key]


def sanitize_attributes(run: SanitizeRun, element: Element, name: str, selector: str) -> bool:
    for key in list(element.attrib):
        local = local_name(key).lower()
        value = element.attrib[key]
        if (
            local.startswith("on")
            or local in ALWAYS_FORBIDDEN_ATTRIBUTES
            or (local == "target" and name in TARGET_ELEMENTS)
        ):
            run.add(
                IssueCode.FORBIDDEN_ATTRIBUTE,
                f"The {local} attribute is not allowed",
                selector,
                {"attribute": local, "element": name},
            )
            del element.attrib[key]
        elif local == "attributename" and name in ANIMATION_ELEMENTS and is_dangerous_animation_target(value):
            run.add(
                IssueCode.FORBIDDEN_ATTRIBUTE,
                f"<{name}> may not animate {value}",
                selector,
                {"attribute": "attributeName", "element": name, "value": value},
            )
            return False
        elif local == "style":
            clean_style_attribute(run, element, value, selector)
        elif local in URL_ATTRIBUTES or local in SRCSET_ATTRIBUTES:
            sanitize_url_attribute(run, element, key, local, selector)
        elif any(marker in value.lower() for marker in CSS_FUNCTION_MARKERS):
            scan = CssScan()
            clean = scan_value(value, scan)
            report_css_problems(run, scan, selector, f"{local} attribute")
            if not clean:
                del element.attrib[key]
    return True


def is_dangerous_animation_target(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith("on") or lowered.endswith("href")


def require_runtime_source(run: SanitizeRun, value: str, attribute: str, selector: str) -> bool:
    if not judge_attribute_url(run, value, attribute, selector):
        return False
    if is_runtime_url(value):
        return True
    run.add(
        IssueCode.FORBIDDEN_URL,
        f"{attribute} must point at the runtime origin",
        selector,
        {"attribute": attribute, "url": snippet(value)},
    )
    return False


def inspect_link(run: SanitizeRun, element: Element, selector: str) -> bool:
    relations = element.attrib.get("rel", "").lower().split()
    href = element.attrib.get("href", "")
    if "stylesheet" not in relations:
        run.add(
            IssueCode.FORBIDDEN_ELEMENT,
            "<link> is only allowed for runtime stylesheets",
            selector,
            {"element": "link", "rel": " ".join(relations), "href": snippet(href)},
        )
        return False
    return require_runtime_source(run, href, "href", selector)


def screen_inline_script(run: SanitizeRun, element: Element, selector: str) -> None:
    body = element.text or ""
    run.composition_calls += count_composition_calls(body)
    for hit in screen_script(body):
        run.add(
            IssueCode.SCRIPT_API,
            f"The script uses {hit.name}",
            selector,
            {"api": hit.name, "excerpt": hit.excerpt},
        )


def inspect_script(run: SanitizeRun, element: Element, selector: str) -> bool:
    script_type = element.attrib.get("type", "").strip().lower()
    if script_type not in SCRIPT_TYPES:
        run.add(
            IssueCode.FORBIDDEN_ELEMENT,
            "<script> with this type is not allowed",
            selector,
            {"element": "script", "type": script_type},
        )
        return False
    source_key = next((key for key in element.attrib if local_name(key).lower() in {"src", "href"}), None)
    if source_key is not None:
        return require_runtime_source(run, element.attrib[source_key], "src", selector)
    screen_inline_script(run, element, selector)
    return True


def inspect_element(run: SanitizeRun, element: Element, selector: str) -> bool:
    name = local_name(element.tag).lower()
    if name in FORBIDDEN_ELEMENTS or (name == "meta" and any(key.lower() == "http-equiv" for key in element.attrib)):
        run.add(IssueCode.FORBIDDEN_ELEMENT, f"<{name}> is not allowed", selector, {"element": name})
        return False
    if name == "link" and not inspect_link(run, element, selector):
        return False
    if name == "script" and not inspect_script(run, element, selector):
        return False
    if name == "style":
        clean_style_element(run, element, selector)
    if not sanitize_attributes(run, element, name, selector):
        return False
    scene = element.attrib.get(SCENE_ATTRIBUTE)
    if scene is not None:
        run.scene_ids.append(scene)
    return True


def append_text(holder: Element | None, parent: Element, text: str) -> None:
    if not text:
        return
    if holder is None:
        parent.text = (parent.text or "") + text
    else:
        holder.tail = (holder.tail or "") + text


def sanitize_children(run: SanitizeRun, parent: Element, parent_selector: str) -> list[tuple[Element, str]]:
    kept: list[Element] = []
    pending: list[tuple[Element, str]] = []
    counts: dict[str, int] = {}
    totals: dict[str, int] = {}
    children = list(parent)
    for child in children:
        if not is_comment(child):
            name = local_name(child.tag).lower()
            totals[name] = totals.get(name, 0) + 1
    for child in children:
        previous = kept[-1] if kept else None
        if is_comment(child):
            append_text(previous, parent, child.tail or "")
            continue
        name = local_name(child.tag).lower()
        counts[name] = counts.get(name, 0) + 1
        run.element_count += 1
        if run.element_count > MAX_ELEMENTS:
            raise LimitExceededError
        selector = f"{parent_selector} > {segment_for(child, name, counts[name], totals[name] > 1)}"
        if not inspect_element(run, child, selector):
            append_text(previous, parent, child.tail or "")
            continue
        kept.append(child)
        pending.append((child, selector))
    parent[:] = kept
    return pending


def sanitize_tree(run: SanitizeRun, root: Element) -> None:
    run.element_count = 1
    stack: list[tuple[Element, str]] = [(root, "html")]
    while stack:
        parent, selector = stack.pop()
        stack.extend(reversed(sanitize_children(run, parent, selector)))


def parse_document(html: str) -> tuple[Element, list[ParseErrorEntry]]:
    parser = cast("TreeParser", html5lib.HTMLParser(namespaceHTMLElements=False))
    root = parser.parse(html)
    return root, parser.errors


def report_parse_errors(run: SanitizeRun, errors: Sequence[ParseErrorEntry]) -> None:
    if not errors:
        return
    codes: list[JsonValue] = [code for _, code, _ in errors[:MAX_PARSE_ERROR_DETAILS]]
    run.add(
        IssueCode.PARSE_ERROR,
        f"The parser recovered from {len(errors)} markup error(s)",
        None,
        {"count": len(errors), "first": codes},
    )


def compare_scenes(run: SanitizeRun, expected: Sequence[str]) -> None:
    found = run.scene_ids
    missing = [scene for scene in expected if scene not in found]
    extra = [scene for scene in found if scene not in expected]
    duplicated = sorted({scene for scene in found if found.count(scene) > 1})
    for scene in missing:
        run.add(
            IssueCode.SCENE_ELEMENT_MISSING,
            f'No element has data-scene="{scene}"',
            None,
            {"scene": scene},
        )
    if extra or duplicated:
        run.add(
            IssueCode.SCENE_MISMATCH,
            "The [data-scene] elements do not match the narration scenes",
            None,
            {
                "expected": json_list(expected),
                "found": json_list(found),
                "extra": json_list(extra),
                "duplicated": json_list(duplicated),
            },
        )
    elif not missing and list(expected) != [scene for scene in found if scene in expected]:
        run.add(
            IssueCode.SCENE_MISMATCH,
            "The [data-scene] elements are not in narration order",
            None,
            {"expected": json_list(expected), "found": json_list(found)},
        )


def sanitize_once(html: str, scene_ids: Sequence[str] | None) -> tuple[SanitizeRun, str]:
    run = SanitizeRun()
    size = len(html.encode("utf-8"))
    if size > MAX_HTML_BYTES + MAX_DATA_URI_BYTES:
        run.add(
            IssueCode.HTML_TOO_LARGE, f"The composition is larger than {size} bytes", None, {"limit": MAX_HTML_BYTES}
        )
        return run, ""
    root, parse_errors = parse_document(html)
    report_parse_errors(run, parse_errors)
    try:
        sanitize_attributes(run, root, "html", "html")
        sanitize_tree(run, root)
    except LimitExceededError:
        run.add(
            IssueCode.TOO_MANY_ELEMENTS,
            f"The composition has more than {MAX_ELEMENTS} elements",
            None,
            {"limit": MAX_ELEMENTS},
        )
        return run, ""
    if size - run.data_bytes > MAX_HTML_BYTES:
        run.add(
            IssueCode.HTML_TOO_LARGE,
            f"The markup is larger than {MAX_HTML_BYTES} bytes without its data URIs",
            None,
            {"limit": MAX_HTML_BYTES, "bytes": size - run.data_bytes},
        )
        return run, ""
    if run.data_bytes > MAX_DATA_URI_BYTES:
        run.add(
            IssueCode.DATA_URIS_TOO_LARGE,
            f"The data URIs total more than {MAX_DATA_URI_BYTES} bytes",
            None,
            {"limit": MAX_DATA_URI_BYTES, "bytes": run.data_bytes},
        )
    if run.composition_calls > 1:
        run.add(
            IssueCode.COMPOSITION_MULTIPLE,
            f"Motionile.composition is called {run.composition_calls} times; call it exactly once",
            None,
            {"calls": run.composition_calls},
        )
    if scene_ids is not None:
        compare_scenes(run, scene_ids)
    return run, serialize_document(root)


def sanitize_composition(html: str, *, scene_ids: Sequence[str] | None = None) -> SanitizeResult:
    run, cleaned = sanitize_once(html, scene_ids)
    findings = list(run.findings)
    if cleaned:
        verification, _ = sanitize_once(cleaned, None)
        for finding in verification.findings:
            if finding.severity == "error" and finding.code not in PERSISTENT_CODES:
                detail = {**finding.detail, "pass": 2}
                findings.append(finding.model_copy(update={"detail": detail}))
    return SanitizeResult(
        html=cleaned,
        findings=tuple(findings),
        composition_calls=run.composition_calls,
        scene_ids=tuple(run.scene_ids),
    )
