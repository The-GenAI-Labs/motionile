from typing import Literal, TypedDict

from pydantic import JsonValue


class IssueRecord(TypedDict):
    scene_id: str
    code: str
    severity: Literal["error", "warning"]
    kind: str
    message: str
    aspect: str | None
    time_ms: int | None
    detail: dict[str, JsonValue]


class PipelineState(TypedDict, total=False):
    job_id: str
    skills: list[str]
    context_text: str
    base_version: int
    planned_version: int
    approval_version: int
    approval_requested: bool
    decision: Literal["approve", "regenerate"]
    instructions: str | None
    attempts: dict[str, int]
    issues: list[IssueRecord]
    reviewed: list[str]
