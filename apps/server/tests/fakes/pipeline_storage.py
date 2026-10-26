from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from tests.fakes.generation import EPOCH, GenerationWorld, InMemoryJobStore

from motionile.core.ids import new_id
from motionile.engine.ai.job_options import JobStatus
from motionile.engine.ai.ports import PreferenceContext, TopicContext
from motionile.modules.generation.models import Job, JobEvent, Scene
from motionile.modules.generation.models import Storyboard as StoryboardRow
from motionile.modules.generation.pipeline_repository import SceneUpsert
from motionile.modules.generation.repository import NewJobEvent, NewStoryboard


class InMemoryPipelineStorage:
    def __init__(self, world: GenerationWorld) -> None:
        self.world = world
        self.touched: list[UUID] = []
        self.topics: dict[UUID, TopicContext] = {}
        self.preferences = PreferenceContext()
        self.timings: Mapping[str, Any] = {}
        self._jobs = InMemoryJobStore(world)

    async def get_for_pipeline(self, job_id: UUID, *, lock: bool = False) -> Job | None:
        del lock
        return self.world.jobs.get(job_id)

    async def add_event(self, row: NewJobEvent) -> JobEvent:
        return await self._jobs.add_event(row)

    async def touch(self, job_id: UUID) -> None:
        self.touched.append(job_id)

    async def move(self, job_id: UUID, target: JobStatus, sources: Collection[JobStatus], stage: str) -> bool:
        job = self.world.jobs.get(job_id)
        if job is None or job.cancel_requested_at is not None or job.status not in {item.value for item in sources}:
            return False
        job.status = target.value
        job.current_stage = stage
        job.started_at = job.started_at or EPOCH
        return True

    async def storyboard_pipeline(self, job_id: UUID) -> StoryboardRow | None:
        return await self._jobs.storyboard_pipeline(job_id)

    async def insert_storyboard(self, row: NewStoryboard) -> StoryboardRow | None:
        return await self._jobs.insert_storyboard(row)

    async def latest_approved_storyboard(self, job_id: UUID) -> StoryboardRow | None:
        rows = [row for row in self.world.storyboards if row.job_id == job_id and row.approved_at is not None]
        return max(rows, key=lambda row: row.version, default=None)

    async def approve(self, storyboard_id: UUID, job_id: UUID, at: datetime) -> bool:
        row = next(item for item in self.world.storyboards if item.id == storyboard_id and item.job_id == job_id)
        if row.approved_at is not None:
            return False
        row.approved_at = at
        return True

    async def upsert_scenes(self, storyboard_id: UUID, rows: Sequence[SceneUpsert]) -> None:
        for row in rows:
            existing = next(
                (
                    scene
                    for scene in self.world.scenes
                    if scene.storyboard_id == storyboard_id and scene.scene_key == row.scene_key
                ),
                None,
            )
            if existing is not None:
                existing.narration = row.narration
                existing.actual_duration_ms = row.actual_duration_ms
                existing.word_timestamps = [dict(word) for word in row.word_timestamps]
                continue
            self.world.scenes.append(
                Scene(
                    id=new_id(),
                    storyboard_id=storyboard_id,
                    scene_key=row.scene_key,
                    position=row.position,
                    narration=row.narration,
                    visual_brief=row.visual_brief,
                    target_duration_ms=row.target_duration_ms,
                    actual_duration_ms=row.actual_duration_ms,
                    word_timestamps=[dict(word) for word in row.word_timestamps],
                    module=None,
                    status="voiced",
                    repair_attempts=0,
                    is_fallback=False,
                    attempt_log=[],
                    created_at=EPOCH,
                    updated_at=EPOCH,
                )
            )

    async def scenes_of(self, storyboard_id: UUID) -> list[Scene]:
        rows = [scene for scene in self.world.scenes if scene.storyboard_id == storyboard_id]
        return sorted(rows, key=lambda scene: scene.position)

    async def scene_for_update(self, storyboard_id: UUID, scene_key: str) -> Scene | None:
        return next(
            (
                scene
                for scene in self.world.scenes
                if scene.storyboard_id == storyboard_id and scene.scene_key == scene_key
            ),
            None,
        )

    async def merge_report(self, job_id: UUID, name: str, report: Mapping[str, Any]) -> None:
        job = self.world.jobs[job_id]
        job.reports = {**job.reports, name: dict(report)}

    async def attach_render(self, job_id: UUID, render_id: UUID) -> None:
        job = self.world.jobs[job_id]
        if job.render_id is None or job.render_id == render_id:
            job.render_id = render_id

    async def preferences_of(self, user_id: UUID) -> PreferenceContext:
        del user_id
        return self.preferences

    async def topic_of(self, topic_id: UUID) -> TopicContext | None:
        return self.topics.get(topic_id)

    async def render_timings(self, render_id: UUID) -> Mapping[str, Any]:
        del render_id
        return self.timings
