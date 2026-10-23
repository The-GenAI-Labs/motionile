import re
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import AfterValidator, Field, StringConstraints, model_validator

from motionile.core.config import MediaDeliveryMode
from motionile.core.schemas import CursorPage, PageQuery, ResponseModel, StrictModel
from motionile.modules.media.domain import Aspect, RenderSource, RenderStage, RenderStatus, RenditionStatus

MOOD_PATTERN = r"^[a-z][a-z0-9-]{1,39}$"
HTTPS_URL_PATTERN = re.compile(r"^https://[^\s]+$")
MAX_URL_LENGTH = 2000
BPM_RANGE = (30, 300)


def require_https_url(value: str) -> str:
    if HTTPS_URL_PATTERN.fullmatch(value) is None:
        raise ValueError("must be an https URL without whitespace")
    return value


type HttpsUrl = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=9, max_length=MAX_URL_LENGTH),
    AfterValidator(require_https_url),
]
type Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
type Mood = Annotated[str, StringConstraints(strip_whitespace=True, pattern=MOOD_PATTERN)]
type Bpm = Annotated[int, Field(ge=BPM_RANGE[0], le=BPM_RANGE[1])]
type LicenseName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
type AttributionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class MediaSessionView(ResponseModel):
    mode: MediaDeliveryMode
    expires_at: datetime | None = None


class MusicAttributionView(ResponseModel):
    track_id: UUID
    title: str
    license_name: str
    license_url: str
    attribution_text: str | None = None


class RenditionView(ResponseModel):
    id: UUID
    aspect: Aspect
    width: int
    height: int
    duration_ms: int | None = None
    status: RenditionStatus
    burned_in_subtitles: bool
    url: str | None = None
    poster_url: str | None = None
    poster_jpeg_url: str | None = None
    subtitles_url: str | None = None
    subtitles_srt_url: str | None = None
    attribution: MusicAttributionView | None = None


class RenditionListView(ResponseModel):
    items: list[RenditionView]


class RenderView(ResponseModel):
    id: UUID
    source: RenderSource
    status: RenderStatus
    stage: RenderStage | None = None
    progress: int
    options: dict[str, Any]
    duration_ms: int | None = None
    validation_report: dict[str, Any] | None = None
    stage_timings: dict[str, Any]
    error_code: str | None = None
    error_message: str | None = None
    cancel_requested_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MusicTrackView(ResponseModel):
    id: UUID
    title: str
    mood: str
    bpm: int | None = None
    duration_ms: int
    license_name: str
    license_url: str
    attribution_text: str | None = None
    is_active: bool
    audio_asset_id: UUID
    preview_url: str | None = None
    created_by_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class MusicTrackPage(CursorPage[MusicTrackView]):
    pass


class MusicListQuery(PageQuery):
    mood: Mood | None = None
    active: bool | None = None


class MusicUpdateRequest(StrictModel):
    title: Title | None = None
    mood: Mood | None = None
    bpm: Bpm | None = None
    license_name: LicenseName | None = None
    license_url: HttpsUrl | None = None
    attribution_text: AttributionText | None = None

    @model_validator(mode="after")
    def require_a_change(self) -> "MusicUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        required = ("title", "mood", "license_name", "license_url")
        cleared = [name for name in required if name in self.model_fields_set and getattr(self, name) is None]
        if cleared:
            raise ValueError(f"{', '.join(cleared)} cannot be cleared")
        return self
