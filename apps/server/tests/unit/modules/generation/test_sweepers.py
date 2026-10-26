from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.generation import TERMINAL, GenerationWorld
from tests.unit.modules.generation.support import Harness, storyboard_content

from motionile.core.ids import new_id
from motionile.modules.generation.models import Job
from motionile.modules.generation.sweeper_repository import SweepStore, SweptJob
from motionile.modules.generation.sweepers import APPROVAL_EXPIRED, STALLED_CODE, Sweeper
from motionile.modules.media import RenderNotFoundError


class FakeSweepStore:
    def __init__(self, world: GenerationWorld) -> None:
        self._world = world

    def _page(self, rows: list[Job], after: UUID | None, limit: int) -> list[SweptJob]:
        ordered = sorted(rows, key=lambda job: job.id)
        return [SweptJob(job.id, job.user_id, job.render_id) for job in ordered if after is None or job.id > after][
            :limit
        ]

    async def stalled(self, before: datetime, after: UUID | None, limit: int) -> list[SweptJob]:
        rows = [
            job
            for job in self._world.jobs.values()
            if job.status not in {*TERMINAL, "awaiting_approval"}
            and job.cancel_requested_at is None
            and job.updated_at < before
        ]
        return self._page(rows, after, limit)

    async def expired_approvals(self, before: datetime, after: UUID | None, limit: int) -> list[SweptJob]:
        rows = [
            job for job in self._world.jobs.values() if job.status == "awaiting_approval" and job.updated_at < before
        ]
        return self._page(rows, after, limit)

    async def cancelling(self, before: datetime, after: UUID | None, limit: int) -> list[SweptJob]:
        rows = [
            job
            for job in self._world.jobs.values()
            if job.status not in TERMINAL and job.cancel_requested_at is not None and job.updated_at < before
        ]
        return self._page(rows, after, limit)

    async def locked(self, job_id: UUID) -> Job | None:
        return self._world.jobs.get(job_id)

    async def is_approved(self, job_id: UUID) -> bool:
        rows = [row for row in self._world.storyboards if row.job_id == job_id]
        latest = max(rows, key=lambda row: row.version, default=None)
        return latest is not None and latest.approved_at is not None


class RecordingRenders:
    def __init__(self) -> None:
        self.cancelled: list[tuple[UUID, UUID]] = []
        self.failures: dict[UUID, Exception] = {}

    async def cancel_render(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> object:
        del session
        if render_id in self.failures:
            raise self.failures[render_id]
        self.cancelled.append((user_id, render_id))
        return None


class Fixture:
    def __init__(self, harness: Harness) -> None:
        self.harness = harness
        self.renders = RecordingRenders()
        harness.reader.values["jobs.max_active_per_user"] = 100

        @asynccontextmanager
        async def transaction() -> AsyncGenerator[AsyncSession]:
            yield harness.session

        def store(session: AsyncSession) -> SweepStore:
            del session
            return FakeSweepStore(harness.world)

        self.sweeper = Sweeper(transaction, harness.service, harness.runtime, harness.clock, self.renders, store)

    async def job(self, status: str, *, render: bool = False, **values: object) -> Job:
        await self.harness.fund(500)
        view = await self.harness.service.create(
            self.harness.session, self.harness.user_id, self.harness.request(), self.harness.key()
        )
        job = self.harness.world.jobs[view.id]
        job.status = status
        job.render_id = new_id() if render else None
        for name, value in values.items():
            setattr(job, name, value)
        return job

    def age(self, job: Job, by: timedelta) -> None:
        job.updated_at = self.harness.clock.now() - by


@pytest.fixture
def fixture(harness: Harness) -> Fixture:
    return Fixture(harness)


async def test_a_job_without_progress_for_the_stage_timeout_is_failed_and_its_credits_returned(
    fixture: Fixture,
) -> None:
    stuck = await fixture.job("generating", render=True)
    fixture.age(stuck, timedelta(minutes=31))

    assert await fixture.sweeper.fail_stalled_jobs() == 1

    assert (stuck.status, stuck.error_code) == ("failed", STALLED_CODE)
    assert fixture.harness.wallet() == (500, 0)
    assert fixture.renders.cancelled == [(stuck.user_id, stuck.render_id)]
    assert fixture.harness.world.events[-1].type == "job.failed"


async def test_recent_waiting_terminal_and_cancelling_jobs_are_not_stalled(fixture: Fixture) -> None:
    recent = await fixture.job("generating")
    fixture.age(recent, timedelta(minutes=29))
    waiting = await fixture.job("awaiting_approval")
    fixture.age(waiting, timedelta(days=3))
    cancelling = await fixture.job("voicing", cancel_requested_at=fixture.harness.clock.now())
    fixture.age(cancelling, timedelta(hours=2))
    done = await fixture.job("completed", completed_at=fixture.harness.clock.now())
    fixture.age(done, timedelta(hours=2))

    assert await fixture.sweeper.fail_stalled_jobs() == 0

    assert [job.status for job in (recent, waiting, cancelling, done)] == [
        "generating",
        "awaiting_approval",
        "voicing",
        "completed",
    ]


async def test_the_stage_timeout_comes_from_the_runtime_setting(fixture: Fixture) -> None:
    job = await fixture.job("planning")
    fixture.age(job, timedelta(minutes=45))
    fixture.harness.reader.values["ai.stage_timeout_minutes"] = 60

    assert await fixture.sweeper.fail_stalled_jobs() == 0
    fixture.harness.reader.values["ai.stage_timeout_minutes"] = 30
    assert await fixture.sweeper.fail_stalled_jobs() == 1


async def test_one_job_that_cannot_be_swept_does_not_stop_the_others(fixture: Fixture) -> None:
    broken = await fixture.job("rendering", render=True)
    healthy = await fixture.job("validating")
    for job in (broken, healthy):
        fixture.age(job, timedelta(hours=1))
    fixture.renders.failures[broken.render_id or new_id()] = RuntimeError("storage down")

    assert await fixture.sweeper.fail_stalled_jobs() == 1

    assert healthy.status == "failed"


async def test_a_deleted_render_does_not_block_failing_the_job(fixture: Fixture) -> None:
    job = await fixture.job("rendering", render=True)
    fixture.age(job, timedelta(hours=1))
    fixture.renders.failures[job.render_id or new_id()] = RenderNotFoundError()

    assert await fixture.sweeper.fail_stalled_jobs() == 1
    assert job.status == "failed"


async def test_sweeping_pages_through_more_jobs_than_one_page(
    fixture: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("motionile.modules.generation.sweepers.PAGE_SIZE", 2)
    jobs = [await fixture.job("generating") for _ in range(5)]
    for job in jobs:
        fixture.age(job, timedelta(hours=1))

    assert await fixture.sweeper.fail_stalled_jobs() == 5


async def test_an_approval_that_waited_too_long_is_cancelled_and_refunded(fixture: Fixture) -> None:
    waiting = await fixture.job("awaiting_approval")
    fixture.harness.world.add_storyboard(waiting, storyboard_content())
    fixture.age(waiting, timedelta(hours=169))

    assert await fixture.sweeper.cancel_expired_approvals() == 1

    assert waiting.status == "cancelled"
    assert fixture.harness.wallet() == (500, 0)
    event = fixture.harness.world.events[-1]
    assert (event.type, event.payload["code"]) == ("job.cancelled", APPROVAL_EXPIRED)


async def test_an_approval_inside_the_window_or_already_given_is_kept(fixture: Fixture) -> None:
    fresh = await fixture.job("awaiting_approval")
    fixture.age(fresh, timedelta(hours=167))
    approved = await fixture.job("awaiting_approval")
    row = fixture.harness.world.add_storyboard(approved, storyboard_content())
    row.approved_at = fixture.harness.clock.now()
    fixture.age(approved, timedelta(hours=200))

    assert await fixture.sweeper.cancel_expired_approvals() == 0

    assert (fresh.status, approved.status) == ("awaiting_approval", "awaiting_approval")


async def test_the_approval_timeout_comes_from_the_runtime_setting(fixture: Fixture) -> None:
    waiting = await fixture.job("awaiting_approval")
    fixture.age(waiting, timedelta(hours=30))
    fixture.harness.reader.values["ai.approval_timeout_hours"] = 24

    assert await fixture.sweeper.cancel_expired_approvals() == 1


async def test_a_requested_cancellation_without_progress_is_finished_and_the_render_stopped(fixture: Fixture) -> None:
    job = await fixture.job("rendering", render=True, cancel_requested_at=fixture.harness.clock.now())
    fixture.age(job, timedelta(minutes=3))

    assert await fixture.sweeper.finalize_cancelled_jobs() == 1

    assert job.status == "cancelled"
    assert fixture.harness.wallet() == (500, 0)
    assert fixture.renders.cancelled == [(job.user_id, job.render_id)]


async def test_a_cancellation_still_making_progress_is_left_to_the_pipeline(fixture: Fixture) -> None:
    job = await fixture.job("generating", cancel_requested_at=fixture.harness.clock.now())
    fixture.age(job, timedelta(seconds=90))

    assert await fixture.sweeper.finalize_cancelled_jobs() == 0
    assert job.status == "generating"


async def test_sweeping_twice_does_nothing_the_second_time(fixture: Fixture) -> None:
    job = await fixture.job("generating")
    fixture.age(job, timedelta(hours=1))

    assert await fixture.sweeper.fail_stalled_jobs() == 1
    assert await fixture.sweeper.fail_stalled_jobs() == 0
