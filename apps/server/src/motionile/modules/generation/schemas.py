from datetime import datetime
from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from motionile.core.schemas import CursorPage, PageQuery, ResponseModel, StrictModel
from motionile.engine.ai.job_options import (
    MAX_ASPECTS,
    MAX_DURATION_SECONDS,
    MIN_DURATION_SECONDS,
    AspectName,
    JobStatus,
    LanguageCode,
    SceneIdentifier,
    Slug,
)
from motionile.engine.ai.ports import JobSource
from motionile.engine.ai.storyboard import Storyboard, StoryboardIssue

MAX_QUERY_CHARS = 2_000
MAX_SCENE_SELECTION = 12

type UserQuery = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUERY_CHARS)]
type Instructions = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUERY_CHARS)]
type AspectChoice = Annotated[list[AspectName], Field(min_length=1, max_length=MAX_ASPECTS)]
type Duration = Annotated[int, Field(ge=MIN_DURATION_SECONDS, le=MAX_DURATION_SECONDS)]
type StoryboardVersion = Annotated[int, Field(ge=1, le=1_000_000)]


def require_unique_aspects(aspects: list[AspectName] | None) -> None:
    if aspects is not None and len(set(aspects)) != len(aspects):
        raise ValueError("aspects must be unique")


def require_captions_for_burn_in(subtitles: bool | None, burn_in_subtitles: bool | None) -> None:
    if burn_in_subtitles and subtitles is False:
        raise ValueError("burnInSubtitles requires subtitles")


class JobOptionsRequest(StrictModel):
    duration_seconds: Duration
    aspects: AspectChoice | None = None
    style: Slug | None = None
    voice_id: UUID | None = None
    language: LanguageCode | None = None
    review_storyboard: bool = False
    music_track_id: UUID | None = None
    subtitles: bool | None = None
    burn_in_subtitles: bool = False

    @model_validator(mode="after")
    def check_choices(self) -> Self:
        require_unique_aspects(self.aspects)
        require_captions_for_burn_in(self.subtitles, self.burn_in_subtitles)
        return self


class JobOptionsOverrides(StrictModel):
    duration_seconds: Duration | None = None
    aspects: AspectChoice | None = None
    style: Slug | None = None
    voice_id: UUID | None = None
    language: LanguageCode | None = None
    review_storyboard: bool | None = None
    music_track_id: UUID | None = None
    subtitles: bool | None = None
    burn_in_subtitles: bool | None = None

    @model_validator(mode="after")
    def check_choices(self) -> Self:
        require_unique_aspects(self.aspects)
        require_captions_for_burn_in(self.subtitles, self.burn_in_subtitles)
        return self


class EstimateRequest(StrictModel):
    options: JobOptionsRequest


class ChargingParametersView(ResponseModel):
    base_credits: int
    credits_per_second: int
    extra_aspect_percent: int
    cloned_voice_premium: int


class EstimateView(ResponseModel):
    credits: int
    available_credits: int
    affordable: bool
    seconds: int
    aspect_count: int
    cloned_voice: bool
    parameters: ChargingParametersView


class JobCreateRequest(StrictModel):
    topic_id: UUID | None = None
    query: UserQuery | None = None
    options: JobOptionsRequest

    @model_validator(mode="after")
    def exactly_one_source(self) -> Self:
        if (self.topic_id is None) == (self.query is None):
            raise ValueError("send exactly one of topicId or query")
        return self


class RegenerateRequest(StrictModel):
    instructions: Instructions


class ReviseRequest(StrictModel):
    instructions: Instructions
    scene_ids: Annotated[list[SceneIdentifier], Field(max_length=MAX_SCENE_SELECTION)] = Field(default_factory=list)
    options: JobOptionsOverrides | None = None

    @model_validator(mode="after")
    def scenes_are_unique(self) -> Self:
        if len(set(self.scene_ids)) != len(self.scene_ids):
            raise ValueError("sceneIds must be unique")
        return self


class ApproveRequest(StrictModel):
    expected_version: StoryboardVersion


class StoryboardUpdateRequest(StrictModel):
    expected_version: StoryboardVersion
    content: Storyboard


class RevisionView(ResponseModel):
    instructions: str
    scene_ids: list[str]


class JobOptionsView(ResponseModel):
    duration_seconds: int
    aspects: list[AspectName]
    style: str
    voice_id: UUID
    voice_is_cloned: bool
    language: str
    review_storyboard: bool
    music_track_id: UUID | None
    subtitles: bool
    burn_in_subtitles: bool
    revision: RevisionView | None


class JobView(ResponseModel):
    id: UUID
    source: JobSource
    topic_id: UUID | None
    query: str
    options: JobOptionsView
    status: JobStatus
    current_stage: str | None
    credits_estimated: int
    credits_reserved: int
    credits_charged: int | None
    error_code: str | None
    error_title: str | None
    error_message: str | None
    cancel_requested_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
    render_id: UUID | None
    parent_job_id: UUID | None
    fallback_scene_ids: list[str]
    created_at: datetime
    updated_at: datetime


class JobPage(CursorPage[JobView]):
    pass


class JobListQuery(PageQuery):
    status: JobStatus | None = None
    source: JobSource | None = None
    topic_id: UUID | None = None


class OnScreenLimitView(ResponseModel):
    aspect: AspectName
    characters: int


class StoryboardLimitsView(ResponseModel):
    min_scenes: int
    max_scenes: int
    duration_tolerance_percent: int
    min_words_per_second: float
    max_words_per_second: float
    nominal_words_per_second: float
    on_screen_text: list[OnScreenLimitView]


class StoryboardView(ResponseModel):
    version: int
    approved: bool
    origin: str
    content: Storyboard
    issues: list[StoryboardIssue]
    limits: StoryboardLimitsView
    updated_at: datetime
