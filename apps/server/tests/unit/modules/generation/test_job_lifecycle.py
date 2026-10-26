from uuid import UUID

import pytest
from tests.unit.modules.generation.support import START, Harness

from motionile.core.db import run_after_commit
from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.engine.ai.job_options import JobStatus
from motionile.modules.credits import ReserveCommand
from motionile.modules.generation import (
    JobCompleted,
    JobNotDeletableError,
    JobNotFoundError,
)
from motionile.modules.generation.repository import JobFilter


async def started(harness: Harness, status: str = "queued") -> UUID:
    await harness.fund(500)
    view = await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())
    job = harness.world.jobs[view.id]
    job.status = status
    return job.id


async def test_cancelling_a_queued_job_stops_it_and_releases_the_reservation(harness: Harness) -> None:
    job_id = await started(harness)

    view = await harness.service.cancel(harness.session, harness.user_id, job_id)

    assert view.status is JobStatus.CANCELLED
    assert view.completed_at is not None
    assert harness.wallet() == (500, 0)
    assert harness.world.event_types(job_id) == ["job.created", "job.cancelled"]
    assert harness.world.events[-1].payload == {"code": "cancelled_by_user", "creditsReleased": 140}
    assert harness.audit.actions == ["job.created", "job.cancelled"]


async def test_cancelling_twice_returns_the_finished_job_unchanged(harness: Harness) -> None:
    job_id = await started(harness)
    await harness.service.cancel(harness.session, harness.user_id, job_id)
    events = len(harness.world.events)

    again = await harness.service.cancel(harness.session, harness.user_id, job_id)

    assert again.status is JobStatus.CANCELLED
    assert len(harness.world.events) == events
    assert harness.wallet() == (500, 0)


async def test_cancelling_a_waiting_job_stops_it_at_once(harness: Harness) -> None:
    job, _ = harness.waiting_job()
    await harness.fund(500)
    await harness.credits.reserve(
        harness.session,
        ReserveCommand(harness.user_id, 140, "job", job.id, f"job:{job.id}:reserve"),
    )

    view = await harness.service.cancel(harness.session, harness.user_id, job.id)

    assert view.status is JobStatus.CANCELLED
    assert harness.wallet() == (500, 0)


async def test_cancelling_an_approved_job_only_requests_a_cooperative_stop(harness: Harness) -> None:
    job, _ = harness.waiting_job(approved=True)

    view = await harness.service.cancel(harness.session, harness.user_id, job.id)

    assert view.status is JobStatus.AWAITING_APPROVAL
    assert view.cancel_requested_at == START
    assert harness.world.event_types(job.id) == ["job.cancel_requested"]


@pytest.mark.parametrize("status", ["planning", "voicing", "generating", "validating", "rendering"])
async def test_cancelling_a_running_job_sets_the_flag_and_keeps_the_reservation(harness: Harness, status: str) -> None:
    job_id = await started(harness, status)

    view = await harness.service.cancel(harness.session, harness.user_id, job_id)

    assert view.status is JobStatus(status)
    assert view.cancel_requested_at == START
    assert harness.wallet() == (500, 140)


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
async def test_cancelling_a_finished_job_changes_nothing(harness: Harness, status: str) -> None:
    job = harness.world.add_job(harness.user_id, status=status, error_code="tts_failed" if status == "failed" else None)

    view = await harness.service.cancel(harness.session, harness.user_id, job.id)

    assert view.status is JobStatus(status)
    assert view.cancel_requested_at is None


async def test_failing_a_job_releases_the_reservation_and_records_the_error(harness: Harness) -> None:
    job_id = await started(harness, "generating")

    assert await harness.service.fail_job(harness.session, job_id, "model_output_invalid", "bad output")

    job = harness.world.jobs[job_id]
    assert (job.status, job.error_code, job.error_message) == ("failed", "model_output_invalid", "bad output")
    assert job.completed_at is not None
    assert harness.wallet() == (500, 0)
    assert harness.world.events[-1].type == "job.failed"
    assert harness.world.events[-1].payload["creditsReleased"] == 140


async def test_failing_a_finished_job_is_a_no_op(harness: Harness) -> None:
    job_id = await started(harness, "rendering")
    await harness.service.complete_job(harness.session, job_id, 30_000)

    assert not await harness.service.fail_job(harness.session, job_id, "tts_failed", "late")
    assert harness.world.jobs[job_id].status == "completed"


async def test_a_waiting_job_cannot_be_failed_by_the_pipeline(harness: Harness) -> None:
    job, _ = harness.waiting_job()

    assert not await harness.service.fail_job(harness.session, job.id, "job_stalled", "x")


async def test_failing_with_a_malformed_code_is_a_programming_error(harness: Harness) -> None:
    job_id = await started(harness, "generating")

    with pytest.raises(ValueError, match="valid job error code"):
        await harness.service.fail_job(harness.session, job_id, "Bad Code", "x")


async def test_failing_an_unknown_job_returns_false(harness: Harness) -> None:
    assert not await harness.service.fail_job(harness.session, new_id(), "tts_failed", "x")


async def test_completing_a_job_charges_the_formula_for_the_final_duration(harness: Harness) -> None:
    job_id = await started(harness, "rendering")

    charged = await harness.service.complete_job(harness.session, job_id, 30_100)

    assert charged == 20 + 2 * 31
    job = harness.world.jobs[job_id]
    assert (job.status, job.credits_charged) == ("completed", 82)
    assert harness.wallet() == (500 - 82, 0)
    assert harness.world.events[-1].type == "job.completed"
    assert harness.world.events[-1].payload == {"creditsCharged": 82, "durationMs": 30_100, "fallbackSceneIds": []}


async def test_a_long_video_is_capped_at_the_reservation(harness: Harness) -> None:
    job_id = await started(harness, "rendering")

    assert await harness.service.complete_job(harness.session, job_id, 119_000) == 140
    assert harness.wallet() == (360, 0)


async def test_completion_lists_the_fallback_scenes_and_publishes_the_domain_event(harness: Harness) -> None:
    job_id = await started(harness, "rendering")
    row = harness.world.add_storyboard(harness.world.jobs[job_id], {})
    harness.world.add_scene(row, "intro", 0, is_fallback=False)
    harness.world.add_scene(row, "outro", 1, is_fallback=True)
    received: list[JobCompleted] = []

    async def handler(event: JobCompleted) -> None:
        received.append(event)

    harness.events.subscribe(JobCompleted, handler, name="test.job_completed")

    await harness.service.complete_job(harness.session, job_id, 60_000)
    assert received == []
    await run_after_commit(harness.session)

    assert harness.world.events[-1].payload["fallbackSceneIds"] == ["outro"]
    assert received == [JobCompleted(job_id=job_id, user_id=harness.user_id, duration_ms=60_000, credits_charged=140)]


async def test_only_a_rendering_job_can_complete(harness: Harness) -> None:
    job_id = await started(harness, "generating")

    assert await harness.service.complete_job(harness.session, job_id, 30_000) is None
    assert harness.world.jobs[job_id].status == "generating"
    assert harness.wallet() == (500, 140)


async def test_completing_twice_charges_once(harness: Harness) -> None:
    job_id = await started(harness, "rendering")
    await harness.service.complete_job(harness.session, job_id, 30_000)

    assert await harness.service.complete_job(harness.session, job_id, 30_000) is None
    assert harness.wallet() == (500 - 80, 0)


async def test_finishing_a_cooperative_cancellation_releases_the_reservation(harness: Harness) -> None:
    job_id = await started(harness, "voicing")
    await harness.service.cancel(harness.session, harness.user_id, job_id)

    assert await harness.service.finish_cancellation(harness.session, job_id)

    assert harness.world.jobs[job_id].status == "cancelled"
    assert harness.wallet() == (500, 0)
    assert harness.world.events[-1].type == "job.cancelled"
    assert not await harness.service.finish_cancellation(harness.session, job_id)


async def test_deleting_a_finished_job_removes_its_render_and_the_job(harness: Harness) -> None:
    render_id = new_id()
    job = harness.world.add_job(harness.user_id, status="completed", render_id=render_id)

    await harness.service.delete(harness.session, harness.user_id, job.id)

    assert job.id not in harness.world.jobs
    assert harness.renders.deleted == [(harness.user_id, render_id)]
    assert harness.audit.actions == ["job.deleted"]


@pytest.mark.parametrize("status", ["failed", "cancelled"])
async def test_a_job_without_a_render_can_be_deleted(harness: Harness, status: str) -> None:
    job = harness.world.add_job(harness.user_id, status=status, error_code="tts_failed" if status == "failed" else None)

    await harness.service.delete(harness.session, harness.user_id, job.id)

    assert harness.renders.deleted == []


@pytest.mark.parametrize("status", ["queued", "planning", "awaiting_approval", "voicing", "rendering"])
async def test_an_unfinished_job_cannot_be_deleted(harness: Harness, status: str) -> None:
    job = harness.world.add_job(harness.user_id, status=status)

    with pytest.raises(JobNotDeletableError) as caught:
        await harness.service.delete(harness.session, harness.user_id, job.id)

    assert caught.value.code == "job_not_deletable"
    assert job.id in harness.world.jobs


async def test_every_operation_treats_another_users_job_as_not_found(harness: Harness) -> None:
    job = harness.world.add_job(harness.other_id, status="completed")
    calls = [
        harness.service.get(harness.session, harness.user_id, job.id),
        harness.service.storyboard(harness.session, harness.user_id, job.id),
        harness.service.cancel(harness.session, harness.user_id, job.id),
        harness.service.delete(harness.session, harness.user_id, job.id),
    ]

    for call in calls:
        with pytest.raises(JobNotFoundError):
            await call
    assert job.id in harness.world.jobs


async def test_jobs_are_listed_newest_first_with_filters_and_cursors(harness: Harness) -> None:
    oldest = harness.world.add_job(harness.user_id, status="completed")
    middle = harness.world.add_job(harness.user_id, status="failed", error_code="tts_failed")
    newest = harness.world.add_job(harness.user_id, status="completed", source="catalog", topic_id=new_id())
    harness.world.add_job(harness.other_id, status="completed")

    everything = await harness.service.list_jobs(harness.session, harness.user_id, JobFilter(), None, 10)
    first = await harness.service.list_jobs(harness.session, harness.user_id, JobFilter(), None, 2)
    assert first.next_cursor is not None
    second = await harness.service.list_jobs(harness.session, harness.user_id, JobFilter(), first.next_cursor, 2)
    failed = await harness.service.list_jobs(
        harness.session, harness.user_id, JobFilter(status=JobStatus.FAILED), None, 10
    )
    catalog = await harness.service.list_jobs(harness.session, harness.user_id, JobFilter(source="catalog"), None, 10)

    assert [item.id for item in everything.items] == [newest.id, middle.id, oldest.id]
    assert everything.next_cursor is None
    assert [item.id for item in first.items] == [newest.id, middle.id]
    assert [item.id for item in second.items] == [oldest.id]
    assert second.next_cursor is None
    assert [item.id for item in failed.items] == [middle.id]
    assert [item.id for item in catalog.items] == [newest.id]
    assert isinstance(first.next_cursor, Cursor)


async def test_the_topic_filter_matches_only_that_topic(harness: Harness) -> None:
    topic_id = new_id()
    wanted = harness.world.add_job(harness.user_id, source="catalog", topic_id=topic_id)
    harness.world.add_job(harness.user_id, source="catalog", topic_id=new_id())

    page = await harness.service.list_jobs(harness.session, harness.user_id, JobFilter(topic_id=topic_id), None, 10)

    assert [item.id for item in page.items] == [wanted.id]


async def test_a_failed_job_view_carries_a_user_facing_title_and_message(harness: Harness) -> None:
    job = harness.world.add_job(
        harness.user_id, status="failed", error_code="policy_weapons", error_message="internal detail"
    )

    view = await harness.service.get(harness.session, harness.user_id, job.id)

    assert view.error_code == "policy_weapons"
    assert view.error_title == "This request cannot be made into a video"
    assert view.error_message is not None
    assert "weapons" in view.error_message
    assert "internal detail" not in view.error_message


async def test_a_completed_job_view_lists_its_fallback_scenes(harness: Harness) -> None:
    job = harness.world.add_job(harness.user_id, status="completed")
    row = harness.world.add_storyboard(job, {})
    harness.world.add_scene(row, "alpha", 0, is_fallback=True)

    view = await harness.service.get(harness.session, harness.user_id, job.id)

    assert view.fallback_scene_ids == ["alpha"]
