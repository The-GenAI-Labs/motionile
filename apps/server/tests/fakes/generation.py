from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.engine.ai.guardrails import GuardResult, PolicyCode
from motionile.engine.ai.job_options import JobOptions, JobStatus
from motionile.modules.audit import AuditContext, AuditEvent
from motionile.modules.catalog import TopicBrief
from motionile.modules.generation.models import Job, JobEvent, Scene
from motionile.modules.generation.models import Storyboard as StoryboardRow
from motionile.modules.generation.ports import ChosenVoice, ResumeKind, UserPreferences
from motionile.modules.generation.repository import JobFilter, NewJob, NewJobEvent, NewStoryboard
from motionile.modules.platform import SETTINGS, SettingValue
from motionile.modules.voices import VoiceNotAvailableError

EPOCH = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
TERMINAL = {JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value}


def job_options(**overrides: Any) -> JobOptions:
    values: dict[str, Any] = {
        "duration_seconds": 60,
        "aspects": ["16:9"],
        "style": "minimal-dark",
        "voice_id": new_id(),
        "language": "en",
        **overrides,
    }
    return JobOptions.model_validate(values)


@dataclass
class GenerationWorld:
    jobs: dict[UUID, Job] = field(default_factory=dict[UUID, Job])
    storyboards: list[StoryboardRow] = field(default_factory=list[StoryboardRow])
    scenes: list[Scene] = field(default_factory=list[Scene])
    events: list[JobEvent] = field(default_factory=list[JobEvent])
    locked_creations: list[UUID] = field(default_factory=list[UUID])
    tick: int = 0

    def next_time(self) -> datetime:
        self.tick += 1
        return datetime.fromtimestamp(EPOCH.timestamp() + self.tick, tz=UTC)

    def add_job(self, user_id: UUID, **overrides: Any) -> Job:
        status = overrides.get("status", JobStatus.QUEUED.value)
        created = self.next_time()
        values: dict[str, Any] = {
            "id": new_id(),
            "user_id": user_id,
            "source": "query",
            "topic_id": None,
            "parent_job_id": None,
            "query": "How does TCP work?",
            "options": job_options().model_dump(mode="json", by_alias=True),
            "status": status,
            "current_stage": None,
            "credits_estimated": 140,
            "credits_reserved": 140,
            "credits_charged": None,
            "error_code": None,
            "error_message": None,
            "cancel_requested_at": None,
            "started_at": None,
            "completed_at": created if status in TERMINAL else None,
            "render_id": None,
            "idempotency_key": None,
            "reports": {},
            "created_at": created,
            "updated_at": created,
            **overrides,
        }
        job = Job(**values)
        self.jobs[job.id] = job
        return job

    def add_storyboard(self, job: Job, content: Mapping[str, Any], **overrides: Any) -> StoryboardRow:
        existing = [row.version for row in self.storyboards if row.job_id == job.id]
        values: dict[str, Any] = {
            "id": new_id(),
            "job_id": job.id,
            "version": max(existing, default=0) + 1,
            "origin": "planner",
            "content": dict(content),
            "approved_at": None,
            "approved_by": None,
            "created_at": self.next_time(),
            "updated_at": self.next_time(),
            **overrides,
        }
        row = StoryboardRow(**values)
        self.storyboards.append(row)
        return row

    def add_scene(self, storyboard: StoryboardRow, key: str, position: int, *, is_fallback: bool) -> Scene:
        scene = Scene(
            id=new_id(),
            storyboard_id=storyboard.id,
            scene_key=key,
            position=position,
            narration="n",
            visual_brief="v",
            target_duration_ms=5000,
            status="validated",
            repair_attempts=0,
            is_fallback=is_fallback,
            attempt_log=[],
            created_at=EPOCH,
            updated_at=EPOCH,
        )
        self.scenes.append(scene)
        return scene

    def factory(self, session: AsyncSession) -> "InMemoryJobStore":
        del session
        return InMemoryJobStore(self)

    def event_types(self, job_id: UUID) -> list[str]:
        return [event.type for event in self.events if event.job_id == job_id]


class InMemoryJobStore:
    def __init__(self, world: GenerationWorld) -> None:
        self._world = world

    async def lock_creation(self, user_id: UUID) -> None:
        self._world.locked_creations.append(user_id)

    async def count_active(self, user_id: UUID) -> int:
        return sum(1 for job in self._world.jobs.values() if job.user_id == user_id and job.status not in TERMINAL)

    async def insert(self, row: NewJob) -> Job:
        now = self._world.next_time()
        job = Job(
            id=row.id,
            user_id=row.user_id,
            source=row.source,
            topic_id=row.topic_id,
            parent_job_id=row.parent_job_id,
            query=row.query,
            options=dict(row.options),
            status=JobStatus.QUEUED.value,
            credits_estimated=row.credits_estimated,
            credits_reserved=row.credits_reserved,
            idempotency_key=row.idempotency_key,
            reports={},
            created_at=now,
            updated_at=now,
        )
        self._world.jobs[job.id] = job
        return job

    async def get_owned(self, user_id: UUID, job_id: UUID, *, lock: bool = False) -> Job | None:
        del lock
        job = self._world.jobs.get(job_id)
        return job if job is not None and job.user_id == user_id else None

    async def get_for_pipeline(self, job_id: UUID, *, lock: bool = False) -> Job | None:
        del lock
        return self._world.jobs.get(job_id)

    async def get_by_key(self, user_id: UUID, idempotency_key: str) -> Job | None:
        return next(
            (
                job
                for job in self._world.jobs.values()
                if job.user_id == user_id and job.idempotency_key == idempotency_key
            ),
            None,
        )

    async def page(self, user_id: UUID, job_filter: JobFilter, cursor: Cursor | None, limit: int) -> list[Job]:
        rows = [job for job in self._world.jobs.values() if job.user_id == user_id]
        if job_filter.status is not None:
            rows = [job for job in rows if job.status == job_filter.status.value]
        if job_filter.source is not None:
            rows = [job for job in rows if job.source == job_filter.source]
        if job_filter.topic_id is not None:
            rows = [job for job in rows if job.topic_id == job_filter.topic_id]
        rows.sort(key=lambda job: (job.created_at, job.id), reverse=True)
        if cursor is not None:
            rows = [job for job in rows if (job.created_at, job.id) < (cursor.created_at, cursor.id)]
        return rows[: limit + 1]

    async def transition(
        self, job_id: UUID, target: JobStatus, sources: Collection[JobStatus], values: Mapping[str, Any]
    ) -> Job | None:
        job = self._world.jobs.get(job_id)
        if job is None or job.status not in {source.value for source in sources}:
            return None
        job.status = target.value
        job.updated_at = self._world.next_time()
        for name, value in values.items():
            setattr(job, name, value)
        return job

    async def request_cancel(self, job_id: UUID, at: datetime) -> Job | None:
        job = self._world.jobs.get(job_id)
        if job is None or job.status in TERMINAL:
            return None
        job.cancel_requested_at = job.cancel_requested_at or at
        return job

    async def delete(self, user_id: UUID, job_id: UUID) -> bool:
        job = await self.get_owned(user_id, job_id)
        if job is None:
            return False
        del self._world.jobs[job_id]
        self._world.storyboards[:] = [row for row in self._world.storyboards if row.job_id != job_id]
        return True

    async def fallback_scene_keys(self, job_ids: Collection[UUID]) -> dict[UUID, list[str]]:
        keys: dict[UUID, list[str]] = {}
        for row in self._world.storyboards:
            if row.job_id not in job_ids:
                continue
            for scene in sorted(self._world.scenes, key=lambda item: item.position):
                if scene.storyboard_id == row.id and scene.is_fallback:
                    keys.setdefault(row.job_id, []).append(scene.scene_key)
        return keys

    async def latest_storyboard(self, user_id: UUID, job_id: UUID) -> StoryboardRow | None:
        if await self.get_owned(user_id, job_id) is None:
            return None
        return await self.storyboard_pipeline(job_id)

    async def storyboard_pipeline(self, job_id: UUID) -> StoryboardRow | None:
        rows = [row for row in self._world.storyboards if row.job_id == job_id]
        return max(rows, key=lambda row: row.version, default=None)

    async def insert_storyboard(self, row: NewStoryboard) -> StoryboardRow | None:
        if any(item.job_id == row.job_id and item.version == row.version for item in self._world.storyboards):
            return None
        return self._world.add_storyboard(
            self._world.jobs[row.job_id], row.content, version=row.version, origin=row.origin
        )

    async def approve_storyboard(self, storyboard_id: UUID, approver_id: UUID, at: datetime) -> bool:
        row = next(item for item in self._world.storyboards if item.id == storyboard_id)
        if row.approved_at is not None:
            return False
        row.approved_at = at
        row.approved_by = approver_id
        return True

    async def scenes(self, user_id: UUID, job_id: UUID) -> list[Scene]:
        if await self.get_owned(user_id, job_id) is None:
            return []
        ids = {row.id for row in self._world.storyboards if row.job_id == job_id}
        return [scene for scene in self._world.scenes if scene.storyboard_id in ids]

    async def add_event(self, row: NewJobEvent) -> JobEvent:
        event = JobEvent(
            id=new_id(), job_id=row.job_id, type=row.type, stage=row.stage, payload=dict(row.payload), created_at=EPOCH
        )
        self._world.events.append(event)
        return event

    async def events_after(self, user_id: UUID, job_id: UUID, after: UUID | None, limit: int) -> list[JobEvent]:
        if await self.get_owned(user_id, job_id) is None:
            return []
        rows = [event for event in self._world.events if event.job_id == job_id and (after is None or event.id > after)]
        return rows[:limit]

    async def events_for_admin(self, job_id: UUID, limit: int) -> list[JobEvent]:
        return [event for event in self._world.events if event.job_id == job_id][:limit]


class FakeSettingsReader:
    def __init__(self, **overrides: SettingValue) -> None:
        self.values: dict[str, SettingValue] = dict(overrides)

    async def value(self, session: AsyncSession, key: str) -> SettingValue:
        del session
        return self.values.get(key, SETTINGS[key].default)


class FakePreferences:
    def __init__(self, preferences: UserPreferences | None = None) -> None:
        self.preferences = preferences or UserPreferences()

    async def for_user(self, session: AsyncSession, user_id: UUID) -> UserPreferences:
        del session, user_id
        return self.preferences


class FakeSkills:
    def __init__(self, *styles: str) -> None:
        self.styles = set(styles) or {"minimal-dark", "whiteboard"}

    async def style_exists(self, session: AsyncSession, slug: str) -> bool:
        del session
        return slug in self.styles


class FakeVoices:
    def __init__(self) -> None:
        self.default = ChosenVoice(new_id(), is_cloned=False)
        self.cloned: set[UUID] = set()
        self.unavailable: set[UUID] = set()
        self.known: set[UUID] = set()

    async def choose(self, session: AsyncSession, user_id: UUID, voice_id: UUID) -> ChosenVoice:
        del session, user_id
        if voice_id in self.unavailable:
            raise VoiceNotAvailableError
        return ChosenVoice(voice_id, is_cloned=voice_id in self.cloned)

    async def default_for(
        self, session: AsyncSession, user_id: UUID, preferred: UUID | None, language: str
    ) -> ChosenVoice:
        del language
        if preferred is not None and preferred not in self.unavailable:
            return await self.choose(session, user_id, preferred)
        return self.default


class FakeMusic:
    def __init__(self) -> None:
        self.active: set[UUID] = set()

    async def require_active(self, session: AsyncSession, track_id: UUID) -> object:
        del session
        if track_id not in self.active:
            from motionile.modules.media import MusicTrackUnavailableError  # noqa: PLC0415

            raise MusicTrackUnavailableError
        return track_id


class FakeTopics:
    def __init__(self) -> None:
        self.topics: dict[UUID, TopicBrief] = {}

    def add(self, title: str = "How DNS works") -> TopicBrief:
        topic = TopicBrief(new_id(), title, None, "Backend", "Networking", (), 60_000)
        self.topics[topic.id] = topic
        return topic

    async def published(self, session: AsyncSession, topic_id: UUID) -> TopicBrief | None:
        del session
        return self.topics.get(topic_id)


class FakeEditGuard:
    def __init__(self) -> None:
        self.refuse_with: PolicyCode | None = None
        self.edits: list[list[str]] = []
        self.instructions: list[str] = []

    async def check_edit(self, user_id: UUID, job_id: UUID, texts: Sequence[str]) -> GuardResult:
        del user_id, job_id
        self.edits.append(list(texts))
        return self._result()

    async def check_instructions(self, user_id: UUID, job_id: UUID, text: str) -> GuardResult:
        del user_id, job_id
        self.instructions.append(text)
        return self._result()

    def _result(self) -> GuardResult:
        return GuardResult.refuse(self.refuse_with) if self.refuse_with else GuardResult.allow()


class FakeRenders:
    def __init__(self) -> None:
        self.deleted: list[tuple[UUID, UUID]] = []

    async def delete_render(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> None:
        del session
        self.deleted.append((user_id, render_id))


@dataclass
class RecordingDispatch:
    runs: list[UUID] = field(default_factory=list[UUID])
    resumes: list[tuple[UUID, ResumeKind, str | None]] = field(
        default_factory=list[tuple[UUID, ResumeKind, str | None]]
    )

    def run(self, session: AsyncSession, job_id: UUID) -> None:
        del session
        self.runs.append(job_id)

    def resume(self, session: AsyncSession, job_id: UUID, kind: ResumeKind, instructions: str | None) -> None:
        del session
        self.resumes.append((job_id, kind, instructions))


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def __call__(self, session: AsyncSession, event: AuditEvent, context: AuditContext | None) -> UUID:
        del session, context
        self.events.append(event)
        return new_id()

    @property
    def actions(self) -> list[str]:
        return [event.action for event in self.events]
