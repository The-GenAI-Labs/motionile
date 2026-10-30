from datetime import datetime
from typing import Annotated, Any, Self
from uuid import UUID

from pydantic import Field, StringConstraints, field_validator, model_validator

from motionile.core.schemas import CursorPage, PageQuery, ResponseModel, StrictModel
from motionile.modules.prompts.domain import (
    MAX_BODY_CHARS,
    MAX_RUN_VERSIONS,
    MAX_VARIABLES,
    MAX_VERSION_NUMBER,
    SUITE_PATTERN,
    VARIABLE_PATTERN,
    EvalStatus,
    RunStatus,
    RunTrigger,
)

MIN_BODY_CHARS = 20
MAX_SUITE_LENGTH = 60
MAX_VARIABLE_LENGTH = 64

type SuiteName = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=MAX_SUITE_LENGTH, pattern=SUITE_PATTERN)
]
type VariableName = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=MAX_VARIABLE_LENGTH, pattern=VARIABLE_PATTERN)
]
type VersionNumber = Annotated[int, Field(ge=1, le=MAX_VERSION_NUMBER)]


class TemplateView(ResponseModel):
    key: str
    description: str | None
    active_version: int | None
    version_count: int
    latest_eval_status: EvalStatus | None


class TemplateList(ResponseModel):
    items: list[TemplateView]


class VersionView(ResponseModel):
    id: UUID
    version: int
    checksum_prefix: str
    eval_status: EvalStatus
    created_at: datetime
    created_by: UUID | None
    is_active: bool


class VersionPage(CursorPage[VersionView]):
    pass


class DiffView(ResponseModel):
    key: str
    from_version: int
    to_version: int
    lines: list[str]
    added: int
    removed: int


class DiffQuery(StrictModel):
    from_version: VersionNumber = Field(alias="from")
    to_version: VersionNumber = Field(alias="to")


class DraftRequest(StrictModel):
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=MIN_BODY_CHARS, max_length=MAX_BODY_CHARS)]
    variables: Annotated[list[VariableName], Field(max_length=MAX_VARIABLES)] = Field(default_factory=list[str])

    @field_validator("variables")
    @classmethod
    def require_unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("variables must be unique")
        return value


class EvalRunRequest(StrictModel):
    suite: SuiteName
    version_ids: Annotated[list[UUID], Field(min_length=1, max_length=MAX_RUN_VERSIONS)]

    @model_validator(mode="after")
    def require_unique_versions(self) -> Self:
        if len(set(self.version_ids)) != len(self.version_ids):
            raise ValueError("version ids must be unique")
        return self


class EvalRunView(ResponseModel):
    id: UUID
    suite: str
    dataset_version: str
    prompt_version_ids: list[UUID]
    models_used: dict[str, Any]
    scores: dict[str, Any]
    passed: bool | None
    status: RunStatus
    error_code: str | None
    trigger: RunTrigger
    created_by: UUID | None
    started_at: datetime
    finished_at: datetime | None


class EvalRunPage(CursorPage[EvalRunView]):
    pass


class EvalRunListQuery(PageQuery):
    suite: SuiteName | None = None
    status: RunStatus | None = None
