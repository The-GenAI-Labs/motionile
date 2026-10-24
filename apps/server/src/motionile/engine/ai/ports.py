from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol
from uuid import UUID

from pydantic import JsonValue

from motionile.engine.ai.job_options import JobOptions, JobStatus
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.storyboard import Storyboard
from motionile.engine.audio.narration_models import NarrationDocument

type JobSource = Literal["catalog", "query", "mcp"]
type EventPayload = Mapping[str, JsonValue]


class StoryboardOrigin(StrEnum):
    PLANNER = "planner"
    CRITIC = "critic"
    REGENERATION = "regeneration"
    USER = "user"


class SceneAttemptKind(StrEnum):
    INITIAL = "initial"
    REPAIR = "repair"
    FALLBACK = "fallback"


class SkillLayer(StrEnum):
    STYLE = "style"
    VISUAL = "visual"
    DOMAIN = "domain"


@dataclass(frozen=True, slots=True)
class TopicContext:
    id: UUID
    title: str
    description: str | None
    category: str
    subcategory: str
    skill_hints: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PreferenceContext:
    style: str | None = None
    pace: str | None = None
    language: str | None = None
    depth: str | None = None


@dataclass(frozen=True, slots=True)
class StoredStoryboard:
    id: UUID
    version: int
    content: Storyboard
    approved: bool


@dataclass(frozen=True, slots=True)
class ParentContext:
    job_id: UUID
    storyboard: Storyboard


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    id: UUID
    user_id: UUID
    source: JobSource
    query: str
    topic: TopicContext | None
    options: JobOptions
    status: JobStatus
    cancel_requested: bool
    preferences: PreferenceContext
    parent: ParentContext | None = None
    render_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class JobEventDraft:
    type: str
    stage: str | None = None
    payload: EventPayload = field(default_factory=dict[str, JsonValue])
    persist: bool = True


@dataclass(frozen=True, slots=True)
class SceneRecord:
    scene_id: str
    position: int
    module: SceneModule | None
    attempts: int
    is_fallback: bool


@dataclass(frozen=True, slots=True)
class CompositionIssue:
    code: str
    severity: Literal["error", "warning"]
    kind: str
    message: str
    scene_id: str | None = None
    aspect: str | None = None
    time_ms: int | None = None
    detail: EventPayload = field(default_factory=dict[str, JsonValue])

    @property
    def is_blocking(self) -> bool:
        return self.severity == "error"


@dataclass(frozen=True, slots=True)
class CompositionCheck:
    valid: bool
    issues: tuple[CompositionIssue, ...]
    report: EventPayload = field(default_factory=dict[str, JsonValue])


@dataclass(frozen=True, slots=True)
class SampledFrame:
    scene_id: str
    aspect: str
    time_ms: int
    png: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class NarrationScript:
    scene_id: str
    text: str


@dataclass(frozen=True, slots=True)
class RenderProgress:
    render_id: UUID
    status: str
    stage: str | None
    progress: int
    terminal: bool
    failed: bool
    error_code: str | None = None


@dataclass(frozen=True, slots=True)
class ActivePrompt:
    key: str
    version_id: UUID
    version: int
    body: str
    canary: str
    variables: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SkillSummary:
    slug: str
    name: str
    description: str
    layer: SkillLayer
    version_id: UUID


@dataclass(frozen=True, slots=True)
class LoadedSkill:
    summary: SkillSummary
    body: str
    tokens: Mapping[str, str]
    token_count: int


@dataclass(frozen=True, slots=True)
class ContextSection:
    title: str
    text: str


class PipelineStore(Protocol):
    async def snapshot(self, job_id: UUID) -> JobSnapshot: ...

    async def transition(self, job_id: UUID, to: JobStatus, *, stage: str) -> bool: ...

    async def emit(self, job_id: UUID, event: JobEventDraft) -> None: ...

    async def save_storyboard(
        self, job_id: UUID, storyboard: Storyboard, origin: StoryboardOrigin
    ) -> StoredStoryboard: ...

    async def latest_storyboard(self, job_id: UUID) -> StoredStoryboard | None: ...

    async def approved_storyboard(self, job_id: UUID) -> StoredStoryboard | None: ...

    async def save_narration(self, job_id: UUID, narration: NarrationDocument) -> None: ...

    async def narration(self, job_id: UUID) -> NarrationDocument | None: ...

    async def save_scene_module(
        self,
        job_id: UUID,
        module: SceneModule,
        kind: SceneAttemptKind,
        issues: Sequence[CompositionIssue],
    ) -> None: ...

    async def scenes(self, job_id: UUID) -> list[SceneRecord]: ...

    async def save_reports(self, job_id: UUID, *, validation: EventPayload, review: EventPayload) -> None: ...

    async def attach_render(self, job_id: UUID, render_id: UUID) -> None: ...

    async def fail(self, job_id: UUID, code: str, message: str) -> None: ...

    async def complete(self, job_id: UUID, *, final_duration_ms: int) -> None: ...

    async def finish_cancellation(self, job_id: UUID) -> None: ...


class Narrator(Protocol):
    async def narrate(self, job: JobSnapshot, scenes: Sequence[NarrationScript]) -> NarrationDocument: ...


class CompositionChecker(Protocol):
    async def check(self, html: str, narration: NarrationDocument, aspects: Sequence[str]) -> CompositionCheck: ...

    async def sample_frames(
        self, html: str, narration: NarrationDocument, aspects: Sequence[str]
    ) -> list[SampledFrame]: ...


class RenderGateway(Protocol):
    async def start(self, job: JobSnapshot, html: str, scenes: Sequence[NarrationScript]) -> UUID: ...

    def follow(self, render_id: UUID) -> AsyncIterator[RenderProgress]: ...

    async def cancel(self, render_id: UUID) -> None: ...


class PromptStore(Protocol):
    async def active(self, key: str) -> ActivePrompt: ...

    async def all_active(self) -> list[ActivePrompt]: ...


class SkillCatalog(Protocol):
    async def nearest(self, layer: SkillLayer, embedding: Sequence[float], limit: int) -> list[SkillSummary]: ...

    async def by_slugs(self, slugs: Sequence[str]) -> list[SkillSummary]: ...

    async def load(self, slugs: Sequence[str]) -> list[LoadedSkill]: ...


class ContextProvider(Protocol):
    @property
    def name(self) -> str: ...

    async def gather(self, job: JobSnapshot) -> ContextSection | None: ...
