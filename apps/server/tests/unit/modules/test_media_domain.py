import re
from enum import StrEnum
from itertools import product
from pathlib import Path

import pytest

from motionile.modules.media.domain import (
    ACTIVE_RENDER_STATUSES,
    INITIAL_RENDER_STATUS,
    RENDER_PIPELINE,
    RENDER_TRANSITIONS,
    STAGE_PROGRESS_WEIGHTS,
    TERMINAL_RENDER_STATUSES,
    Aspect,
    AssetKind,
    AssetStatus,
    InvalidRenderTransitionError,
    RenderFailureCode,
    RenderSource,
    RenderStage,
    RenderStatus,
    RenditionStatus,
    TtsProvider,
    can_transition,
    following_status,
    is_terminal,
    require_transition,
)
from motionile.modules.voices.domain import VoiceFailureCode, VoiceKind, VoiceProvider, VoiceStatus

STATE_MACHINES_DOC = Path(__file__).resolve().parents[5] / "docs" / "db" / "state-machines.md"
SCHEMA_DOC = Path(__file__).resolve().parents[5] / "docs" / "db" / "schema.md"
EDGE = re.compile(r"^\s*(\[\*\]|\w+) --> (\[\*\]|\w+)")
PIPELINE_ORDER = ("preparing", "voicing", "mixing", "capturing", "encoding", "finalizing")

type Edges = set[tuple[str, str]]


def documented_edges() -> tuple[Edges, set[str]]:
    text = STATE_MACHINES_DOC.read_text(encoding="utf-8")
    block = re.search(r"```mermaid\n(.*?)```", text[text.index("## `renders.status`") :], re.DOTALL)
    assert block is not None
    edges: Edges = set()
    initial: set[str] = set()
    for line in block.group(1).splitlines():
        match = EDGE.match(line)
        if match is None:
            continue
        source, target = match.groups()
        if source == "[*]":
            initial.add(target)
        elif target != "[*]":
            edges.add((source, target))
    return edges, initial


def documented_values(table: str, constraint: str) -> set[str]:
    text = SCHEMA_DOC.read_text(encoding="utf-8")
    section = text[text.index(f"### `{table}`") :]
    match = re.search(rf"`{constraint}`: `[^`]*? IN \(([^)]*)\)", section)
    assert match is not None
    return set(re.findall(r"'([^']+)'", match.group(1)))


def test_the_transition_table_matches_the_documented_diagram() -> None:
    edges, initial = documented_edges()

    assert {
        (source.value, target.value) for source, targets in RENDER_TRANSITIONS.items() for target in targets
    } == edges
    assert {INITIAL_RENDER_STATUS.value} == initial


@pytest.mark.parametrize(("current", "target"), list(product(RenderStatus, RenderStatus)))
def test_every_transition_is_allowed_or_rejected_as_documented(current: RenderStatus, target: RenderStatus) -> None:
    edges, _ = documented_edges()
    allowed = (current.value, target.value) in edges

    assert can_transition(current, target) is allowed
    if allowed:
        require_transition(current, target)
    else:
        with pytest.raises(InvalidRenderTransitionError, match=f"cannot move from {current.value} to {target.value}"):
            require_transition(current, target)


def test_every_status_has_an_entry_in_the_transition_table() -> None:
    assert set(RENDER_TRANSITIONS) == set(RenderStatus)


def test_terminal_statuses_have_no_way_out() -> None:
    assert {RenderStatus.COMPLETED, RenderStatus.FAILED, RenderStatus.CANCELLED} == TERMINAL_RENDER_STATUSES
    for status in RenderStatus:
        assert is_terminal(status) is (status in TERMINAL_RENDER_STATUSES)
        assert (RENDER_TRANSITIONS[status] == frozenset()) is is_terminal(status)
    assert set(RenderStatus) - TERMINAL_RENDER_STATUSES == ACTIVE_RENDER_STATUSES


def test_every_active_status_can_fail_and_be_cancelled_except_nothing_else_skips_a_stage() -> None:
    for status in ACTIVE_RENDER_STATUSES:
        assert RenderStatus.CANCELLED in RENDER_TRANSITIONS[status]
        assert RenderStatus.FAILED in RENDER_TRANSITIONS[status]
        assert len(RENDER_TRANSITIONS[status]) == 3


def test_a_render_starts_queued_and_walks_the_pipeline_in_order() -> None:
    status = INITIAL_RENDER_STATUS
    visited: list[str] = []
    while (following := following_status(status)) is not None:
        require_transition(status, following)
        visited.append(following.value)
        status = following

    assert visited == [*PIPELINE_ORDER, "completed"]


@pytest.mark.parametrize("status", [RenderStatus.COMPLETED, RenderStatus.FAILED, RenderStatus.CANCELLED])
def test_terminal_statuses_have_no_following_status(status: RenderStatus) -> None:
    assert following_status(status) is None


def test_the_pipeline_lists_the_six_stages_in_order() -> None:
    assert tuple(stage.value for stage in RENDER_PIPELINE) == PIPELINE_ORDER
    assert tuple(stage.status.value for stage in RenderStage) == PIPELINE_ORDER


def test_stage_weights_add_up_to_one_hundred() -> None:
    assert set(STAGE_PROGRESS_WEIGHTS) == set(RenderStage)
    assert sum(STAGE_PROGRESS_WEIGHTS.values()) == 100


def test_invalid_transition_errors_carry_both_states() -> None:
    error = InvalidRenderTransitionError(RenderStatus.COMPLETED, RenderStatus.QUEUED)

    assert error.current is RenderStatus.COMPLETED
    assert error.target is RenderStatus.QUEUED


@pytest.mark.parametrize(
    ("enum", "table", "constraint"),
    [
        (RenderStatus, "renders", "ck_renders_status"),
        (RenderSource, "renders", "ck_renders_source"),
        (RenderStage, "renders", "ck_renders_stage"),
        (RenditionStatus, "renditions", "ck_renditions_status"),
        (Aspect, "renditions", "ck_renditions_aspect"),
        (AssetKind, "assets", "ck_assets_kind"),
        (AssetStatus, "assets", "ck_assets_status"),
        (TtsProvider, "tts_cache", "ck_tts_cache_provider"),
        (VoiceKind, "voices", "ck_voices_kind"),
        (VoiceStatus, "voices", "ck_voices_status"),
        (VoiceProvider, "voices", "ck_voices_provider"),
    ],
)
def test_enums_match_the_documented_check_constraints(enum: type[StrEnum], table: str, constraint: str) -> None:
    assert {member.value for member in enum} == documented_values(table, constraint)


@pytest.mark.parametrize("code", [*RenderFailureCode, *VoiceFailureCode])
def test_failure_codes_satisfy_the_database_format(code: RenderFailureCode | VoiceFailureCode) -> None:
    assert re.fullmatch(r"[a-z][a-z0-9_]{1,59}", code.value)


def test_the_documented_failure_codes_exist() -> None:
    documented = {
        "invalid_composition",
        "validation_failed",
        "network_violation",
        "timeout",
        "page_error",
        "browser_crash",
        "duration_limit_exceeded",
        "insufficient_disk",
        "tts_failed",
        "output_check_failed",
        "music_track_unavailable",
        "render_stalled",
        "unsupported_composition",
    }

    assert {code.value for code in RenderFailureCode} == documented
    assert {"consent_mismatch", "sample_invalid", "provider_failed"} <= {code.value for code in VoiceFailureCode}


@pytest.mark.parametrize(
    ("aspect", "slug"), [(Aspect.LANDSCAPE, "16x9"), (Aspect.PORTRAIT, "9x16"), (Aspect.SQUARE, "1x1")]
)
def test_aspect_slugs(aspect: Aspect, slug: str) -> None:
    assert aspect.slug == slug
