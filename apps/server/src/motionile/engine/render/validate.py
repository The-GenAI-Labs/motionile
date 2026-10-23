import asyncio
import hashlib
import io
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from PIL import Image

from motionile.engine.audio.narration_models import NarrationDocument, NarrationScene
from motionile.engine.render.models import (
    Aspect,
    AspectSpec,
    CaptureCancelledError,
    IssueCode,
    ValidationIssue,
    ValidationReport,
    ValidationStats,
    Where,
    make_issue,
)
from motionile.engine.render.sandbox import CompositionInfo, PageSpec, load_browser_expression

SAMPLE_EDGE_MS = 50
FRAME_MS = 33
CONTRACT_TOLERANCE_MS = 50
OVERFLOW_TOLERANCE_PX = 2.0
SAFE_AREA_TOLERANCE_PX = 1.0
OVERLAP_THRESHOLD_PX2 = 16.0
VISIBLE_OPACITY = 0.05
ANIMATION_RECT_TOLERANCE_PX = 0.5
ANIMATION_OPACITY_TOLERANCE = 0.01
OFFSCREEN_VISIBLE_FRACTION = 0.9
CONTRAST_NORMAL = 4.5
CONTRAST_LARGE = 3.0
LARGE_TEXT_PX = 24.0
LARGE_BOLD_TEXT_PX = 18.66
BOLD_WEIGHT = 700
CONTRAST_SAMPLE_COLUMNS = 40
CONTRAST_SAMPLE_ROWS = 10
CONTRAST_PERCENTILE = 0.01
BLANK_CHANNEL_SPREAD = 2
SRGB_THRESHOLD = 0.04045
TEXT_TRANSPARENT_STYLE = (
    "*, *::before, *::after { color: transparent !important; -webkit-text-fill-color: transparent !important; "
    "text-shadow: none !important; -webkit-text-stroke: 0 !important; caret-color: transparent !important; } "
    "svg text, svg tspan { fill: transparent !important; stroke: none !important; }"
)
STYLE_ON = (
    "(css) => { const style = document.createElement('style'); style.id = '__mo_probe_style'; "
    "style.textContent = css; document.head.append(style); }"
)
STYLE_OFF = "() => { document.getElementById('__mo_probe_style')?.remove(); }"


class ValidationPage(Protocol):
    composition: CompositionInfo | None

    async def settle_at(self, time_ms: float) -> None: ...

    async def capture_at(self, time_ms: float) -> bytes: ...

    async def screenshot(self) -> bytes: ...

    async def evaluate(self, expression: str, argument: object = None, *, what: str = ...) -> Any: ...

    async def close(self) -> None: ...


class ValidationPageOpener(Protocol):
    async def open_page(self, spec: PageSpec) -> ValidationPage: ...


type CancelCheck = Callable[[], Awaitable[bool]]


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def area(self) -> float:
        return max(0.0, self.width) * max(0.0, self.height)

    def intersection_area(self, other: "Rect") -> float:
        width = min(self.right, other.right) - max(self.x, other.x)
        height = min(self.bottom, other.bottom) - max(self.y, other.y)
        return max(0.0, width) * max(0.0, height)


@dataclass(frozen=True)
class Rgba:
    r: int
    g: int
    b: int
    a: float


@dataclass(frozen=True)
class TextItem:
    index: int
    selector: str
    scene: str | None
    rect: Rect
    line_rects: tuple[Rect, ...]
    element_rect: Rect
    font_size_px: float
    font_weight: int
    fill: Rgba
    clip_text: bool
    opacity: float
    visible: bool
    overflow_x: float
    overflow_y: float
    important: bool
    text: str

    @property
    def shown(self) -> bool:
        return self.visible and self.opacity >= VISIBLE_OPACITY and self.rect.area > 0


@dataclass(frozen=True)
class ImportantItem:
    index: int
    selector: str
    rect: Rect
    opacity: float
    visible: bool

    @property
    def shown(self) -> bool:
        return self.visible and self.opacity >= VISIBLE_OPACITY


@dataclass(frozen=True)
class Probe:
    texts: tuple[TextItem, ...]
    important: tuple[ImportantItem, ...]


def parse_rect(raw: dict[str, Any]) -> Rect:
    return Rect(float(raw["x"]), float(raw["y"]), float(raw["width"]), float(raw["height"]))


def parse_text_item(raw: dict[str, Any]) -> TextItem:
    fill = cast("dict[str, Any]", raw["fill"])
    return TextItem(
        index=int(raw["index"]),
        selector=str(raw["selector"]),
        scene=None if raw["scene"] is None else str(raw["scene"]),
        rect=parse_rect(raw["rect"]),
        line_rects=tuple(parse_rect(line) for line in cast("list[dict[str, Any]]", raw["lineRects"])),
        element_rect=parse_rect(raw["elementRect"]),
        font_size_px=float(raw["fontSizePx"]),
        font_weight=int(raw["fontWeight"]),
        fill=Rgba(int(fill["r"]), int(fill["g"]), int(fill["b"]), float(fill["a"])),
        clip_text=bool(raw["clipText"]),
        opacity=float(raw["opacity"]),
        visible=bool(raw["visible"]),
        overflow_x=float(raw["overflowX"]),
        overflow_y=float(raw["overflowY"]),
        important=bool(raw["important"]),
        text=str(raw["text"]),
    )


def parse_important_item(raw: dict[str, Any]) -> ImportantItem:
    return ImportantItem(
        index=int(raw["index"]),
        selector=str(raw["selector"]),
        rect=parse_rect(raw["rect"]),
        opacity=float(raw["opacity"]),
        visible=bool(raw["visible"]),
    )


def parse_probe(raw: dict[str, Any]) -> Probe:
    return Probe(
        texts=tuple(parse_text_item(item) for item in cast("list[dict[str, Any]]", raw["texts"])),
        important=tuple(parse_important_item(item) for item in cast("list[dict[str, Any]]", raw["important"])),
    )


def rect_moved(first: Rect, second: Rect) -> bool:
    return any(
        abs(a - b) > ANIMATION_RECT_TOLERANCE_PX
        for a, b in (
            (first.x, second.x),
            (first.y, second.y),
            (first.width, second.width),
            (first.height, second.height),
        )
    )


def animating_keys(first: Probe, second: Probe) -> frozenset[str]:
    if len(first.texts) != len(second.texts) or len(first.important) != len(second.important):
        return frozenset({item.selector for item in (*first.texts, *first.important)})
    moving: set[str] = set()
    for before, after in zip(first.texts, second.texts, strict=True):
        if (
            rect_moved(before.rect, after.rect)
            or abs(before.opacity - after.opacity) > ANIMATION_OPACITY_TOLERANCE
            or before.visible != after.visible
        ):
            moving.add(before.selector)
    for before_important, after_important in zip(first.important, second.important, strict=True):
        if (
            rect_moved(before_important.rect, after_important.rect)
            or abs(before_important.opacity - after_important.opacity) > ANIMATION_OPACITY_TOLERANCE
        ):
            moving.add(before_important.selector)
    return frozenset(moving)


def srgb_to_linear(channel: int) -> float:
    value = channel / 255
    return value / 12.92 if value <= SRGB_THRESHOLD else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(red: float, green: float, blue: float) -> float:
    return (
        0.2126 * srgb_to_linear(round(red))
        + 0.7152 * srgb_to_linear(round(green))
        + 0.0722 * srgb_to_linear(round(blue))
    )


def contrast_ratio(first: float, second: float) -> float:
    lighter, darker = (first, second) if first >= second else (second, first)
    return (lighter + 0.05) / (darker + 0.05)


def required_contrast(item: TextItem) -> float:
    large = item.font_size_px >= LARGE_TEXT_PX or (
        item.font_size_px >= LARGE_BOLD_TEXT_PX and item.font_weight >= BOLD_WEIGHT
    )
    return CONTRAST_LARGE if large else CONTRAST_NORMAL


def pixel_contrast(fill: Rgba, opacity: float, background: tuple[int, int, int]) -> float:
    alpha = max(0.0, min(1.0, fill.a * opacity))
    red = fill.r * alpha + background[0] * (1 - alpha)
    green = fill.g * alpha + background[1] * (1 - alpha)
    blue = fill.b * alpha + background[2] * (1 - alpha)
    text_luminance = relative_luminance(red, green, blue)
    return contrast_ratio(text_luminance, relative_luminance(*background))


def sampled_pixels(region: Image.Image) -> list[tuple[int, int, int]]:
    width, height = region.size
    columns = min(width, CONTRAST_SAMPLE_COLUMNS)
    rows = min(height, CONTRAST_SAMPLE_ROWS)
    data = region.tobytes()
    pixels: list[tuple[int, int, int]] = []
    for row in range(rows):
        for column in range(columns):
            offset = ((row * height // rows) * width + column * width // columns) * 3
            pixels.append((data[offset], data[offset + 1], data[offset + 2]))
    return pixels


def item_contrast(image: Image.Image, item: TextItem) -> float | None:
    left = max(0, int(item.rect.x))
    top = max(0, int(item.rect.y))
    right = min(image.width, int(item.rect.right) + 1)
    bottom = min(image.height, int(item.rect.bottom) + 1)
    if right <= left or bottom <= top:
        return None
    pixels = sampled_pixels(image.crop((left, top, right, bottom)))
    ratios = sorted(pixel_contrast(item.fill, item.opacity, pixel) for pixel in pixels)
    return ratios[int(len(ratios) * CONTRAST_PERCENTILE)]


def analyze_contrast(png: bytes, items: Iterable[TextItem]) -> dict[int, float]:
    with Image.open(io.BytesIO(png)) as opened:
        image = opened.convert("RGB")
    ratios: dict[int, float] = {}
    for item in items:
        ratio = item_contrast(image, item)
        if ratio is not None:
            ratios[item.index] = ratio
    return ratios


def is_blank(png: bytes) -> bool:
    with Image.open(io.BytesIO(png)) as opened:
        extrema = cast("Sequence[tuple[int, int]]", opened.convert("RGB").getextrema())
    return all(high - low <= BLANK_CHANNEL_SPREAD for low, high in extrema)


def sample_times(scene: NarrationScene) -> tuple[int, int, int]:
    middle = scene.start_ms + scene.duration_ms // 2
    start = min(scene.start_ms + SAMPLE_EDGE_MS, middle)
    end = max(scene.end_ms - SAMPLE_EDGE_MS, middle)
    return start, middle, end


def contract_issues(
    info: CompositionInfo | None, narration: NarrationDocument, aspect: Aspect
) -> list[ValidationIssue]:
    where = Where(aspect=aspect.value)
    if info is None:
        return [
            make_issue(
                IssueCode.COMPOSITION_MISSING,
                "window.__timeline or window.__composition does not exist once __ready resolved",
                where,
            )
        ]
    issues: list[ValidationIssue] = []
    expected_ids = [scene.id for scene in narration.scenes]
    actual_ids = [scene.id for scene in info.scenes]
    if actual_ids != expected_ids:
        issues.append(
            make_issue(
                IssueCode.SCENE_MISMATCH,
                "The composition's scene IDs differ from the narration's",
                where,
                {"expected": list(expected_ids), "actual": list(actual_ids)},
            )
        )
    issues.extend(
        make_issue(
            IssueCode.SCENE_ELEMENT_MISSING,
            f'No element has data-scene="{scene_id}"',
            Where(scene=scene_id, aspect=aspect.value),
        )
        for scene_id in expected_ids
        if scene_id not in info.scene_elements
    )
    if aspect.value not in info.aspects:
        issues.append(
            make_issue(
                IssueCode.ASPECT_UNSUPPORTED,
                f"The composition does not support {aspect.value}",
                where,
                {"supported": list(info.aspects)},
            )
        )
    issues.extend(timing_issues(info, narration, aspect))
    return issues


def timing_issues(info: CompositionInfo, narration: NarrationDocument, aspect: Aspect) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    longest = max(info.timeline_duration_ms, info.duration_ms)
    if abs(longest - narration.total_duration_ms) > CONTRACT_TOLERANCE_MS:
        issues.append(
            make_issue(
                IssueCode.DURATION_MISMATCH,
                f"The timeline lasts {longest} ms; the narration lasts {narration.total_duration_ms} ms",
                Where(aspect=aspect.value),
                {"timelineMs": longest, "narrationMs": narration.total_duration_ms},
            )
        )
    by_id = {scene.id: scene for scene in info.scenes}
    for expected in narration.scenes:
        actual = by_id.get(expected.id)
        if actual is None:
            continue
        where = Where(scene=expected.id, aspect=aspect.value)
        if (
            abs(actual.start_ms - expected.start_ms) > CONTRACT_TOLERANCE_MS
            or abs(actual.end_ms - expected.end_ms) > CONTRACT_TOLERANCE_MS
        ):
            issues.append(
                make_issue(
                    IssueCode.SCENE_BOUNDARY_MISMATCH,
                    f"Scene {expected.id} runs {actual.start_ms}-{actual.end_ms} ms; the narration says "
                    f"{expected.start_ms}-{expected.end_ms} ms",
                    where,
                )
            )
        if actual.content_end_ms > expected.end_ms + CONTRACT_TOLERANCE_MS:
            issues.append(
                make_issue(
                    IssueCode.SCENE_OVERFLOW,
                    f"Scene {expected.id} animates until {actual.content_end_ms} ms but ends at {expected.end_ms} ms",
                    where,
                    {"contentEndMs": actual.content_end_ms, "sceneEndMs": expected.end_ms},
                )
            )
    return issues


def fraction_inside(rect: Rect, width: int, height: int) -> float:
    if rect.area == 0:
        return 1.0
    return rect.intersection_area(Rect(0, 0, width, height)) / rect.area


def outside_safe_area(rect: Rect, spec: AspectSpec) -> bool:
    safe = spec.safe_area
    return (
        rect.x < safe.left - SAFE_AREA_TOLERANCE_PX
        or rect.y < safe.top - SAFE_AREA_TOLERANCE_PX
        or rect.right > spec.viewport.width - safe.right + SAFE_AREA_TOLERANCE_PX
        or rect.bottom > spec.viewport.height - safe.bottom + SAFE_AREA_TOLERANCE_PX
    )


def is_ancestor_selector(parent: str, child: str) -> bool:
    return child.startswith(parent + " > ")


def overlap_area(first: TextItem, second: TextItem) -> float:
    return sum(a.intersection_area(b) for a in first.line_rects for b in second.line_rects)


@dataclass(frozen=True)
class SampleContext:
    aspect: Aspect
    scene: str
    time_ms: int

    def where(self, selector: str | None = None) -> Where:
        return Where(scene=self.scene, time_ms=self.time_ms, aspect=self.aspect.value, selector=selector)


def text_item_issues(
    item: TextItem, context: SampleContext, spec: AspectSpec, contrast: float | None
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    where = context.where(item.selector)
    minimum = spec.minimum_font_px
    if item.font_size_px < minimum - 0.01:
        issues.append(
            make_issue(
                IssueCode.FONT_TOO_SMALL,
                f"Text is {item.font_size_px:g}px; the minimum for {context.aspect.value} is {minimum}px",
                where,
                {"fontSizePx": item.font_size_px, "minimumPx": minimum},
            )
        )
    if max(item.overflow_x, item.overflow_y) > OVERFLOW_TOLERANCE_PX:
        issues.append(
            make_issue(
                IssueCode.TEXT_OVERFLOW,
                "Text overflows its element box",
                where,
                {"overflowXPx": round(item.overflow_x, 1), "overflowYPx": round(item.overflow_y, 1)},
            )
        )
    if outside_safe_area(item.rect, spec):
        issues.append(
            make_issue(
                IssueCode.SAFE_AREA_VIOLATION,
                "Text extends outside the safe area",
                where,
                {
                    "x": round(item.rect.x),
                    "y": round(item.rect.y),
                    "right": round(item.rect.right),
                    "bottom": round(item.rect.bottom),
                },
            )
        )
    if fraction_inside(item.rect, spec.viewport.width, spec.viewport.height) < OFFSCREEN_VISIBLE_FRACTION:
        issues.append(make_issue(IssueCode.ELEMENT_OFFSCREEN, "Text lies outside the viewport", where))
    required = required_contrast(item)
    if contrast is not None and contrast < required:
        issues.append(
            make_issue(
                IssueCode.CONTRAST_LOW,
                f"Text contrast is {contrast:.2f}:1; WCAG AA needs {required}:1",
                where,
                {"ratio": round(contrast, 2), "required": required},
            )
        )
    return issues


def layout_issues(
    probe: Probe,
    moving: frozenset[str],
    context: SampleContext,
    spec: AspectSpec,
    contrast: dict[int, float],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    settled = [item for item in probe.texts if item.shown and item.selector not in moving]
    for item in settled:
        issues.extend(text_item_issues(item, context, spec, contrast.get(item.index)))
    for position, first in enumerate(settled):
        for second in settled[position + 1 :]:
            if is_ancestor_selector(first.selector, second.selector) or is_ancestor_selector(
                second.selector, first.selector
            ):
                continue
            area = overlap_area(first, second)
            if area > OVERLAP_THRESHOLD_PX2:
                issues.append(
                    make_issue(
                        IssueCode.TEXT_OVERLAP,
                        f"Text in {first.selector} overlaps text in {second.selector}",
                        context.where(first.selector),
                        {"other": second.selector, "areaPx2": round(area)},
                    )
                )
    for important in probe.important:
        if not important.shown or important.selector in moving:
            continue
        if fraction_inside(important.rect, spec.viewport.width, spec.viewport.height) < OFFSCREEN_VISIBLE_FRACTION:
            issues.append(
                make_issue(
                    IssueCode.ELEMENT_OFFSCREEN,
                    "An important element lies outside the viewport",
                    context.where(important.selector),
                )
            )
    return issues


def deduplicate(issues: Iterable[ValidationIssue]) -> tuple[ValidationIssue, ...]:
    seen: dict[tuple[str, str | None, str | None, str | None, str], ValidationIssue] = {}
    for issue in issues:
        other = cast("str", issue.detail.get("other", ""))
        key = (issue.code, issue.scene, issue.aspect, issue.selector, other if issue.selector else issue.message)
        seen.setdefault(key, issue)
    return tuple(seen.values())


@dataclass
class ValidationRun:
    narration: NarrationDocument
    frame_ms: int
    should_cancel: CancelCheck | None
    script: str
    issues: list[ValidationIssue] = field(default_factory=list[ValidationIssue])
    samples: int = 0

    async def checkpoint(self) -> None:
        if self.should_cancel is not None and await self.should_cancel():
            raise CaptureCancelledError("The validation was cancelled")


async def run_probe(page: ValidationPage, script: str) -> Probe:
    return parse_probe(cast("dict[str, Any]", await page.evaluate(script, what="Probing the layout")))


async def contrast_by_item(
    page: ValidationPage, probe: Probe, moving: frozenset[str], time_ms: int
) -> dict[int, float]:
    candidates = [item for item in probe.texts if item.shown and item.selector not in moving and not item.clip_text]
    if not candidates:
        return {}
    await page.evaluate(STYLE_ON, TEXT_TRANSPARENT_STYLE, what="Hiding text for the contrast check")
    try:
        await page.settle_at(time_ms)
        png = await page.screenshot()
    finally:
        await page.evaluate(STYLE_OFF, what="Restoring text after the contrast check")
    return await asyncio.to_thread(analyze_contrast, png, candidates)


async def sample_scene(
    page: ValidationPage,
    run: ValidationRun,
    context: SampleContext,
    *,
    is_middle: bool,
) -> bytes | None:
    spec = context.aspect.spec
    script = run.script
    await run.checkpoint()
    await page.settle_at(context.time_ms)
    first = await run_probe(page, script)
    await page.settle_at(context.time_ms + run.frame_ms)
    second = await run_probe(page, script)
    await page.settle_at(context.time_ms)
    moving = animating_keys(first, second)
    picture = await page.screenshot() if is_middle else None
    contrast = await contrast_by_item(page, first, moving, context.time_ms)
    run.samples += 1
    run.issues.extend(layout_issues(first, moving, context, spec, contrast))
    if (
        is_middle
        and picture is not None
        and not any(item.shown for item in first.texts)
        and await asyncio.to_thread(is_blank, picture)
    ):
        run.issues.append(
            make_issue(IssueCode.EMPTY_SCENE, "The middle of the scene shows no visible content", context.where())
        )
    return picture


async def check_determinism(
    page: ValidationPage, run: ValidationRun, scene: NarrationScene, aspect: Aspect, first_picture: bytes
) -> None:
    start, middle, _ = sample_times(scene)
    await page.settle_at(start)
    second_picture = await page.capture_at(middle)
    if hashlib.sha256(first_picture).digest() != hashlib.sha256(second_picture).digest():
        run.issues.append(
            make_issue(
                IssueCode.NON_DETERMINISTIC_STATE,
                "Two samples at the same time, taken in a different order, produce different pixels",
                Where(scene=scene.id, time_ms=middle, aspect=aspect.value),
            )
        )


async def validate_scene(page: ValidationPage, run: ValidationRun, scene: NarrationScene, aspect: Aspect) -> None:
    start, middle, end = sample_times(scene)
    await sample_scene(page, run, SampleContext(aspect, scene.id, start), is_middle=False)
    picture = await sample_scene(page, run, SampleContext(aspect, scene.id, middle), is_middle=True)
    if picture is not None:
        await check_determinism(page, run, scene, aspect, picture)
    await sample_scene(page, run, SampleContext(aspect, scene.id, end), is_middle=False)


async def validate_aspect(
    opener: ValidationPageOpener,
    run: ValidationRun,
    html: str,
    aspect: Aspect,
    seed: int,
) -> None:
    page = await opener.open_page(PageSpec(html=html, narration=run.narration, aspect=aspect, seed=seed))
    try:
        contract = contract_issues(page.composition, run.narration, aspect)
        run.issues.extend(contract)
        if any(issue.severity == "error" for issue in contract):
            return
        for scene in run.narration.scenes:
            await validate_scene(page, run, scene, aspect)
    finally:
        await page.close()


async def validate_composition(  # noqa: PLR0913
    sandbox: ValidationPageOpener,
    html: str,
    narration: NarrationDocument,
    aspects: Sequence[Aspect],
    *,
    seed: int,
    should_cancel: CancelCheck | None = None,
) -> ValidationReport:
    run = ValidationRun(
        narration=narration,
        frame_ms=FRAME_MS,
        should_cancel=should_cancel,
        script=load_browser_expression("layout_probe.js"),
    )
    for aspect in aspects:
        await run.checkpoint()
        await validate_aspect(sandbox, run, html, aspect, seed)
    stats = ValidationStats(
        scenes=len(narration.scenes),
        aspects=len(aspects),
        samples=run.samples,
        duration_ms=narration.total_duration_ms,
    )
    return ValidationReport(issues=deduplicate(run.issues), stats=stats)
