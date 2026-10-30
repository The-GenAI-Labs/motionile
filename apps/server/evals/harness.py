import io
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import cache
from typing import Final
from uuid import UUID, uuid4

from langgraph.checkpoint.memory import InMemorySaver
from PIL import Image

from evals.skill_library import LibrarySkillCatalog
from motionile.engine.ai.graphs.deps import PipelineConfig, PipelineDependencies
from motionile.engine.ai.graphs.run import RunOutcome, run_graph
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.guardrails.input_guard import InputGuard
from motionile.engine.ai.guardrails.output_guard import OutputGuard
from motionile.engine.ai.job_options import AspectName, JobOptions, JobStatus, RevisionRequest
from motionile.engine.ai.llm.models import Embedder, LlmClient
from motionile.engine.ai.ports import (
    CompositionCheck,
    CompositionChecker,
    CompositionIssue,
    EventPayload,
    JobEventDraft,
    JobSnapshot,
    NarrationScript,
    PreferenceContext,
    PromptStore,
    RenderProgress,
    SampledFrame,
    SceneAttemptKind,
    SceneRecord,
    StoredStoryboard,
    StoryboardOrigin,
)
from motionile.engine.ai.prompts.canary import OutputScanner
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.skills import LibrarySkillRouter
from motionile.engine.ai.storyboard import Storyboard, StoryboardLimits
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.render.sanitize import sanitize_composition
from motionile.engine.render.synthetic import SyntheticScene, build_synthetic_narration

FRAME_SIZE: Final = (768, 432)
FRAME_GRAY: Final = 24
FRAME_PERCENTS: Final = (25, 75)
ALLOWED_TRANSITIONS: Final[Mapping[JobStatus, frozenset[JobStatus]]] = {
    JobStatus.QUEUED: frozenset({JobStatus.PLANNING}),
    JobStatus.PLANNING: frozenset({JobStatus.AWAITING_APPROVAL, JobStatus.VOICING}),
    JobStatus.AWAITING_APPROVAL: frozenset({JobStatus.PLANNING, JobStatus.VOICING}),
    JobStatus.VOICING: frozenset({JobStatus.GENERATING}),
    JobStatus.GENERATING: frozenset({JobStatus.VALIDATING}),
    JobStatus.VALIDATING: frozenset({JobStatus.GENERATING, JobStatus.RENDERING}),
    JobStatus.RENDERING: frozenset(),
}


def make_job(  # noqa: PLR0913
    *,
    query: str,
    duration_seconds: int,
    aspects: Sequence[AspectName],
    language: str = "en",
    style: str = "minimal-dark",
    revision: RevisionRequest | None = None,
) -> JobSnapshot:
    options = JobOptions(
        duration_seconds=duration_seconds,
        aspects=list(aspects),
        style=style,
        voice_id=uuid4(),
        language=language,
        review_storyboard=False,
        revision=revision,
    )
    return JobSnapshot(
        id=uuid4(),
        user_id=uuid4(),
        source="query",
        query=query,
        topic=None,
        options=options,
        status=JobStatus.QUEUED,
        cancel_requested=False,
        preferences=PreferenceContext(),
    )


@dataclass(frozen=True, slots=True)
class SavedModule:
    scene_id: str
    kind: SceneAttemptKind
    issue_codes: tuple[str, ...]


@dataclass
class EvalPipelineStore:
    job: JobSnapshot
    events: list[JobEventDraft] = field(default_factory=list[JobEventDraft])
    storyboards: list[StoredStoryboard] = field(default_factory=list[StoredStoryboard])
    approved_ids: set[UUID] = field(default_factory=set[UUID])
    narration_document: NarrationDocument | None = None
    records: dict[str, SceneRecord] = field(default_factory=dict[str, SceneRecord])
    saved_modules: list[SavedModule] = field(default_factory=list[SavedModule])
    failure: tuple[str, str] | None = None
    completed_duration_ms: int | None = None

    async def snapshot(self, job_id: UUID) -> JobSnapshot:
        del job_id
        return self.job

    async def reservation_active(self, job_id: UUID) -> bool:
        del job_id
        return True

    async def transition(self, job_id: UUID, to: JobStatus, *, stage: str) -> bool:
        del job_id, stage
        if self.job.status.is_terminal or self.job.cancel_requested:
            return False
        if to is not self.job.status and to not in ALLOWED_TRANSITIONS[self.job.status]:
            return False
        self.job = replace(self.job, status=to)
        return True

    async def emit(self, job_id: UUID, event: JobEventDraft) -> None:
        del job_id
        self.events.append(event)

    async def save_storyboard(self, job_id: UUID, storyboard: Storyboard, origin: StoryboardOrigin) -> StoredStoryboard:
        del job_id, origin
        stored = StoredStoryboard(id=uuid4(), version=len(self.storyboards) + 1, content=storyboard, approved=False)
        self.storyboards.append(stored)
        return stored

    def present(self, stored: StoredStoryboard) -> StoredStoryboard:
        return replace(stored, approved=stored.id in self.approved_ids)

    async def latest_storyboard(self, job_id: UUID) -> StoredStoryboard | None:
        del job_id
        return self.present(self.storyboards[-1]) if self.storyboards else None

    async def approved_storyboard(self, job_id: UUID) -> StoredStoryboard | None:
        del job_id
        approved = [stored for stored in self.storyboards if stored.id in self.approved_ids]
        return self.present(approved[-1]) if approved else None

    async def approve_storyboard(self, job_id: UUID, storyboard_id: UUID) -> None:
        del job_id
        self.approved_ids.add(storyboard_id)

    async def save_narration(self, job_id: UUID, narration: NarrationDocument) -> None:
        del job_id
        self.narration_document = narration

    async def narration(self, job_id: UUID) -> NarrationDocument | None:
        del job_id
        return self.narration_document

    async def save_scene_module(
        self, job_id: UUID, module: SceneModule, kind: SceneAttemptKind, issues: Sequence[CompositionIssue]
    ) -> None:
        previous = self.records.get(module.scene_id)
        approved = await self.approved_storyboard(job_id)
        scenes = approved.content.scenes if approved is not None else []
        position = next((scene.position for scene in scenes if scene.id == module.scene_id), len(self.records))
        attempts = (previous.attempts if previous else 0) + (1 if kind is SceneAttemptKind.REPAIR else 0)
        self.records[module.scene_id] = SceneRecord(
            scene_id=module.scene_id,
            position=position,
            module=module,
            attempts=attempts,
            is_fallback=kind is SceneAttemptKind.FALLBACK,
        )
        self.saved_modules.append(SavedModule(module.scene_id, kind, tuple(issue.code for issue in issues)))

    async def scenes(self, job_id: UUID) -> list[SceneRecord]:
        del job_id
        return sorted(self.records.values(), key=lambda record: record.position)

    async def save_reports(self, job_id: UUID, *, validation: EventPayload, review: EventPayload) -> None:
        del job_id, validation, review

    async def attach_render(self, job_id: UUID, render_id: UUID) -> None:
        del job_id
        self.job = replace(self.job, render_id=render_id)

    async def fail(self, job_id: UUID, code: str, message: str) -> None:
        del job_id
        self.job = replace(self.job, status=JobStatus.FAILED)
        self.failure = (code, message)

    async def complete(self, job_id: UUID, *, final_duration_ms: int) -> None:
        del job_id
        self.job = replace(self.job, status=JobStatus.COMPLETED)
        self.completed_duration_ms = final_duration_ms

    async def finish_cancellation(self, job_id: UUID) -> None:
        del job_id
        self.job = replace(self.job, status=JobStatus.CANCELLED)

    @property
    def fallback_ids(self) -> list[str]:
        return sorted(scene_id for scene_id, record in self.records.items() if record.is_fallback)


class SyntheticNarrator:
    async def narrate(self, job: JobSnapshot, scenes: Sequence[NarrationScript]) -> NarrationDocument:
        del job
        return build_synthetic_narration([SyntheticScene(script.scene_id, script.text) for script in scenes])


class CompletedRenderGateway:
    def __init__(self) -> None:
        self._render_id = uuid4()

    async def start(self, job: JobSnapshot, html: str, scenes: Sequence[NarrationScript]) -> UUID:
        del job, html, scenes
        return self._render_id

    async def follow(self, render_id: UUID) -> AsyncIterator[RenderProgress]:
        yield RenderProgress(render_id, "completed", "done", 100, terminal=True, failed=False)

    async def cancel(self, render_id: UUID) -> None:
        del render_id


@cache
def placeholder_frame() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", FRAME_SIZE, (FRAME_GRAY, FRAME_GRAY, FRAME_GRAY)).save(buffer, format="PNG")
    return buffer.getvalue()


def frame_times(narration: NarrationDocument) -> list[tuple[str, int]]:
    return [
        (scene.id, scene.start_ms + scene.duration_ms * percent // 100)
        for scene in narration.scenes
        for percent in FRAME_PERCENTS
    ]


class StaticChecker:
    async def check(self, html: str, narration: NarrationDocument, aspects: Sequence[str]) -> CompositionCheck:
        del aspects
        sanitized = sanitize_composition(html, scene_ids=[scene.id for scene in narration.scenes])
        issues = tuple(
            CompositionIssue(
                code=finding.code,
                severity=finding.severity,
                kind=finding.kind,
                message=finding.message,
                scene_id=finding.scene,
                aspect=finding.aspect,
                time_ms=finding.time_ms,
            )
            for finding in sanitized.findings
        )
        return CompositionCheck(valid=not any(issue.is_blocking for issue in issues), issues=issues)

    async def sample_frames(
        self, html: str, narration: NarrationDocument, aspects: Sequence[str]
    ) -> list[SampledFrame]:
        del html
        return [
            SampledFrame(scene_id=scene_id, aspect=aspect, time_ms=time_ms, png=placeholder_frame())
            for aspect in aspects
            for scene_id, time_ms in frame_times(narration)
        ]


class ObservingChecker:
    def __init__(self, inner: CompositionChecker) -> None:
        self._inner = inner
        self.first_check: CompositionCheck | None = None
        self.checks = 0
        self.last_frames: list[SampledFrame] = []
        self.last_html = ""

    async def check(self, html: str, narration: NarrationDocument, aspects: Sequence[str]) -> CompositionCheck:
        result = await self._inner.check(html, narration, aspects)
        self.checks += 1
        self.last_html = html
        if self.first_check is None:
            self.first_check = result
        return result

    async def sample_frames(
        self, html: str, narration: NarrationDocument, aspects: Sequence[str]
    ) -> list[SampledFrame]:
        frames = await self._inner.sample_frames(html, narration, aspects)
        self.last_frames = frames
        return frames


@dataclass(frozen=True, slots=True)
class RigParts:
    llm: LlmClient
    prompts: PromptStore
    checker: CompositionChecker
    embedder: Embedder
    limits: StoryboardLimits = field(default_factory=StoryboardLimits)
    visual_review: bool = True


type NodeFunction = Callable[[PipelineDependencies, PipelineState], Awaitable[PipelineState]]


@dataclass(slots=True)
class Rig:
    job: JobSnapshot
    store: EvalPipelineStore
    deps: PipelineDependencies
    saver: InMemorySaver = field(default_factory=InMemorySaver)

    async def run(self) -> RunOutcome:
        return await run_graph(self.deps, self.job.id, self.saver)

    async def run_nodes(self, nodes: Sequence[NodeFunction]) -> PipelineState:
        state: PipelineState = {"job_id": str(self.job.id)}
        for node in nodes:
            state = {**state, **await node(self.deps, state)}
        return state


async def build_rig(job: JobSnapshot, parts: RigParts, catalog: LibrarySkillCatalog) -> Rig:
    store = EvalPipelineStore(job)
    scanner = OutputScanner(await parts.prompts.all_active(), catalog.bodies())
    deps = PipelineDependencies(
        store=store,
        narrator=SyntheticNarrator(),
        checker=parts.checker,
        renders=CompletedRenderGateway(),
        prompts=parts.prompts,
        skill_router=LibrarySkillRouter(catalog, parts.embedder, parts.llm, parts.prompts),
        catalog=catalog,
        llm=parts.llm,
        input_guard=InputGuard(parts.llm, parts.prompts),
        output_guard=OutputGuard(parts.llm, parts.prompts, scanner),
        config=PipelineConfig(
            limits=parts.limits, visual_review_enabled=parts.visual_review, render_poll_seconds=0.001
        ),
    )
    return Rig(job, store, deps)
