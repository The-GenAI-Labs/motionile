from collections.abc import AsyncIterator, Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Final, Protocol
from uuid import UUID, uuid4

from pydantic import JsonValue

from motionile.engine.ai.job_options import JobOptions, JobStatus
from motionile.engine.ai.llm.models import CallContext
from motionile.engine.ai.ports import (
    CompositionCheck,
    CompositionIssue,
    EventPayload,
    JobEventDraft,
    JobSnapshot,
    LoadedSkill,
    NarrationScript,
    ParentContext,
    PreferenceContext,
    RenderProgress,
    SampledFrame,
    SceneAttemptKind,
    SceneRecord,
    SelectedSkills,
    SkillLayer,
    SkillSummary,
    StoredStoryboard,
    StoryboardOrigin,
    TopicContext,
)
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.storyboard import Storyboard
from motionile.engine.audio.models import WordTiming
from motionile.engine.audio.narration import SceneAudio, assemble_narration
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.render.sanitize import sanitize_composition

MS_PER_WORD: Final = 350
SCENE_PADDING_MS: Final = 400
FALLBACK_MARKER: Final = ".mo-fb-stage"
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
    query: str = "How does binary search work?",
    duration_seconds: int = 60,
    aspects: Sequence[str] = ("16:9",),
    style: str = "minimal-dark",
    language: str = "en",
    review_storyboard: bool = False,
    topic: TopicContext | None = None,
    preferences: PreferenceContext | None = None,
    options: JobOptions | None = None,
    parent: Storyboard | None = None,
) -> JobSnapshot:
    resolved = options or JobOptions.model_validate(
        {
            "durationSeconds": duration_seconds,
            "aspects": list(aspects),
            "style": style,
            "voiceId": str(uuid4()),
            "language": language,
            "reviewStoryboard": review_storyboard,
        }
    )
    return JobSnapshot(
        id=uuid4(),
        user_id=uuid4(),
        source="query",
        query=query,
        topic=topic,
        options=resolved,
        status=JobStatus.QUEUED,
        cancel_requested=False,
        preferences=preferences or PreferenceContext(),
        parent=ParentContext(job_id=uuid4(), storyboard=parent) if parent is not None else None,
    )


@dataclass(frozen=True, slots=True)
class SavedModule:
    scene_id: str
    kind: SceneAttemptKind
    issue_codes: tuple[str, ...]


@dataclass
class InMemoryPipelineStore:
    job: JobSnapshot
    events: list[JobEventDraft] = field(default_factory=list[JobEventDraft])
    storyboards: list[StoredStoryboard] = field(default_factory=list[StoredStoryboard])
    origins: list[StoryboardOrigin] = field(default_factory=list[StoryboardOrigin])
    approved_ids: set[UUID] = field(default_factory=set[UUID])
    narration_document: NarrationDocument | None = None
    records: dict[str, SceneRecord] = field(default_factory=dict[str, SceneRecord])
    saved_modules: list[SavedModule] = field(default_factory=list[SavedModule])
    validation_report: EventPayload = field(default_factory=dict[str, JsonValue])
    review_report: EventPayload = field(default_factory=dict[str, JsonValue])
    stages: list[tuple[JobStatus, str]] = field(default_factory=list[tuple[JobStatus, str]])
    cancel_before: set[str] = field(default_factory=set[str])
    failure: tuple[str, str] | None = None
    completed_duration_ms: int | None = None
    snapshots_taken: int = 0

    def _own(self, job_id: UUID) -> None:
        if job_id != self.job.id:
            raise AssertionError("the store was asked about another job")

    async def snapshot(self, job_id: UUID) -> JobSnapshot:
        self._own(job_id)
        self.snapshots_taken += 1
        return self.job

    async def transition(self, job_id: UUID, to: JobStatus, *, stage: str) -> bool:
        self._own(job_id)
        if self.job.status.is_terminal:
            return False
        if stage in self.cancel_before:
            self.job = replace(self.job, cancel_requested=True)
        if self.job.cancel_requested:
            return False
        if to is not self.job.status and to not in ALLOWED_TRANSITIONS[self.job.status]:
            return False
        self.job = replace(self.job, status=to)
        self.stages.append((to, stage))
        return True

    def request_cancel(self) -> None:
        self.job = replace(self.job, cancel_requested=True)

    async def emit(self, job_id: UUID, event: JobEventDraft) -> None:
        self._own(job_id)
        self.events.append(event)

    async def save_storyboard(self, job_id: UUID, storyboard: Storyboard, origin: StoryboardOrigin) -> StoredStoryboard:
        self._own(job_id)
        stored = StoredStoryboard(id=uuid4(), version=len(self.storyboards) + 1, content=storyboard, approved=False)
        self.storyboards.append(stored)
        self.origins.append(origin)
        return stored

    def present(self, stored: StoredStoryboard) -> StoredStoryboard:
        return replace(stored, approved=stored.id in self.approved_ids)

    async def latest_storyboard(self, job_id: UUID) -> StoredStoryboard | None:
        self._own(job_id)
        return self.present(self.storyboards[-1]) if self.storyboards else None

    async def approved_storyboard(self, job_id: UUID) -> StoredStoryboard | None:
        self._own(job_id)
        approved = [stored for stored in self.storyboards if stored.id in self.approved_ids]
        return self.present(approved[-1]) if approved else None

    async def approve_storyboard(self, job_id: UUID, storyboard_id: UUID) -> None:
        self._own(job_id)
        self.approved_ids.add(storyboard_id)

    async def save_narration(self, job_id: UUID, narration: NarrationDocument) -> None:
        self._own(job_id)
        self.narration_document = narration

    async def narration(self, job_id: UUID) -> NarrationDocument | None:
        self._own(job_id)
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
        self._own(job_id)
        return sorted(self.records.values(), key=lambda record: record.position)

    async def save_reports(self, job_id: UUID, *, validation: EventPayload, review: EventPayload) -> None:
        self._own(job_id)
        if validation:
            self.validation_report = validation
        if review:
            self.review_report = review

    async def attach_render(self, job_id: UUID, render_id: UUID) -> None:
        self._own(job_id)
        self.job = replace(self.job, render_id=render_id)

    async def fail(self, job_id: UUID, code: str, message: str) -> None:
        self._own(job_id)
        self.job = replace(self.job, status=JobStatus.FAILED)
        self.failure = (code, message)
        self.events.append(JobEventDraft("job.failed", payload={"code": code, "message": message}))

    async def complete(self, job_id: UUID, *, final_duration_ms: int) -> None:
        self._own(job_id)
        self.job = replace(self.job, status=JobStatus.COMPLETED)
        self.completed_duration_ms = final_duration_ms
        fallbacks = sorted(scene_id for scene_id, record in self.records.items() if record.is_fallback)
        payload: dict[str, JsonValue] = {
            "durationMs": final_duration_ms,
            "fallbackSceneIds": list[JsonValue](fallbacks),
        }
        self.events.append(JobEventDraft("job.completed", payload=payload))

    async def finish_cancellation(self, job_id: UUID) -> None:
        self._own(job_id)
        self.job = replace(self.job, status=JobStatus.CANCELLED)
        self.events.append(JobEventDraft("job.cancelled"))

    @property
    def event_types(self) -> list[str]:
        return [event.type for event in self.events]

    def events_of(self, event_type: str) -> list[JobEventDraft]:
        return [event for event in self.events if event.type == event_type]

    @property
    def stage_names(self) -> list[str]:
        return [str(event.payload["stage"]) for event in self.events if event.type == "stage.started"]


class FakeNarrator:
    def __init__(self, *, ms_per_word: int = MS_PER_WORD, failure: Exception | None = None) -> None:
        self._ms_per_word = ms_per_word
        self._failure = failure
        self.calls: list[list[NarrationScript]] = []

    async def narrate(self, job: JobSnapshot, scenes: Sequence[NarrationScript]) -> NarrationDocument:
        del job
        self.calls.append(list(scenes))
        if self._failure is not None:
            raise self._failure
        audio = [self._scene_audio(script) for script in scenes]
        return assemble_narration(audio, SCENE_PADDING_MS)

    def _scene_audio(self, script: NarrationScript) -> SceneAudio:
        words = script.text.split()
        timings = tuple(
            WordTiming(word, index * self._ms_per_word, (index + 1) * self._ms_per_word)
            for index, word in enumerate(words)
        )
        return SceneAudio(
            id=script.scene_id, text=script.text, duration_ms=len(words) * self._ms_per_word, words=timings
        )


class IssueRule(Protocol):
    def __call__(self, html: str, check_index: int, /) -> Sequence[CompositionIssue]: ...


def scene_issue(
    scene_id: str | None,
    code: str = "text_overflow",
    *,
    severity: str = "error",
    kind: str = "layout",
    aspect: str | None = "16:9",
) -> CompositionIssue:
    return CompositionIssue(
        code=code,
        severity="error" if severity == "error" else "warning",
        kind=kind,
        message=f"{code} measured by the fake checker",
        scene_id=scene_id,
        aspect=aspect,
        time_ms=1200,
    )


def broken_until_fallback(scene_id: str, code: str = "text_overflow") -> IssueRule:
    def rule(html: str, check_index: int) -> Sequence[CompositionIssue]:
        del check_index
        return [] if f".mo-s-{scene_id} {FALLBACK_MARKER}" in html else [scene_issue(scene_id, code)]

    return rule


def always_broken(scene_id: str, code: str = "text_overflow") -> IssueRule:
    def rule(html: str, check_index: int) -> Sequence[CompositionIssue]:
        del html, check_index
        return [scene_issue(scene_id, code)]

    return rule


def broken_on_checks(scene_id: str, checks: Collection[int], code: str = "text_overflow") -> IssueRule:
    def rule(html: str, check_index: int) -> Sequence[CompositionIssue]:
        del html
        return [scene_issue(scene_id, code)] if check_index in checks else []

    return rule


class ScriptedChecker:
    def __init__(self, *rules: IssueRule, frames_png: bytes = b"png") -> None:
        self._rules = rules
        self._frames_png = frames_png
        self.checked_html: list[str] = []
        self.sampled_html: list[str] = []
        self.sample_failure: Exception | None = None

    async def check(self, html: str, narration: NarrationDocument, aspects: Sequence[str]) -> CompositionCheck:
        del aspects
        index = len(self.checked_html)
        self.checked_html.append(html)
        sanitized = sanitize_composition(html, scene_ids=[scene.id for scene in narration.scenes])
        issues = [
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
        ]
        for rule in self._rules:
            issues.extend(rule(html, index))
        return CompositionCheck(valid=not any(issue.is_blocking for issue in issues), issues=tuple(issues))

    async def sample_frames(
        self, html: str, narration: NarrationDocument, aspects: Sequence[str]
    ) -> list[SampledFrame]:
        self.sampled_html.append(html)
        if self.sample_failure is not None:
            raise self.sample_failure
        return [
            SampledFrame(scene_id=scene.id, aspect=aspect, time_ms=scene.duration_ms // 2, png=self._frames_png)
            for scene in narration.scenes
            for aspect in aspects
        ]


def progress_script(
    *points: int, failed_with: str | None = None, render_id: UUID | None = None
) -> list[RenderProgress]:
    identifier = render_id or uuid4()
    steps = [
        RenderProgress(identifier, "rendering", "capture", point, terminal=False, failed=False) for point in points[:-1]
    ]
    if failed_with is not None:
        steps.append(RenderProgress(identifier, "failed", "capture", points[-1], True, True, failed_with))
    else:
        steps.append(RenderProgress(identifier, "completed", "done", points[-1], True, False))
    return steps


class FakeRenderGateway:
    def __init__(
        self,
        script: Sequence[RenderProgress] | None = None,
        on_progress: Callable[[int], None] | None = None,
    ) -> None:
        self.render_id = uuid4()
        self._script = list(script) if script is not None else progress_script(0, 5, 10, 24, 60, 100)
        self._on_progress = on_progress
        self.started: list[tuple[UUID, str]] = []
        self.started_scenes: list[list[NarrationScript]] = []
        self.cancelled: list[UUID] = []
        self.followed: list[UUID] = []

    async def start(self, job: JobSnapshot, html: str, scenes: Sequence[NarrationScript]) -> UUID:
        self.started.append((job.id, html))
        self.started_scenes.append(list(scenes))
        return self.render_id

    async def follow(self, render_id: UUID) -> AsyncIterator[RenderProgress]:
        self.followed.append(render_id)
        for index, step in enumerate(self._script):
            if self._on_progress is not None:
                self._on_progress(index)
            yield replace(step, render_id=render_id)

    async def cancel(self, render_id: UUID) -> None:
        self.cancelled.append(render_id)


def loaded_skill(slug: str, layer: SkillLayer, body: str | None = None) -> LoadedSkill:
    text = body or f"Guidance for the {slug} skill: use calm pacing and clear labels for {layer.value} choices."
    summary = SkillSummary(
        slug=slug, name=slug.replace("-", " ").title(), description=text, layer=layer, version_id=uuid4()
    )
    return LoadedSkill(summary=summary, body=text, tokens={}, token_count=len(text.split()))


def default_selected_skills() -> SelectedSkills:
    return SelectedSkills(
        style=loaded_skill("minimal-dark", SkillLayer.STYLE),
        visual=(
            loaded_skill("kinetic-typography", SkillLayer.VISUAL),
            loaded_skill("flow-diagram", SkillLayer.VISUAL),
        ),
        domain=(loaded_skill("cs-fundamentals", SkillLayer.DOMAIN),),
        reasons={},
    )


class StaticSkillRouter:
    def __init__(self, selected: SelectedSkills | None = None, failure: Exception | None = None) -> None:
        self.selected = selected or default_selected_skills()
        self.failure = failure
        self.calls: list[tuple[JobSnapshot, CallContext, int]] = []

    async def select(self, job: JobSnapshot, context: CallContext, *, token_budget: int) -> SelectedSkills:
        self.calls.append((job, context, token_budget))
        if self.failure is not None:
            raise self.failure
        return self.selected


class StaticSkillCatalog:
    def __init__(self, selected: SelectedSkills | None = None) -> None:
        skills = (selected or default_selected_skills()).all
        self._skills = {skill.summary.slug: skill for skill in skills}
        self.loads: list[list[str]] = []

    async def nearest(self, layer: SkillLayer, embedding: Sequence[float], limit: int) -> list[SkillSummary]:
        del embedding
        return [skill.summary for skill in self._skills.values() if skill.summary.layer is layer][:limit]

    async def by_slugs(self, slugs: Sequence[str]) -> list[SkillSummary]:
        return [self._skills[slug].summary for slug in slugs if slug in self._skills]

    async def load(self, slugs: Sequence[str]) -> list[LoadedSkill]:
        self.loads.append(list(slugs))
        return [self._skills[slug] for slug in slugs if slug in self._skills]
