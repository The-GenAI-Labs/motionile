from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from motionile.engine.ai.base import AiModel

MIN_DURATION_SECONDS = 10
MAX_DURATION_SECONDS = 120
MAX_ASPECTS = 3
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"
LANGUAGE_PATTERN = r"^[a-z]{2,3}(-[A-Z]{2})?$"
SCENE_ID_PATTERN = r"^[a-z][a-z0-9-]{0,31}$"

type AspectName = Literal["16:9", "9:16", "1:1"]
type Slug = Annotated[str, StringConstraints(strip_whitespace=True, pattern=SLUG_PATTERN, max_length=64)]
type LanguageCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=LANGUAGE_PATTERN)]
type SceneIdentifier = Annotated[str, StringConstraints(strip_whitespace=True, pattern=SCENE_ID_PATTERN)]


class JobStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    VOICING = "voicing"
    GENERATING = "generating"
    VALIDATING = "validating"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in TERMINAL_JOB_STATUSES


TERMINAL_JOB_STATUSES = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED})


class RevisionRequest(AiModel):
    instructions: Annotated[str, Field(min_length=1, max_length=2000)]
    scene_ids: Annotated[list[SceneIdentifier], Field(max_length=12)] = Field(default_factory=list)


class JobOptions(AiModel):
    duration_seconds: Annotated[int, Field(ge=MIN_DURATION_SECONDS, le=MAX_DURATION_SECONDS)]
    aspects: Annotated[list[AspectName], Field(min_length=1, max_length=MAX_ASPECTS)]
    style: Slug
    voice_id: UUID
    voice_is_cloned: bool = False
    language: LanguageCode
    review_storyboard: bool = False
    music_track_id: UUID | None = None
    subtitles: bool = True
    burn_in_subtitles: bool = False
    revision: RevisionRequest | None = None

    @field_validator("aspects")
    @classmethod
    def aspects_are_unique(cls, value: list[AspectName]) -> list[AspectName]:
        if len(set(value)) != len(value):
            raise ValueError("aspects must be unique")
        return value

    @model_validator(mode="after")
    def burn_in_needs_subtitles(self) -> "JobOptions":
        if self.burn_in_subtitles and not self.subtitles:
            raise ValueError("burnInSubtitles requires subtitles")
        return self

    @property
    def target_duration_ms(self) -> int:
        return self.duration_seconds * 1000
