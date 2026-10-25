import json
from collections.abc import Collection, Iterable, Sequence
from typing import Final

from pydantic import JsonValue

from motionile.engine.ai.graphs.state import IssueRecord
from motionile.engine.ai.ports import CompositionIssue, SceneRecord
from motionile.engine.ai.scenes.models import SceneModule, StaticFinding
from motionile.engine.ai.scenes.static_checks import check_scene_module

MAX_ISSUES_PER_SCENE: Final = 8
MAX_MESSAGE_CHARS: Final = 400
MAX_DETAIL_CHARS: Final = 300
MAX_EVENT_CODES: Final = 12
STATIC_KIND: Final = "static"


def clipped_detail(detail: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return detail if len(json.dumps(detail, ensure_ascii=False)) <= MAX_DETAIL_CHARS else {}


def to_record(issue: CompositionIssue, scene_id: str) -> IssueRecord:
    return IssueRecord(
        scene_id=scene_id,
        code=issue.code,
        severity=issue.severity,
        kind=issue.kind,
        message=issue.message[:MAX_MESSAGE_CHARS],
        aspect=issue.aspect,
        time_ms=issue.time_ms,
        detail=clipped_detail(dict(issue.detail)),
    )


def to_issue(record: IssueRecord) -> CompositionIssue:
    return CompositionIssue(
        code=record["code"],
        severity=record["severity"],
        kind=record["kind"],
        message=record["message"],
        scene_id=record["scene_id"],
        aspect=record["aspect"],
        time_ms=record["time_ms"],
        detail=record["detail"],
    )


def static_issue(scene_id: str, finding: StaticFinding) -> CompositionIssue:
    detail: dict[str, JsonValue] = {}
    if finding.line is not None:
        detail["line"] = finding.line
    if finding.detail is not None:
        detail["detail"] = finding.detail
    return CompositionIssue(
        code=finding.code.value,
        severity="error",
        kind=STATIC_KIND,
        message=finding.message,
        scene_id=scene_id,
        detail=detail,
    )


def module_issues(module: SceneModule) -> list[CompositionIssue]:
    return [static_issue(module.scene_id, finding) for finding in check_scene_module(module)]


def static_records(records: Iterable[SceneRecord]) -> list[IssueRecord]:
    found: list[IssueRecord] = []
    for record in records:
        if record.module is None or record.is_fallback:
            continue
        found.extend(to_record(issue, record.scene_id) for issue in module_issues(record.module)[:MAX_ISSUES_PER_SCENE])
    return found


def attribute_issues(
    issues: Iterable[CompositionIssue], scene_ids: Collection[str], document_targets: Sequence[str]
) -> dict[str, list[CompositionIssue]]:
    grouped: dict[str, list[CompositionIssue]] = {}
    for issue in issues:
        scene_id = issue.scene_id
        targets = [scene_id] if scene_id is not None and scene_id in scene_ids else list(document_targets)
        for target in targets:
            grouped.setdefault(target, []).append(issue)
    return grouped


def blocking_records(grouped: dict[str, list[CompositionIssue]]) -> list[IssueRecord]:
    return [
        to_record(issue, scene_id)
        for scene_id, issues in grouped.items()
        for issue in [candidate for candidate in issues if candidate.is_blocking][:MAX_ISSUES_PER_SCENE]
    ]


def group_records(records: Iterable[IssueRecord]) -> dict[str, list[CompositionIssue]]:
    grouped: dict[str, list[CompositionIssue]] = {}
    for record in records:
        grouped.setdefault(record["scene_id"], []).append(to_issue(record))
    return grouped


def issue_codes(issues: Iterable[CompositionIssue]) -> list[JsonValue]:
    return list[JsonValue](sorted({issue.code for issue in issues})[:MAX_EVENT_CODES])


def issues_json(issues: Iterable[CompositionIssue]) -> str:
    entries: list[dict[str, JsonValue]] = []
    for issue in issues:
        entry: dict[str, JsonValue] = {
            "code": issue.code,
            "severity": issue.severity,
            "kind": issue.kind,
            "message": issue.message,
        }
        if issue.aspect is not None:
            entry["aspect"] = issue.aspect
        if issue.time_ms is not None:
            entry["timeMs"] = issue.time_ms
        if issue.detail:
            entry["details"] = dict(issue.detail)
        entries.append(entry)
    return json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
