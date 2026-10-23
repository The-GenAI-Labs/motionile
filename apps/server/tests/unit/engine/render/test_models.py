import json
from dataclasses import replace

import pytest

from motionile.engine.render.models import (
    ASPECT_SPECS,
    Aspect,
    BrowserCrashError,
    CaptureCancelledError,
    DurationLimitError,
    InsufficientDiskError,
    InvalidCompositionError,
    IssueCode,
    NetworkViolationError,
    OutputCheckError,
    PageError,
    RenderEngineConfig,
    SandboxError,
    SandboxTimeoutError,
    ValidationReport,
    ValidationStats,
    Where,
    issue_from_error,
    make_issue,
)


def test_aspect_specs_match_the_documented_tables() -> None:
    landscape = ASPECT_SPECS[Aspect.LANDSCAPE]
    portrait = ASPECT_SPECS[Aspect.PORTRAIT]
    square = ASPECT_SPECS[Aspect.SQUARE]

    assert (landscape.viewport.width, landscape.viewport.height) == (1920, 1080)
    assert (portrait.viewport.width, portrait.viewport.height) == (1080, 1920)
    assert (square.viewport.width, square.viewport.height) == (1080, 1080)
    assert (landscape.safe_area.left, landscape.safe_area.top, landscape.safe_area.bottom) == (96, 64, 160)
    assert (portrait.safe_area.left, portrait.safe_area.top, portrait.safe_area.bottom) == (72, 160, 420)
    assert (square.safe_area.left, square.safe_area.top, square.safe_area.bottom) == (72, 72, 200)
    assert [spec.minimum_font_px for spec in (landscape, portrait, square)] == [28, 34, 30]
    assert [spec.text_title for spec in (landscape, portrait, square)] == [72, 88, 80]
    assert [spec.text_display for spec in (landscape, portrait, square)] == [120, 140, 128]
    assert [spec.text_code for spec in (landscape, portrait, square)] == [30, 34, 32]


def test_aspect_labels_use_x_instead_of_a_colon() -> None:
    assert [aspect.label for aspect in Aspect] == ["16x9", "9x16", "1x1"]


def test_safe_area_dimensions() -> None:
    landscape = Aspect.LANDSCAPE.spec

    assert landscape.safe_width == 1920 - 96 - 96
    assert landscape.safe_height == 1080 - 64 - 160


def test_report_is_valid_without_errors_and_serializes_to_camel_case() -> None:
    warning = make_issue(IssueCode.EMPTY_SCENE, "empty", Where(scene="intro", time_ms=100, aspect="16:9"))
    report = ValidationReport(issues=(warning,), stats=ValidationStats(scenes=1, aspects=1, samples=3, duration_ms=900))

    document = json.loads(report.model_dump_json(by_alias=True))

    assert report.valid is True
    assert document["valid"] is True
    assert document["version"] == 1
    assert document["stats"] == {"scenes": 1, "aspects": 1, "samples": 3, "durationMs": 900}
    assert document["issues"][0]["timeMs"] == 100
    assert document["issues"][0]["severity"] == "warning"
    assert document["issues"][0]["kind"] == "layout"


def test_report_with_an_error_is_invalid_and_exposes_errors_and_warnings() -> None:
    error = make_issue(IssueCode.FONT_TOO_SMALL, "small")
    warning = make_issue(IssueCode.PARSE_ERROR, "parse")
    report = ValidationReport(issues=(error, warning))

    assert report.valid is False
    assert report.errors == (error,)
    assert report.warnings == (warning,)


def test_merge_combines_issues_and_stats() -> None:
    first = ValidationReport(
        issues=(make_issue(IssueCode.SCRIPT_API, "a"),),
        stats=ValidationStats(scenes=2, aspects=1, samples=4, duration_ms=10),
    )
    second = ValidationReport(
        issues=(make_issue(IssueCode.TEXT_OVERLAP, "b"),),
        stats=ValidationStats(scenes=3, aspects=2, samples=5, duration_ms=8),
    )

    merged = ValidationReport.merge(first, second)

    assert [issue.code for issue in merged.issues] == ["script_api", "text_overlap"]
    assert merged.stats == ValidationStats(scenes=3, aspects=2, samples=9, duration_ms=10)


@pytest.mark.parametrize(
    ("code", "severity", "kind"),
    [
        (IssueCode.FORBIDDEN_ELEMENT, "error", "sanitize"),
        (IssueCode.SCRIPT_API, "warning", "sanitize"),
        (IssueCode.PARSE_ERROR, "warning", "sanitize"),
        (IssueCode.COMPOSITION_MISSING, "error", "contract"),
        (IssueCode.NON_DETERMINISTIC_STATE, "error", "runtime"),
        (IssueCode.CONTRAST_LOW, "error", "layout"),
        (IssueCode.EMPTY_SCENE, "warning", "layout"),
        (IssueCode.NETWORK_VIOLATION, "error", "runtime"),
    ],
)
def test_issue_catalog_severity_and_kind(code: IssueCode, severity: str, kind: str) -> None:
    issue = make_issue(code, "message")

    assert (issue.severity, issue.kind) == (severity, kind)


def test_every_documented_code_is_in_the_catalog() -> None:
    documented = {
        "forbidden_element",
        "forbidden_attribute",
        "forbidden_url",
        "html_too_large",
        "data_uris_too_large",
        "too_many_elements",
        "invalid_data_uri",
        "script_api",
        "composition_multiple",
        "parse_error",
        "composition_missing",
        "scene_mismatch",
        "scene_element_missing",
        "aspect_unsupported",
        "duration_mismatch",
        "scene_boundary_mismatch",
        "scene_overflow",
        "non_deterministic_state",
        "text_overflow",
        "safe_area_violation",
        "text_overlap",
        "font_too_small",
        "contrast_low",
        "element_offscreen",
        "empty_scene",
        "network_violation",
        "timeout",
        "page_error",
        "browser_crash",
    }

    assert documented == {code.value for code in IssueCode}


def test_error_types_carry_stable_codes() -> None:
    assert NetworkViolationError(["GET http://x"]).code == "network_violation"
    assert SandboxTimeoutError("slow").code == "timeout"
    assert PageError(["boom"]).code == "page_error"
    assert BrowserCrashError("crash").code == "browser_crash"
    assert CaptureCancelledError("stop").code == "cancelled"
    assert OutputCheckError(["bad"]).code == "output_check_failed"
    assert InsufficientDiskError("full").code == "insufficient_disk"
    assert DurationLimitError("long").code == "duration_limit_exceeded"
    assert InvalidCompositionError([make_issue(IssueCode.FORBIDDEN_URL, "u")]).code == "invalid_composition"
    assert issubclass(NetworkViolationError, SandboxError)


def test_error_messages_list_the_details() -> None:
    assert "GET http://a" in str(NetworkViolationError(["GET http://a", "GET http://b"]))
    assert str(PageError(["first", "second"])) == "first; second"
    assert "forbidden_url" in str(InvalidCompositionError([make_issue(IssueCode.FORBIDDEN_URL, "u")]))


def test_issue_from_error_keeps_the_details() -> None:
    issue = issue_from_error(PageError(["boom"]), aspect="16:9")

    assert issue.code == "page_error"
    assert issue.aspect == "16:9"
    assert issue.detail == {"messages": ["boom"]}


def test_config_defaults_match_the_documented_values() -> None:
    config = RenderEngineConfig()

    assert (config.fps, config.crf, config.preset) == (30, 20, "veryfast")
    assert (config.chunk_seconds, config.tail_ms, config.poster_ms) == (5, 1000, 2000)
    assert config.max_duration_ms == 120_000
    assert (config.page_load_timeout_seconds, config.ready_timeout_seconds, config.frame_timeout_seconds) == (
        15,
        15,
        10,
    )
    assert config.browser_memory_mb == 768
    assert config.min_free_disk_mb == 2048
    assert config.chunk_frames == 150
    assert 1 <= config.parallel_pages <= 8


@pytest.mark.parametrize(
    "overrides",
    [
        {"fps": 0},
        {"fps": 61},
        {"crf": 52},
        {"parallel_pages": 0},
        {"parallel_pages": 9},
        {"chunk_seconds": 0},
        {"tail_ms": -1},
        {"max_duration_ms": 120_001},
        {"frame_timeout_seconds": 0},
        {"browser_memory_mb": 10},
        {"encoder_threads": 0},
    ],
)
def test_config_rejects_out_of_range_values(overrides: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="must"):
        replace(RenderEngineConfig(), **overrides)
