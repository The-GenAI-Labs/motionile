import re
from itertools import product
from pathlib import Path

import pytest

from motionile.modules.generation import (
    ACTIVE_JOB_STATUSES,
    INITIAL_JOB_STATUS,
    JOB_TRANSITIONS,
    TERMINAL_JOB_STATUSES,
    InvalidJobTransitionError,
    JobStatus,
    can_transition,
    is_terminal,
    require_transition,
)

STATE_MACHINES_DOC = Path(__file__).resolve().parents[6] / "docs" / "db" / "state-machines.md"
SCHEMA_DOC = Path(__file__).resolve().parents[6] / "docs" / "db" / "schema.md"
EDGE = re.compile(r"^\s*(\[\*\]|\w+) --> (\[\*\]|\w+)")

type Edges = set[tuple[str, str]]

ALLOWED: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {
        JobStatus.PLANNING,
        JobStatus.VOICING,
        JobStatus.VALIDATING,
        JobStatus.CANCELLED,
        JobStatus.FAILED,
    },
    JobStatus.PLANNING: {JobStatus.AWAITING_APPROVAL, JobStatus.VOICING, JobStatus.CANCELLED, JobStatus.FAILED},
    JobStatus.AWAITING_APPROVAL: {JobStatus.PLANNING, JobStatus.VOICING, JobStatus.CANCELLED},
    JobStatus.VOICING: {JobStatus.GENERATING, JobStatus.CANCELLED, JobStatus.FAILED},
    JobStatus.GENERATING: {JobStatus.VALIDATING, JobStatus.CANCELLED, JobStatus.FAILED},
    JobStatus.VALIDATING: {JobStatus.GENERATING, JobStatus.RENDERING, JobStatus.CANCELLED, JobStatus.FAILED},
    JobStatus.RENDERING: {JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED},
    JobStatus.COMPLETED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}
ALL_PAIRS = list(product(JobStatus, JobStatus))
ALLOWED_PAIRS = [(current, target) for current, target in ALL_PAIRS if target in ALLOWED[current]]
REJECTED_PAIRS = [(current, target) for current, target in ALL_PAIRS if target not in ALLOWED[current]]


def documented_edges() -> tuple[Edges, set[str]]:
    text = STATE_MACHINES_DOC.read_text(encoding="utf-8")
    block = re.search(r"```mermaid\n(.*?)```", text[text.index("## `jobs.status`") :], re.DOTALL)
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
    line = next(line for line in section.splitlines() if f"`{constraint}`" in line)
    return set(re.findall(r"'([a-z_]+)'", line))


def test_the_table_covers_every_status() -> None:
    assert set(JOB_TRANSITIONS) == set(JobStatus)


def test_the_expectation_in_this_file_covers_every_status() -> None:
    assert set(ALLOWED) == set(JobStatus)


@pytest.mark.parametrize(("current", "target"), ALLOWED_PAIRS)
def test_allowed_transitions_pass(current: JobStatus, target: JobStatus) -> None:
    assert can_transition(current, target)
    require_transition(current, target)


@pytest.mark.parametrize(("current", "target"), REJECTED_PAIRS)
def test_rejected_transitions_raise(current: JobStatus, target: JobStatus) -> None:
    assert not can_transition(current, target)
    with pytest.raises(InvalidJobTransitionError) as raised:
        require_transition(current, target)
    assert raised.value.current is current
    assert raised.value.target is target
    assert current.value in str(raised.value)
    assert target.value in str(raised.value)


@pytest.mark.parametrize("status", sorted(TERMINAL_JOB_STATUSES))
def test_terminal_statuses_have_no_exit(status: JobStatus) -> None:
    assert JOB_TRANSITIONS[status] == frozenset()
    assert is_terminal(status)
    assert status.is_terminal


def test_terminal_statuses_are_completed_failed_and_cancelled() -> None:
    assert {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED} == TERMINAL_JOB_STATUSES


@pytest.mark.parametrize("status", sorted(ACTIVE_JOB_STATUSES))
def test_active_statuses_can_be_cancelled(status: JobStatus) -> None:
    assert not is_terminal(status)
    assert can_transition(status, JobStatus.CANCELLED)


def test_active_statuses_are_the_complement_of_the_terminal_ones() -> None:
    assert set(JobStatus) == ACTIVE_JOB_STATUSES | TERMINAL_JOB_STATUSES
    assert not ACTIVE_JOB_STATUSES & TERMINAL_JOB_STATUSES


def test_no_status_moves_to_itself() -> None:
    assert not any(can_transition(status, status) for status in JobStatus)


def test_a_new_job_starts_queued() -> None:
    assert INITIAL_JOB_STATUS is JobStatus.QUEUED


def test_a_regeneration_returns_an_awaiting_job_to_planning_and_it_can_still_be_cancelled() -> None:
    assert can_transition(JobStatus.AWAITING_APPROVAL, JobStatus.PLANNING)
    assert can_transition(JobStatus.AWAITING_APPROVAL, JobStatus.CANCELLED)
    assert not can_transition(JobStatus.AWAITING_APPROVAL, JobStatus.FAILED)


def test_the_repair_loop_runs_between_generating_and_validating() -> None:
    assert can_transition(JobStatus.VALIDATING, JobStatus.GENERATING)
    assert can_transition(JobStatus.GENERATING, JobStatus.VALIDATING)


def test_the_code_matches_the_documented_state_machine() -> None:
    edges, initial = documented_edges()
    coded = {(current.value, target.value) for current, targets in JOB_TRANSITIONS.items() for target in targets}

    assert coded == edges
    assert initial == {INITIAL_JOB_STATUS.value}


def test_the_statuses_match_the_documented_check_constraint() -> None:
    assert {status.value for status in JobStatus} == documented_values("jobs", "ck_jobs_status")
