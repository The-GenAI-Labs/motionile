from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.db import after_commit
from motionile.core.ids import new_id
from motionile.engine.ai.job_options import JobStatus
from motionile.engine.ai.ports import PreferenceContext, TopicContext
from motionile.modules.catalog import published_topic
from motionile.modules.generation.job_events import JobEvents, JobMessage
from motionile.modules.generation.models import Job, JobEvent, Scene, Storyboard
from motionile.modules.generation.repository import FRESH_ROWS, NewJobEvent, NewStoryboard, SqlJobRepository
from motionile.modules.media import Render
from motionile.modules.users import UserPreference


@dataclass(frozen=True, slots=True)
class SceneUpsert:
    scene_key: str
    position: int
    narration: str
    visual_brief: str
    target_duration_ms: int
    actual_duration_ms: int
    word_timestamps: Sequence[Mapping[str, Any]]


class PipelineStorage(Protocol):
    async def get_for_pipeline(self, job_id: UUID, *, lock: bool = False) -> Job | None: ...

    async def add_event(self, row: NewJobEvent) -> JobEvent: ...

    async def touch(self, job_id: UUID) -> None: ...

    async def move(self, job_id: UUID, target: JobStatus, sources: Collection[JobStatus], stage: str) -> bool: ...

    async def storyboard_pipeline(self, job_id: UUID) -> Storyboard | None: ...

    async def insert_storyboard(self, row: NewStoryboard) -> Storyboard | None: ...

    async def latest_approved_storyboard(self, job_id: UUID) -> Storyboard | None: ...

    async def approve(self, storyboard_id: UUID, job_id: UUID, at: datetime) -> bool: ...

    async def upsert_scenes(self, storyboard_id: UUID, rows: Sequence[SceneUpsert]) -> None: ...

    async def scenes_of(self, storyboard_id: UUID) -> list[Scene]: ...

    async def scene_for_update(self, storyboard_id: UUID, scene_key: str) -> Scene | None: ...

    async def merge_report(self, job_id: UUID, name: str, report: Mapping[str, Any]) -> None: ...

    async def attach_render(self, job_id: UUID, render_id: UUID) -> None: ...

    async def preferences_of(self, user_id: UUID) -> PreferenceContext: ...

    async def topic_of(self, topic_id: UUID) -> TopicContext | None: ...

    async def render_timings(self, render_id: UUID) -> Mapping[str, Any]: ...


def message_of(event: JobEvent) -> JobMessage:
    return JobMessage(id=event.id, type=event.type, stage=event.stage, payload=dict(event.payload), at=event.created_at)


class PublishingJobRepository(SqlJobRepository):
    def __init__(self, session: AsyncSession, events: JobEvents | None = None) -> None:
        super().__init__(session)
        self._events = events

    async def add_event(self, row: NewJobEvent) -> JobEvent:
        event = await super().add_event(row)
        await self.session.refresh(event)
        events = self._events
        if events is not None:
            message = message_of(event)
            job_id = event.job_id
            after_commit(self.session, lambda: events.publish(job_id, message))
        return event


class SqlPipelineRepository(PublishingJobRepository):
    async def touch(self, job_id: UUID) -> None:
        await self.session.execute(update(Job).where(Job.id == job_id).values(updated_at=func.now()))

    async def move(self, job_id: UUID, target: JobStatus, sources: Collection[JobStatus], stage: str) -> bool:
        statement = (
            update(Job)
            .where(
                Job.id == job_id,
                Job.status.in_([source.value for source in sources]),
                Job.cancel_requested_at.is_(None),
            )
            .values(
                status=target.value,
                current_stage=stage,
                started_at=func.coalesce(Job.started_at, func.now()),
                updated_at=func.now(),
            )
            .returning(Job.id)
        )
        return await self.session.scalar(statement) is not None

    async def latest_approved_storyboard(self, job_id: UUID) -> Storyboard | None:
        statement = (
            select(Storyboard)
            .where(Storyboard.job_id == job_id, Storyboard.approved_at.is_not(None))
            .order_by(Storyboard.version.desc())
            .limit(1)
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def storyboards_of(self, job_id: UUID) -> list[Storyboard]:
        statement = (
            select(Storyboard)
            .where(Storyboard.job_id == job_id)
            .order_by(Storyboard.version)
            .execution_options(**FRESH_ROWS)
        )
        return list(await self.session.scalars(statement))

    async def approve(self, storyboard_id: UUID, job_id: UUID, at: datetime) -> bool:
        statement = (
            update(Storyboard)
            .where(Storyboard.id == storyboard_id, Storyboard.job_id == job_id, Storyboard.approved_at.is_(None))
            .values(approved_at=at, updated_at=func.now())
            .returning(Storyboard.id)
        )
        return await self.session.scalar(statement) is not None

    async def upsert_scenes(self, storyboard_id: UUID, rows: Sequence[SceneUpsert]) -> None:
        for row in rows:
            values: dict[str, Any] = {
                "narration": row.narration,
                "visual_brief": row.visual_brief,
                "target_duration_ms": row.target_duration_ms,
                "actual_duration_ms": row.actual_duration_ms,
                "word_timestamps": [dict(word) for word in row.word_timestamps],
            }
            statement = insert(Scene).values(
                id=new_id(),
                storyboard_id=storyboard_id,
                scene_key=row.scene_key,
                position=row.position,
                status="voiced",
                **values,
            )
            await self.session.execute(
                statement.on_conflict_do_update(
                    index_elements=[Scene.storyboard_id, Scene.scene_key],
                    set_={**values, "updated_at": func.now()},
                )
            )

    async def scenes_of(self, storyboard_id: UUID) -> list[Scene]:
        statement = (
            select(Scene)
            .where(Scene.storyboard_id == storyboard_id)
            .order_by(Scene.position)
            .execution_options(**FRESH_ROWS)
        )
        return list(await self.session.scalars(statement))

    async def scene_for_update(self, storyboard_id: UUID, scene_key: str) -> Scene | None:
        statement = (
            select(Scene)
            .where(Scene.storyboard_id == storyboard_id, Scene.scene_key == scene_key)
            .with_for_update()
            .execution_options(**FRESH_ROWS)
        )
        return await self.session.scalar(statement)

    async def merge_report(self, job_id: UUID, name: str, report: Mapping[str, Any]) -> None:
        job = await self.get_for_pipeline(job_id, lock=True)
        if job is None:
            return
        merged = {**job.reports, name: dict(report)}
        await self.session.execute(update(Job).where(Job.id == job_id).values(reports=merged, updated_at=func.now()))

    async def owner_of_render(self, render_id: UUID) -> UUID | None:
        return await self.session.scalar(select(Job.user_id).where(Job.render_id == render_id).limit(1))

    async def attach_render(self, job_id: UUID, render_id: UUID) -> None:
        statement = (
            update(Job)
            .where(Job.id == job_id, Job.render_id.is_(None) | (Job.render_id == render_id))
            .values(render_id=render_id, updated_at=func.now())
        )
        await self.session.execute(statement)

    async def preferences_of(self, user_id: UUID) -> PreferenceContext:
        statement = select(UserPreference).where(UserPreference.user_id == user_id)
        row = await self.session.scalar(statement.execution_options(**FRESH_ROWS))
        if row is None:
            return PreferenceContext()
        return PreferenceContext(style=row.default_style, pace=row.pace, language=row.language, depth=row.depth)

    async def topic_of(self, topic_id: UUID) -> TopicContext | None:
        brief = await published_topic(self.session, topic_id)
        if brief is None:
            return None
        return TopicContext(
            id=brief.id,
            title=brief.title,
            description=brief.summary,
            category=brief.category,
            subcategory=brief.subcategory,
            skill_hints=brief.skill_hints,
        )

    async def render_timings(self, render_id: UUID) -> Mapping[str, Any]:
        timings = await self.session.scalar(select(Render.stage_timings).where(Render.id == render_id))
        return timings or {}
