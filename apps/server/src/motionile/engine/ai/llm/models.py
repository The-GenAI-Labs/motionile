from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Annotated, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel


class LlmTask(StrEnum):
    GUARD = "guard"
    ROUTE = "route"
    PLAN = "plan"
    CRITIQUE = "critique"
    SCENE = "scene"
    REPAIR = "repair"
    VISION_REVIEW = "vision_review"
    CAPTION = "caption"


class LlmErrorCode(StrEnum):
    MODEL_OUTPUT_INVALID = "model_output_invalid"
    BUDGET_EXCEEDED = "budget_exceeded"
    LLM_UNAVAILABLE = "llm_unavailable"
    LLM_TIMEOUT = "llm_timeout"
    OUTPUT_BLOCKED = "output_blocked"


class LlmError(Exception):
    code: LlmErrorCode = LlmErrorCode.LLM_UNAVAILABLE

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code.value)


class ModelOutputInvalidError(LlmError):
    code = LlmErrorCode.MODEL_OUTPUT_INVALID


class BudgetExceededError(LlmError):
    code = LlmErrorCode.BUDGET_EXCEEDED


class LlmUnavailableError(LlmError):
    code = LlmErrorCode.LLM_UNAVAILABLE


class LlmTimeoutError(LlmError):
    code = LlmErrorCode.LLM_TIMEOUT


class OutputBlockedError(LlmError):
    code = LlmErrorCode.OUTPUT_BLOCKED


class RouteConfig(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        extra="forbid",
        frozen=True,
    )

    primary: Annotated[str, Field(min_length=1, max_length=120)]
    fallbacks: Annotated[list[Annotated[str, Field(min_length=1, max_length=120)]], Field(max_length=4)] = Field(
        default_factory=list
    )
    temperature: Annotated[float, Field(ge=0.0, le=1.5)] = 0.3
    max_output_tokens: Annotated[int, Field(ge=64, le=64_000)] = 4_096
    timeout_seconds: Annotated[float, Field(ge=1.0, le=600.0)] = 60.0

    @property
    def models(self) -> tuple[str, ...]:
        return (self.primary, *self.fallbacks)


class RoutingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    routes: dict[LlmTask, RouteConfig]

    @model_validator(mode="after")
    def every_task_is_routed(self) -> "RoutingConfig":
        missing = [task.value for task in LlmTask if task not in self.routes]
        if missing:
            raise ValueError(f"routes are missing for: {', '.join(missing)}")
        return self

    def route(self, task: LlmTask) -> RouteConfig:
        return self.routes[task]


@dataclass(frozen=True, slots=True)
class ImageBlock:
    png: bytes = field(repr=False)
    label: str


type UserBlock = str | ImageBlock


@dataclass(frozen=True, slots=True)
class CallContext:
    user_id: UUID
    job_id: UUID | None
    stage: str
    call_key: str


@dataclass(frozen=True, slots=True)
class LlmCall:
    task: LlmTask
    context: CallContext
    system_blocks: Sequence[str] = field(repr=False)
    user_blocks: Sequence[UserBlock] = field(repr=False)
    metadata: Mapping[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True, slots=True)
class LlmUsage:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int
    cost_micros_usd: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class LlmResult[OutputT: BaseModel]:
    output: OutputT
    usage: LlmUsage
    attempts: int
    fallback_used: bool


class LlmClient(Protocol):
    async def generate[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]: ...


class Embedder(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed(self, texts: Sequence[str], context: CallContext) -> list[list[float]]: ...


class UsageLedger(Protocol):
    async def record(self, context: CallContext, task: LlmTask, usage: LlmUsage) -> None: ...

    async def tokens_used(self, job_id: UUID) -> int: ...


class Span(Protocol):
    def set_output(self, summary: str) -> None: ...

    def set_usage(self, usage: LlmUsage) -> None: ...

    def fail(self, code: str) -> None: ...

    def end(self) -> None: ...


class Tracer(Protocol):
    def span(self, context: CallContext, name: str, summary: str) -> Span: ...
