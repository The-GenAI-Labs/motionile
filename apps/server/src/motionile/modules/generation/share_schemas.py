from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import model_validator

from motionile.core.schemas import ResponseModel, StrictModel
from motionile.engine.ai.job_options import AspectName


class ShareCreateRequest(StrictModel):
    rendition_id: UUID | None = None
    aspect: AspectName | None = None
    allow_indexing: bool = False

    @model_validator(mode="after")
    def exactly_one_target(self) -> Self:
        if (self.rendition_id is None) == (self.aspect is None):
            raise ValueError("send exactly one of renditionId or aspect")
        return self


class ShareLinkView(ResponseModel):
    slug: str
    url: str
    rendition_id: UUID
    aspect: AspectName
    allow_indexing: bool
    view_count: int
    created_at: datetime


class SharedVideoView(ResponseModel):
    title: str
    summary: str | None
    language: str | None
    duration_ms: int | None
    aspect: AspectName
    width: int
    height: int
    poster_url: str | None
    playback_url: str
    playback_expires_in_seconds: int
    allow_indexing: bool
    uploaded_at: datetime
    music_attribution: str | None = None
