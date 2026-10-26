from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.pipeline_storage import InMemoryPipelineStorage
from tests.unit.modules.generation.support import Harness, storyboard_content, valid_storyboard

from motionile.engine.ai.job_options import JobStatus
from motionile.engine.ai.ports import (
    CompositionIssue,
    JobEventDraft,
    SceneAttemptKind,
    StoryboardOrigin,
    TopicContext,
)
from motionile.engine.ai.scenes.fallback import fallback_module
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.audio.models import WordTiming
from motionile.engine.audio.narration import SceneAudio, assemble_narration
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.modules.generation.job_events import JobEvents, JobMessage
from motionile.modules.generation.models import Job
from motionile.modules.generation.pipeline_repository import PipelineStorage
from motionile.modules.generation.pipeline_store import (
    SceneRowMissingError,
    SqlPipelineStore,
    StoryboardNotApprovedError,
    module_checksum,
)


class RecordingJobEvents(JobEvents):
    def __init__(self) -> None:
        self.published: list[tuple[UUID, JobMessage]] = []

    async def publish(self, job_id: UUID, message: JobMessage) -> None:
        self.published.append((job_id, message))


class Fixture:
    def __init__(self, harness: Harness) -> None:
        self.harness = harness
        self.storage = InMemoryPipelineStorage(harness.world)
        self.events = RecordingJobEvents()

        @asynccontextmanager
        async def transaction() -> AsyncGenerator[AsyncSession]:
            yield harness.session

        def repository(session: AsyncSession, events: JobEvents) -> PipelineStorage:
            del session, events
            return self.storage

        self.store = SqlPipelineStore(transaction, harness.service, self.events, harness.clock, repository)

    async def started_job(self, status: str = "queued") -> Job:
        await self.harness.fund(500)
        view = await self.harness.service.create(
            self.harness.session, self.harness.user_id, self.harness.request(), self.harness.key()
        )
        job = self.harness.world.jobs[view.id]
        job.status = status
        return job

    async def approved(self, job: Job) -> None:
        stored = await self.store.save_storyboard(job.id, valid_storyboard(), StoryboardOrigin.PLANNER)
        await self.store.approve_storyboard(job.id, stored.id)


def narration_for(ms_per_word: int = 300) -> NarrationDocument:
    board = valid_storyboard()
    audio = [
        SceneAudio(
            id=scene.id,
            text=scene.narration,
            duration_ms=len(scene.narration.split()) * ms_per_word,
            words=tuple(
                WordTiming(word, index * ms_per_word, (index + 1) * ms_per_word)
                for index, word in enumerate(scene.narration.split())
            ),
        )
        for scene in board.scenes
    ]
    return assemble_narration(audio, 400)


def module_for(scene_id: str, builder: str = "ctx.at(0);") -> SceneModule:
    return SceneModule(scene_id=scene_id, builder=builder)


@pytest.fixture
def fixture(harness: Harness) -> Fixture:
    return Fixture(harness)


async def test_a_persisted_event_is_stored_with_a_sanitized_payload(fixture: Fixture) -> None:
    job = await fixture.started_job("planning")
    draft = JobEventDraft("stage.completed", "plan", {"stage": "plan", "durationMs": 40, "prompt": "leak"})

    await fixture.store.emit(job.id, draft)

    stored = fixture.harness.world.events[-1]
    assert (stored.type, stored.stage, stored.payload) == (
        "stage.completed",
        "plan",
        {"stage": "plan", "durationMs": 40},
    )
    assert fixture.storage.touched == [job.id]
    assert fixture.events.published == []


async def test_a_transient_event_is_only_published(fixture: Fixture) -> None:
    job = await fixture.started_job("rendering")
    before = len(fixture.harness.world.events)

    await fixture.store.emit(
        job.id, JobEventDraft("render.progress", "render", {"renderId": "r", "progress": 3}, persist=False)
    )

    assert len(fixture.harness.world.events) == before
    ((published_for, message),) = fixture.events.published
    assert published_for == job.id
    assert message.id is None
    assert (message.type, message.stage, message.payload) == (
        "render.progress",
        "render",
        {"renderId": "r", "progress": 3},
    )
    assert message.at == fixture.harness.clock.now()


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        ("queued", JobStatus.PLANNING, True),
        ("planning", JobStatus.PLANNING, True),
        ("planning", JobStatus.AWAITING_APPROVAL, True),
        ("awaiting_approval", JobStatus.VOICING, True),
        ("awaiting_approval", JobStatus.PLANNING, True),
        ("validating", JobStatus.GENERATING, True),
        ("generating", JobStatus.GENERATING, True),
        ("planning", JobStatus.RENDERING, False),
        ("completed", JobStatus.PLANNING, False),
        ("failed", JobStatus.FAILED, False),
    ],
)
async def test_transitions_follow_the_state_machine_and_allow_staying_put(
    fixture: Fixture, current: str, target: JobStatus, allowed: bool
) -> None:
    job = await fixture.started_job(current)

    assert await fixture.store.transition(job.id, target, stage="x") is allowed

    assert job.status == (target.value if allowed else current)


async def test_a_transition_fails_once_cancellation_was_requested(fixture: Fixture) -> None:
    job = await fixture.started_job("planning")
    job.cancel_requested_at = fixture.harness.clock.now()

    assert not await fixture.store.transition(job.id, JobStatus.VOICING, stage="voice")


async def test_a_snapshot_describes_the_job_for_the_graph(fixture: Fixture) -> None:
    job = await fixture.started_job("planning")
    topic = TopicContext(job.id, "DNS", None, "Backend", "Networking")
    job.topic_id = topic.id
    fixture.storage.topics[topic.id] = topic

    snapshot = await fixture.store.snapshot(job.id)

    assert (snapshot.id, snapshot.user_id, snapshot.status) == (job.id, job.user_id, JobStatus.PLANNING)
    assert snapshot.topic == topic
    assert snapshot.parent is None
    assert not snapshot.cancel_requested
    assert snapshot.options.duration_seconds == 60


async def test_a_snapshot_carries_the_approved_storyboard_of_the_parent(fixture: Fixture) -> None:
    parent = fixture.harness.world.add_job(fixture.harness.user_id, status="completed")
    row = fixture.harness.world.add_storyboard(parent, storyboard_content())
    row.approved_at = fixture.harness.clock.now()
    child = await fixture.started_job("planning")
    child.parent_job_id = parent.id

    snapshot = await fixture.store.snapshot(child.id)

    assert snapshot.parent is not None
    assert snapshot.parent.job_id == parent.id
    assert snapshot.parent.storyboard == valid_storyboard()


async def test_storyboard_versions_count_up_and_only_the_approved_one_is_approved(fixture: Fixture) -> None:
    job = await fixture.started_job("planning")

    first = await fixture.store.save_storyboard(job.id, valid_storyboard(), StoryboardOrigin.PLANNER)
    second = await fixture.store.save_storyboard(job.id, valid_storyboard(), StoryboardOrigin.CRITIC)

    assert (first.version, second.version) == (1, 2)
    assert await fixture.store.approved_storyboard(job.id) is None
    latest = await fixture.store.latest_storyboard(job.id)
    assert latest is not None
    assert (latest.version, latest.approved) == (2, False)
    await fixture.store.approve_storyboard(job.id, second.id)
    await fixture.store.approve_storyboard(job.id, second.id)
    approved = await fixture.store.approved_storyboard(job.id)
    assert approved is not None
    assert (approved.version, approved.approved, approved.content) == (2, True, valid_storyboard())
    assert fixture.harness.world.storyboards[0].origin == "planner"
    assert fixture.harness.world.storyboards[1].origin == "critic"


async def test_narration_survives_a_round_trip_through_the_scene_rows(fixture: Fixture) -> None:
    job = await fixture.started_job("voicing")
    await fixture.approved(job)
    narration = narration_for()

    assert await fixture.store.narration(job.id) is None
    await fixture.store.save_narration(job.id, narration)

    assert await fixture.store.narration(job.id) == narration
    rows = fixture.harness.world.scenes
    assert [(row.scene_key, row.position, row.status) for row in rows] == [
        (scene.id, scene.index, "voiced") for scene in narration.scenes
    ]
    assert [row.actual_duration_ms for row in rows] == [scene.duration_ms for scene in narration.scenes]


async def test_saving_the_narration_twice_updates_the_same_rows(fixture: Fixture) -> None:
    job = await fixture.started_job("voicing")
    await fixture.approved(job)

    await fixture.store.save_narration(job.id, narration_for(300))
    await fixture.store.save_narration(job.id, narration_for(250))

    assert len(fixture.harness.world.scenes) == len(valid_storyboard().scenes)
    assert await fixture.store.narration(job.id) == narration_for(250)


async def test_narration_needs_an_approved_storyboard(fixture: Fixture) -> None:
    job = await fixture.started_job("voicing")

    with pytest.raises(StoryboardNotApprovedError):
        await fixture.store.save_narration(job.id, narration_for())
    assert await fixture.store.narration(job.id) is None


async def test_scene_modules_are_stored_with_a_log_of_codes_and_checksums(fixture: Fixture) -> None:
    job = await fixture.started_job("generating")
    await fixture.approved(job)
    await fixture.store.save_narration(job.id, narration_for())
    first = module_for("scene-0")
    repaired = module_for("scene-0", "ctx.at(1);")
    issue = CompositionIssue("text_overflow", "error", "layout", "too wide", scene_id="scene-0")

    await fixture.store.save_scene_module(job.id, first, SceneAttemptKind.INITIAL, [])
    await fixture.store.save_scene_module(job.id, repaired, SceneAttemptKind.REPAIR, [issue, issue])
    await fixture.store.save_scene_module(job.id, fallback_module("scene-0"), SceneAttemptKind.FALLBACK, [])

    row = fixture.harness.world.scenes[0]
    assert row.repair_attempts == 1
    assert row.is_fallback
    assert row.status == "generated"
    assert [(entry["attempt"], entry["kind"], entry["issueCodes"]) for entry in row.attempt_log] == [
        (1, "initial", []),
        (2, "repair", ["text_overflow"]),
        (3, "fallback", []),
    ]
    assert row.attempt_log[0]["checksum"] == module_checksum(first)
    assert len(str(row.attempt_log[0]["checksum"])) == 16
    assert "builder" not in str(row.attempt_log)


async def test_scene_records_report_attempts_only_for_repairs(fixture: Fixture) -> None:
    job = await fixture.started_job("generating")
    await fixture.approved(job)
    await fixture.store.save_narration(job.id, narration_for())
    await fixture.store.save_scene_module(job.id, module_for("scene-1"), SceneAttemptKind.INITIAL, [])
    await fixture.store.save_scene_module(job.id, module_for("scene-1", "ctx.at(2);"), SceneAttemptKind.REPAIR, [])

    records = await fixture.store.scenes(job.id)

    assert [record.scene_id for record in records] == ["scene-0", "scene-1", "scene-2", "scene-3"]
    assert records[0].module is None
    assert (records[1].attempts, records[1].is_fallback) == (1, False)
    assert records[1].module == module_for("scene-1", "ctx.at(2);")


async def test_a_scene_without_a_row_is_an_error(fixture: Fixture) -> None:
    job = await fixture.started_job("generating")
    await fixture.approved(job)

    with pytest.raises(SceneRowMissingError):
        await fixture.store.save_scene_module(job.id, module_for("scene-0"), SceneAttemptKind.INITIAL, [])


async def test_empty_reports_leave_the_stored_ones_unchanged(fixture: Fixture) -> None:
    job = await fixture.started_job("validating")

    await fixture.store.save_reports(job.id, validation={"valid": True}, review={})
    await fixture.store.save_reports(job.id, validation={}, review={"issues": []})
    await fixture.store.save_reports(job.id, validation={}, review={})

    assert job.reports == {"validation": {"valid": True}, "review": {"issues": []}}


async def test_attaching_a_render_is_idempotent_and_keeps_the_first_render(fixture: Fixture) -> None:
    job = await fixture.started_job("rendering")
    first, second = UUID(int=1), UUID(int=2)

    await fixture.store.attach_render(job.id, first)
    await fixture.store.attach_render(job.id, first)
    await fixture.store.attach_render(job.id, second)

    assert job.render_id == first


async def test_failing_records_the_error_and_releases_the_credits(fixture: Fixture) -> None:
    job = await fixture.started_job("generating")

    await fixture.store.fail(job.id, "tts_failed", "no voice")

    assert (job.status, job.error_code) == ("failed", "tts_failed")
    assert fixture.harness.wallet() == (500, 0)


async def test_completing_charges_for_the_final_duration(fixture: Fixture) -> None:
    job = await fixture.started_job("rendering")

    await fixture.store.complete(job.id, final_duration_ms=30_100)

    assert (job.status, job.credits_charged) == ("completed", 82)
    assert fixture.harness.wallet() == (500 - 82, 0)


async def test_finishing_a_cancellation_releases_the_credits(fixture: Fixture) -> None:
    job = await fixture.started_job("voicing")
    await fixture.harness.service.cancel(fixture.harness.session, fixture.harness.user_id, job.id)

    await fixture.store.finish_cancellation(job.id)

    assert job.status == "cancelled"
    assert fixture.harness.wallet() == (500, 0)
