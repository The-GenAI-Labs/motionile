import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, computed_field
from pydantic.alias_generators import to_camel

from motionile.engine.ffmpeg import FfmpegTools

REPORT_VERSION: Literal[1] = 1
MAX_NARRATION_MS = 120_000
MAX_PARALLEL_PAGES = 8
MAX_FPS = 60
MAX_CRF = 51
MIN_BROWSER_MEMORY_MB = 64


class Aspect(StrEnum):
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"
    SQUARE = "1:1"

    @property
    def label(self) -> str:
        return self.value.replace(":", "x")

    @property
    def spec(self) -> "AspectSpec":
        return ASPECT_SPECS[self]


@dataclass(frozen=True)
class Viewport:
    width: int
    height: int


@dataclass(frozen=True)
class SafeArea:
    left: int
    right: int
    top: int
    bottom: int


@dataclass(frozen=True)
class AspectSpec:
    viewport: Viewport
    safe_area: SafeArea
    text_small: int
    text_body: int
    text_subtitle: int
    text_title: int
    text_display: int
    text_code: int

    @property
    def minimum_font_px(self) -> int:
        return self.text_small

    @property
    def safe_width(self) -> int:
        return self.viewport.width - self.safe_area.left - self.safe_area.right

    @property
    def safe_height(self) -> int:
        return self.viewport.height - self.safe_area.top - self.safe_area.bottom


ASPECT_SPECS: dict[Aspect, AspectSpec] = {
    Aspect.LANDSCAPE: AspectSpec(
        viewport=Viewport(1920, 1080),
        safe_area=SafeArea(left=96, right=96, top=64, bottom=160),
        text_small=28,
        text_body=36,
        text_subtitle=48,
        text_title=72,
        text_display=120,
        text_code=30,
    ),
    Aspect.PORTRAIT: AspectSpec(
        viewport=Viewport(1080, 1920),
        safe_area=SafeArea(left=72, right=72, top=160, bottom=420),
        text_small=34,
        text_body=44,
        text_subtitle=60,
        text_title=88,
        text_display=140,
        text_code=34,
    ),
    Aspect.SQUARE: AspectSpec(
        viewport=Viewport(1080, 1080),
        safe_area=SafeArea(left=72, right=72, top=72, bottom=200),
        text_small=30,
        text_body=40,
        text_subtitle=54,
        text_title=80,
        text_display=128,
        text_code=32,
    ),
}


def default_parallel_pages() -> int:
    return max(1, min(os.cpu_count() or 1, MAX_PARALLEL_PAGES))


@dataclass(frozen=True)
class RenderEngineConfig:
    fps: int = 30
    crf: int = 20
    preset: str = "veryfast"
    parallel_pages: int = field(default_factory=default_parallel_pages)
    chunk_seconds: int = 5
    tail_ms: int = 1000
    poster_ms: int = 2000
    max_duration_ms: int = MAX_NARRATION_MS
    page_load_timeout_seconds: float = 15.0
    ready_timeout_seconds: float = 15.0
    frame_timeout_seconds: float = 10.0
    shutdown_timeout_seconds: float = 10.0
    browser_memory_mb: int = 768
    min_free_disk_mb: int = 2048
    encoder_threads: int = 4
    work_directory: Path | None = None
    tools: FfmpegTools = field(default_factory=FfmpegTools)

    def __post_init__(self) -> None:
        if not 1 <= self.fps <= MAX_FPS:
            raise ValueError(f"fps must be between 1 and {MAX_FPS}")
        if not 0 <= self.crf <= MAX_CRF:
            raise ValueError(f"crf must be between 0 and {MAX_CRF}")
        if not 1 <= self.parallel_pages <= MAX_PARALLEL_PAGES:
            raise ValueError(f"parallel_pages must be between 1 and {MAX_PARALLEL_PAGES}")
        if self.chunk_seconds < 1:
            raise ValueError("chunk_seconds must be at least 1")
        if self.tail_ms < 0 or self.poster_ms < 0:
            raise ValueError("tail_ms and poster_ms must not be negative")
        if not 1 <= self.max_duration_ms <= MAX_NARRATION_MS:
            raise ValueError(f"max_duration_ms must be between 1 and {MAX_NARRATION_MS}")
        if min(self.page_load_timeout_seconds, self.ready_timeout_seconds, self.frame_timeout_seconds) <= 0:
            raise ValueError("timeouts must be positive")
        if self.browser_memory_mb < MIN_BROWSER_MEMORY_MB:
            raise ValueError(f"browser_memory_mb must be at least {MIN_BROWSER_MEMORY_MB}")
        if self.encoder_threads < 1:
            raise ValueError("encoder_threads must be at least 1")

    @property
    def chunk_frames(self) -> int:
        return self.chunk_seconds * self.fps

    @property
    def resolved_work_directory(self) -> Path:
        return self.work_directory or Path(tempfile.gettempdir())


type Severity = Literal["error", "warning"]
type IssueKind = Literal["sanitize", "contract", "layout", "runtime"]


class IssueCode(StrEnum):
    FORBIDDEN_ELEMENT = "forbidden_element"
    FORBIDDEN_ATTRIBUTE = "forbidden_attribute"
    FORBIDDEN_URL = "forbidden_url"
    HTML_TOO_LARGE = "html_too_large"
    DATA_URIS_TOO_LARGE = "data_uris_too_large"
    TOO_MANY_ELEMENTS = "too_many_elements"
    INVALID_DATA_URI = "invalid_data_uri"
    SCRIPT_API = "script_api"
    COMPOSITION_MULTIPLE = "composition_multiple"
    PARSE_ERROR = "parse_error"
    COMPOSITION_MISSING = "composition_missing"
    SCENE_MISMATCH = "scene_mismatch"
    SCENE_ELEMENT_MISSING = "scene_element_missing"
    ASPECT_UNSUPPORTED = "aspect_unsupported"
    DURATION_MISMATCH = "duration_mismatch"
    SCENE_BOUNDARY_MISMATCH = "scene_boundary_mismatch"
    SCENE_OVERFLOW = "scene_overflow"
    NON_DETERMINISTIC_STATE = "non_deterministic_state"
    TEXT_OVERFLOW = "text_overflow"
    SAFE_AREA_VIOLATION = "safe_area_violation"
    TEXT_OVERLAP = "text_overlap"
    FONT_TOO_SMALL = "font_too_small"
    CONTRAST_LOW = "contrast_low"
    ELEMENT_OFFSCREEN = "element_offscreen"
    EMPTY_SCENE = "empty_scene"
    NETWORK_VIOLATION = "network_violation"
    TIMEOUT = "timeout"
    PAGE_ERROR = "page_error"
    BROWSER_CRASH = "browser_crash"


ISSUE_CATALOG: dict[IssueCode, tuple[Severity, IssueKind]] = {
    IssueCode.FORBIDDEN_ELEMENT: ("error", "sanitize"),
    IssueCode.FORBIDDEN_ATTRIBUTE: ("error", "sanitize"),
    IssueCode.FORBIDDEN_URL: ("error", "sanitize"),
    IssueCode.HTML_TOO_LARGE: ("error", "sanitize"),
    IssueCode.DATA_URIS_TOO_LARGE: ("error", "sanitize"),
    IssueCode.TOO_MANY_ELEMENTS: ("error", "sanitize"),
    IssueCode.INVALID_DATA_URI: ("error", "sanitize"),
    IssueCode.SCRIPT_API: ("warning", "sanitize"),
    IssueCode.COMPOSITION_MULTIPLE: ("error", "sanitize"),
    IssueCode.PARSE_ERROR: ("warning", "sanitize"),
    IssueCode.COMPOSITION_MISSING: ("error", "contract"),
    IssueCode.SCENE_MISMATCH: ("error", "contract"),
    IssueCode.SCENE_ELEMENT_MISSING: ("error", "contract"),
    IssueCode.ASPECT_UNSUPPORTED: ("error", "contract"),
    IssueCode.DURATION_MISMATCH: ("error", "contract"),
    IssueCode.SCENE_BOUNDARY_MISMATCH: ("error", "contract"),
    IssueCode.SCENE_OVERFLOW: ("error", "contract"),
    IssueCode.NON_DETERMINISTIC_STATE: ("error", "runtime"),
    IssueCode.TEXT_OVERFLOW: ("error", "layout"),
    IssueCode.SAFE_AREA_VIOLATION: ("error", "layout"),
    IssueCode.TEXT_OVERLAP: ("error", "layout"),
    IssueCode.FONT_TOO_SMALL: ("error", "layout"),
    IssueCode.CONTRAST_LOW: ("error", "layout"),
    IssueCode.ELEMENT_OFFSCREEN: ("error", "layout"),
    IssueCode.EMPTY_SCENE: ("warning", "layout"),
    IssueCode.NETWORK_VIOLATION: ("error", "runtime"),
    IssueCode.TIMEOUT: ("error", "runtime"),
    IssueCode.PAGE_ERROR: ("error", "runtime"),
    IssueCode.BROWSER_CRASH: ("error", "runtime"),
}


class RenderModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        extra="forbid",
        frozen=True,
    )


class ValidationIssue(RenderModel):
    code: str
    severity: Severity
    kind: IssueKind
    message: str
    scene: str | None = None
    time_ms: int | None = None
    aspect: str | None = None
    selector: str | None = None
    detail: dict[str, JsonValue] = Field(default_factory=dict)


@dataclass(frozen=True)
class Where:
    scene: str | None = None
    time_ms: int | None = None
    aspect: str | None = None
    selector: str | None = None


def make_issue(
    code: IssueCode,
    message: str,
    where: Where | None = None,
    detail: dict[str, JsonValue] | None = None,
) -> ValidationIssue:
    severity, kind = ISSUE_CATALOG[code]
    location = where or Where()
    return ValidationIssue(
        code=code.value,
        severity=severity,
        kind=kind,
        message=message,
        scene=location.scene,
        time_ms=location.time_ms,
        aspect=location.aspect,
        selector=location.selector,
        detail=detail or {},
    )


class ValidationStats(RenderModel):
    scenes: int = 0
    aspects: int = 0
    samples: int = 0
    duration_ms: int = 0

    def merged_with(self, other: "ValidationStats") -> "ValidationStats":
        return ValidationStats(
            scenes=max(self.scenes, other.scenes),
            aspects=max(self.aspects, other.aspects),
            samples=self.samples + other.samples,
            duration_ms=max(self.duration_ms, other.duration_ms),
        )


class ValidationReport(RenderModel):
    version: Literal[1] = REPORT_VERSION
    issues: tuple[ValidationIssue, ...] = ()
    stats: ValidationStats = Field(default_factory=ValidationStats)

    @computed_field
    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    def with_issues(self, issues: Iterable[ValidationIssue]) -> "ValidationReport":
        return ValidationReport(issues=(*self.issues, *issues), stats=self.stats)

    def with_stats(self, stats: ValidationStats) -> "ValidationReport":
        return ValidationReport(issues=self.issues, stats=stats)

    @classmethod
    def merge(cls, *reports: "ValidationReport") -> "ValidationReport":
        issues: list[ValidationIssue] = []
        stats = ValidationStats()
        for report in reports:
            issues.extend(report.issues)
            stats = stats.merged_with(report.stats)
        return cls(issues=tuple(issues), stats=stats)


class RenderEngineError(Exception):
    code: str = "render_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SandboxError(RenderEngineError):
    code = "sandbox_error"


class NetworkViolationError(SandboxError):
    code = IssueCode.NETWORK_VIOLATION.value

    def __init__(self, violations: Iterable[str]) -> None:
        self.violations = tuple(violations)
        shown = "; ".join(self.violations[:5])
        super().__init__(f"The composition attempted {len(self.violations)} forbidden operation(s): {shown}")


class SandboxTimeoutError(SandboxError):
    code = IssueCode.TIMEOUT.value


class PageError(SandboxError):
    code = IssueCode.PAGE_ERROR.value

    def __init__(self, messages: Iterable[str]) -> None:
        self.messages = tuple(messages)
        super().__init__("; ".join(self.messages[:5]) or "The page reported an error")


class BrowserCrashError(SandboxError):
    code = IssueCode.BROWSER_CRASH.value


class CaptureCancelledError(RenderEngineError):
    code = "cancelled"


class OutputCheckError(RenderEngineError):
    code = "output_check_failed"

    def __init__(self, problems: Iterable[str]) -> None:
        self.problems = tuple(problems)
        super().__init__("; ".join(self.problems))


class InsufficientDiskError(RenderEngineError):
    code = "insufficient_disk"


class DurationLimitError(RenderEngineError):
    code = "duration_limit_exceeded"


class InvalidCompositionError(RenderEngineError):
    code = "invalid_composition"

    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        summary = ", ".join(sorted({issue.code for issue in self.issues}))
        super().__init__(f"The composition is invalid: {summary}")


def issue_from_error(error: SandboxError, *, aspect: str | None = None) -> ValidationIssue:
    details: dict[str, JsonValue] = {}
    if isinstance(error, PageError):
        details["messages"] = list(error.messages)
    if isinstance(error, NetworkViolationError):
        details["violations"] = list(error.violations)
    return make_issue(IssueCode(error.code), error.message, Where(aspect=aspect), details)
