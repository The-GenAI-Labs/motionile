from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from motionile.core.schemas import CursorPage, PageQuery, ResponseModel, StrictModel
from motionile.modules.voices.domain import VoiceKind, VoiceStatus

LANGUAGE_PATTERN = r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$"
TAG_PATTERN = r"^[a-z0-9][a-z0-9 -]{0,29}$"
MAX_TAGS = 10
MAX_LANGUAGE_LENGTH = 35
MAX_NAME_LENGTH = 80
MAX_VERSION_LENGTH = 40

type VoiceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_NAME_LENGTH)]
type VoiceLanguage = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=MAX_LANGUAGE_LENGTH, pattern=LANGUAGE_PATTERN)
]
type VoiceTag = Annotated[str, StringConstraints(strip_whitespace=True, pattern=TAG_PATTERN)]
type StatementVersion = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_VERSION_LENGTH)
]


class VoiceView(ResponseModel):
    id: UUID
    name: str
    kind: VoiceKind
    language: str
    status: VoiceStatus
    failure_code: str | None = None
    tags: list[str]
    labels: dict[str, str]
    has_preview: bool
    created_at: datetime
    updated_at: datetime


class AdminVoiceView(VoiceView):
    provider: str
    provider_voice_id: str | None = None


class VoicePage(CursorPage[VoiceView]):
    pass


class AdminVoicePage(CursorPage[AdminVoiceView]):
    pass


class VoicePreviewView(ResponseModel):
    url: str
    expires_at: datetime


class VoiceListQuery(PageQuery):
    language: VoiceLanguage | None = None
    kind: VoiceKind | None = None


class AdminVoiceListQuery(PageQuery):
    language: VoiceLanguage | None = None
    status: VoiceStatus | None = None


class VoiceSyncView(ResponseModel):
    added: int
    unchanged: int


class VoiceUpdateRequest(StrictModel):
    name: VoiceName | None = None
    language: VoiceLanguage | None = None
    tags: Annotated[list[VoiceTag], Field(max_length=MAX_TAGS)] | None = None
    status: Literal[VoiceStatus.READY, VoiceStatus.DISABLED] | None = None

    @model_validator(mode="after")
    def require_a_change(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be set")
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("fields must not be null")
        return self


class CloneLimitsView(ResponseModel):
    sample_min_total_seconds: int
    sample_max_total_seconds: int
    sample_max_bytes: int
    consent_min_seconds: int
    consent_max_seconds: int
    max_sample_files: int


class CloneStartRequest(StrictModel):
    statement_version: StatementVersion
    accepted: Literal[True]


class CloneStartView(ResponseModel):
    attempt_id: UUID
    voice_id: UUID
    consent_sentence: str
    statement_text: str
    statement_version: str
    expires_at: datetime
    limits: CloneLimitsView


class ConsentRecordingView(ResponseModel):
    duration_ms: int
    size_bytes: int


class CloneSampleView(ResponseModel):
    id: UUID
    duration_ms: int
    size_bytes: int


class CloneAttemptView(ResponseModel):
    attempt_id: UUID
    voice_id: UUID
    consent_sentence: str
    statement_version: str
    expires_at: datetime
    consent_recording: ConsentRecordingView | None = None
    samples: list[CloneSampleView]
    total_sample_ms: int
    limits: CloneLimitsView


class CloneSubmitRequest(StrictModel):
    name: VoiceName
    language: VoiceLanguage
