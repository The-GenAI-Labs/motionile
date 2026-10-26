from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import JsonValue, StringConstraints

from motionile.core.schemas import CursorPage, PageQuery, ResponseModel, StrictModel
from motionile.engine.ai.job_options import JobStatus
from motionile.engine.ai.ports import JobSource
from motionile.engine.ai.storyboard import Storyboard
from motionile.modules.generation.schemas import JobView

MAX_QUERY_PREVIEW = 200

type Stage = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{0,39}$")]


class AdminJobListQuery(PageQuery):
    status: JobStatus | None = None
    source: JobSource | None = None
    user_id: UUID | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None


class AdminJobSummary(ResponseModel):
    id: UUID
    user_id: UUID
    source: JobSource
    status: JobStatus
    current_stage: str | None
    error_code: str | None
    query: str
    credits_estimated: int
    credits_reserved: int
    credits_charged: int | None
    parent_job_id: UUID | None
    created_at: datetime
    completed_at: datetime | None


class AdminJobPage(CursorPage[AdminJobSummary]):
    pass


class AdminEventView(ResponseModel):
    id: UUID
    type: str
    stage: str | None
    payload: dict[str, JsonValue]
    created_at: datetime


class AdminStoryboardVersion(ResponseModel):
    version: int
    origin: str
    approved: bool
    created_at: datetime


class AdminSceneView(ResponseModel):
    scene_id: str
    position: int
    status: str
    repair_attempts: int
    is_fallback: bool
    actual_duration_ms: int | None
    attempt_log: list[dict[str, JsonValue]]
    error_code: str | None


class AdminCostView(ResponseModel):
    input_tokens: int
    output_tokens: int
    audio_characters: int
    render_ms: int
    cost_micros_usd: int
    usage_records: int
    credits_charged: int | None


class AdminJobDetail(ResponseModel):
    job: JobView
    events: list[AdminEventView]
    storyboard_versions: list[AdminStoryboardVersion]
    approved_storyboard: Storyboard | None
    scenes: list[AdminSceneView]
    reports: dict[str, JsonValue]
    cost: AdminCostView
    trace_url: str | None


class AnalyticsQuery(StrictModel):
    date_from: date | None = None
    date_to: date | None = None


class DayOutcomeView(ResponseModel):
    day: date
    completed: int
    failed: int
    cancelled: int
    success_rate: float | None


class StageDurationView(ResponseModel):
    stage: Stage
    average_seconds: float
    samples: int


class JobAnalyticsView(ResponseModel):
    date_from: date
    date_to: date
    days: list[DayOutcomeView]
    success_rate: float | None
    stages: list[StageDurationView]
    scenes: int
    repair_rate: float | None
    fallback_rate: float | None
    average_cost_micros_usd: float | None
    average_credits_charged: float | None
