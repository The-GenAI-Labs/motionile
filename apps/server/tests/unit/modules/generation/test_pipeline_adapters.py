import asyncio
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.pipeline import FakeNarrator, make_job
from tests.fakes.storage import InMemoryStorage

from motionile.core.ids import new_id
from motionile.engine.ai.graphs.errors import PipelineError
from motionile.engine.ai.ports import NarrationScript
from motionile.engine.audio.models import WordTiming
from motionile.engine.audio.narration import NarrationError, SceneAudio, assemble_narration
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.audio.providers.base import ProviderUnavailableError
from motionile.engine.render.models import (
    Aspect as EngineAspect,
)
from motionile.engine.render.models import (
    InvalidCompositionError,
    IssueCode,
    ValidationReport,
    ValidationStats,
    make_issue,
)
from motionile.modules.generation.check_gateway import CheckTimedOutError, StorageCheckGateway
from motionile.modules.generation.narrator import MediaNarrator
from motionile.modules.generation.ports import CheckedFrame, CheckOutcome
from motionile.modules.generation.render_gateway import (
    CANCELLED_CODE,
    MediaRenderGateway,
    RenderOwnerNotFoundError,
    progress_from_message,
    progress_of,
)
from motionile.modules.generation.render_queue_checker import RenderQueueChecker
from motionile.modules.media import (
    CHECK_REQUEST_NAME,
    CHECK_RESULT_NAME,
    CompositionCheckRequest,
    CompositionCheckResult,
    FrameEntry,
    RenderOptions,
    RenderOptionsInvalidError,
    RenderProgress,
    RenderSource,
    RenderStage,
    RenderStatus,
    RenderView,
    ResolvedVoice,
    SceneScript,
    composition_check_key,
)

AT = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
USER = UUID(int=11)


@asynccontextmanager
async def transaction() -> AsyncGenerator[AsyncSession]:
    yield AsyncSession()


def voice() -> ResolvedVoice:
    return ResolvedVoice(voice_id=new_id(), provider="fake", provider_voice_id="fake-voice-ada", language="en")


class FakeVoices:
    def __init__(self) -> None:
        self.asked: list[tuple[UUID, UUID]] = []
        self.voice = voice()

    async def resolve_selectable(self, session: AsyncSession, user_id: UUID, voice_id: UUID) -> ResolvedVoice:
        del session
        self.asked.append((user_id, voice_id))
        return self.voice


class FakeNarrationMedia:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[dict[str, Any]] = []
        self.inner = FakeNarrator()

    async def narrate(  # noqa: PLR0913
        self,
        session: AsyncSession,
        user_id: UUID,
        scenes: Sequence[SceneScript],
        voice: ResolvedVoice,
        *,
        padding_ms: int | None = None,
        job_id: UUID | None = None,
    ) -> NarrationDocument:
        del session
        self.calls.append(
            {"user_id": user_id, "scenes": list(scenes), "voice": voice, "padding_ms": padding_ms, "job_id": job_id}
        )
        if self.failure is not None:
            raise self.failure
        job = make_job()
        return await self.inner.narrate(job, [NarrationScript(scene.scene_id, scene.text) for scene in scenes])


def narrator(media: FakeNarrationMedia, voices: FakeVoices) -> MediaNarrator:
    return MediaNarrator(transaction, AsyncSession, media, voices)


SCRIPTS = [NarrationScript("intro", "Hello there world"), NarrationScript("outro", "Goodbye for now")]


async def test_the_narrator_resolves_the_job_voice_and_hands_the_scripts_to_media() -> None:
    media, voices = FakeNarrationMedia(), FakeVoices()
    job = make_job()

    document = await narrator(media, voices).narrate(job, SCRIPTS)

    assert [scene.id for scene in document.scenes] == ["intro", "outro"]
    assert voices.asked == [(job.user_id, job.options.voice_id)]
    (call,) = media.calls
    assert call["job_id"] == job.id
    assert call["user_id"] == job.user_id
    assert call["voice"] == voices.voice
    assert call["scenes"] == [
        SceneScript(scene_id="intro", text="Hello there world"),
        SceneScript(scene_id="outro", text="Goodbye for now"),
    ]
    assert call["padding_ms"] is None


async def test_a_duration_limit_becomes_the_pipeline_failure() -> None:
    media = FakeNarrationMedia(RenderOptionsInvalidError("too long", code="duration_limit_exceeded"))

    with pytest.raises(PipelineError) as raised:
        await narrator(media, FakeVoices()).narrate(make_job(), SCRIPTS)

    assert raised.value.code == "duration_limit_exceeded"


async def test_other_invalid_scenes_become_a_narration_error() -> None:
    media = FakeNarrationMedia(RenderOptionsInvalidError("The scenes are invalid: 1 problem(s)."))

    with pytest.raises(NarrationError, match="invalid"):
        await narrator(media, FakeVoices()).narrate(make_job(), SCRIPTS)


async def test_retryable_provider_errors_propagate_untouched() -> None:
    media = FakeNarrationMedia(ProviderUnavailableError("503"))

    with pytest.raises(ProviderUnavailableError):
        await narrator(media, FakeVoices()).narrate(make_job(), SCRIPTS)


def render_view(render_id: UUID, status: RenderStatus, progress: int, **values: Any) -> RenderView:
    return RenderView(
        id=render_id,
        source=RenderSource.JOB,
        status=status,
        stage=values.pop("stage", None),
        progress=progress,
        options={},
        stage_timings={},
        created_at=AT,
        updated_at=AT,
        **values,
    )


class FakeRenderMedia:
    def __init__(self, render_id: UUID) -> None:
        self.render_id = render_id
        self.created: list[tuple[UUID, str, RenderOptions, RenderSource]] = []
        self.states: list[RenderView] = []
        self.cancelled: list[tuple[UUID, UUID]] = []

    async def create_render(
        self, session: AsyncSession, user_id: UUID, composition_html: str, options: RenderOptions, source: RenderSource
    ) -> RenderView:
        del session
        self.created.append((user_id, composition_html, options, source))
        return render_view(self.render_id, RenderStatus.QUEUED, 0)

    async def get_render(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> RenderView:
        del session, user_id
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return state.model_copy(update={"id": render_id})

    async def cancel_render(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> RenderView:
        del session
        self.cancelled.append((user_id, render_id))
        return render_view(render_id, RenderStatus.CANCELLED, 0)


class FakeFeed:
    def __init__(self, messages: list[RenderProgress | None]) -> None:
        self.messages = messages

    async def next(self, timeout_seconds: float) -> RenderProgress | None:
        await asyncio.sleep(min(timeout_seconds, 0.001))
        return self.messages.pop(0) if self.messages else None


class FakeChannel:
    def __init__(self, messages: list[RenderProgress | None] | None = None) -> None:
        self.feed = FakeFeed(messages or [])
        self.subscribed: list[UUID] = []

    @asynccontextmanager
    async def subscribe(self, render_id: UUID) -> AsyncGenerator[FakeFeed]:
        self.subscribed.append(render_id)
        yield self.feed


class FakeLinks:
    def __init__(self, owner: UUID | None) -> None:
        self.owner = owner
        self.attached: list[tuple[UUID, UUID]] = []

    async def owner_of_render(self, render_id: UUID) -> UUID | None:
        del render_id
        return self.owner

    async def attach_render(self, job_id: UUID, render_id: UUID) -> None:
        self.attached.append((job_id, render_id))


def message(render_id: UUID, status: RenderStatus, progress: int, **values: Any) -> RenderProgress:
    return RenderProgress(render_id=render_id, status=status, progress=progress, at=AT, **values)


def gateway(
    media: FakeRenderMedia, channel: FakeChannel, links: FakeLinks, voices: FakeVoices | None = None
) -> MediaRenderGateway:
    return MediaRenderGateway(
        transaction,
        media,
        channel,
        voices or FakeVoices(),
        default_fps=30,
        poll_seconds=0.001,
        recheck_seconds=0.0,
        links=lambda _session: links,
    )


async def test_starting_a_render_builds_the_options_from_the_job_and_links_it() -> None:
    render_id = new_id()
    media, links = FakeRenderMedia(render_id), FakeLinks(USER)
    job = make_job(aspects=("16:9", "9:16"))
    voices = FakeVoices()

    started = await gateway(media, FakeChannel(), links, voices).start(job, "<html></html>", SCRIPTS)

    assert started == render_id
    ((user_id, html, options, source),) = media.created
    assert (user_id, html, source) == (job.user_id, "<html></html>", RenderSource.JOB)
    assert [aspect.value for aspect in options.aspects] == ["16:9", "9:16"]
    assert options.subtitles
    assert not options.burn_in_subtitles
    assert options.fps == 30
    assert options.is_synthesized
    assert options.scene_ids == ["intro", "outro"]
    assert [scene.text for scene in options.narration.scenes] == ["Hello there world", "Goodbye for now"]
    assert options.narration.mode == "synthesize"
    assert voices.asked == [(job.user_id, job.options.voice_id)]
    assert links.attached == [(job.id, render_id)]


async def test_following_ends_at_once_for_a_finished_render() -> None:
    render_id = new_id()
    media = FakeRenderMedia(render_id)
    media.states = [render_view(render_id, RenderStatus.COMPLETED, 100)]

    steps = [step async for step in gateway(media, FakeChannel(), FakeLinks(USER)).follow(render_id)]

    assert len(steps) == 1
    assert (steps[0].terminal, steps[0].failed, steps[0].progress) == (True, False, 100)


async def test_following_yields_channel_messages_until_the_terminal_one() -> None:
    render_id = new_id()
    media = FakeRenderMedia(render_id)
    media.states = [render_view(render_id, RenderStatus.QUEUED, 0)]
    channel = FakeChannel(
        [
            message(render_id, RenderStatus.CAPTURING, 40, stage=RenderStage.CAPTURING),
            message(render_id, RenderStatus.COMPLETED, 100, stage=RenderStage.FINALIZING),
            message(render_id, RenderStatus.FAILED, 0),
        ]
    )

    steps = [step async for step in gateway(media, channel, FakeLinks(USER)).follow(render_id)]

    assert [(step.status, step.progress, step.terminal) for step in steps if step.progress != 0 or step.terminal] == [
        ("capturing", 40, False),
        ("completed", 100, True),
    ]
    assert channel.subscribed == [render_id]


async def test_following_rechecks_the_database_when_no_message_arrives() -> None:
    render_id = new_id()
    media = FakeRenderMedia(render_id)
    media.states = [
        render_view(render_id, RenderStatus.QUEUED, 0),
        render_view(render_id, RenderStatus.CAPTURING, 55, stage=RenderStage.CAPTURING),
        render_view(render_id, RenderStatus.FAILED, 55, error_code="timeout"),
    ]

    steps = [step async for step in gateway(media, FakeChannel(), FakeLinks(USER)).follow(render_id)]

    assert steps[-1].terminal
    assert steps[-1].failed
    assert steps[-1].error_code == "timeout"
    assert [step.progress for step in steps][:2] == [0, 55]


async def test_a_cancelled_render_counts_as_failed_with_a_code() -> None:
    render_id = new_id()

    progress = progress_of(render_id, RenderStatus.CANCELLED, None, 20, None)

    assert (progress.terminal, progress.failed, progress.error_code) == (True, True, CANCELLED_CODE)


async def test_a_running_render_carries_no_error() -> None:
    progress = progress_from_message(message(new_id(), RenderStatus.MIXING, 30, stage=RenderStage.MIXING))

    assert (progress.stage, progress.terminal, progress.failed, progress.error_code) == ("mixing", False, False, None)


async def test_cancelling_reaches_media_as_the_owner() -> None:
    render_id = new_id()
    media = FakeRenderMedia(render_id)

    await gateway(media, FakeChannel(), FakeLinks(USER)).cancel(render_id)

    assert media.cancelled == [(USER, render_id)]


async def test_a_render_that_no_job_owns_cannot_be_followed_or_cancelled() -> None:
    render_id = new_id()
    media = FakeRenderMedia(render_id)
    orphan = gateway(media, FakeChannel(), FakeLinks(None))

    with pytest.raises(RenderOwnerNotFoundError):
        await orphan.cancel(render_id)
    with pytest.raises(RenderOwnerNotFoundError):
        _ = [step async for step in orphan.follow(render_id)]


def narration_document() -> NarrationDocument:
    audio = [
        SceneAudio(
            id=script.scene_id,
            text=script.text,
            duration_ms=1_000,
            words=(WordTiming(script.text.split()[0], 0, 400),),
        )
        for script in SCRIPTS
    ]
    return assemble_narration(audio, 400)


def checked_request(*, want_frames: bool = False) -> CompositionCheckRequest:
    return CompositionCheckRequest(
        html="<html></html>",
        narration=narration_document(),
        aspects=(EngineAspect.LANDSCAPE,),
        want_frames=want_frames,
    )


class InlineWorker:
    def __init__(self, storage: InMemoryStorage, report: ValidationReport, *, frames: int = 0) -> None:
        self.storage = storage
        self.report = report
        self.frames = frames
        self.deferred: list[tuple[UUID, str]] = []
        self.silent = False

    async def __call__(self, job_id: UUID, check_id: str) -> None:
        self.deferred.append((job_id, check_id))
        if self.silent:
            return
        entries: list[FrameEntry] = []
        for index in range(self.frames):
            key = composition_check_key(job_id, check_id, "frames", f"{index:04d}.png")
            await self.storage.put(key, one_chunk(b"png-%d" % index), content_type="image/png")
            entries.append(FrameEntry(scene_id="intro", aspect=EngineAspect.LANDSCAPE, time_ms=100 * index, key=key))
        result = CompositionCheckResult(check_id=check_id, report=self.report, frames=tuple(entries))
        await self.storage.put(
            composition_check_key(job_id, check_id, CHECK_RESULT_NAME),
            one_chunk(result.model_dump_json(by_alias=True).encode()),
            content_type="application/json",
        )


async def one_chunk(data: bytes) -> AsyncGenerator[bytes]:
    yield data


def storage_gateway(worker: InlineWorker, *, timeout: float = 5.0) -> StorageCheckGateway:
    return StorageCheckGateway(worker.storage, worker, timeout_seconds=timeout, poll_seconds=0.001)


async def test_the_gateway_stores_the_request_defers_the_task_and_returns_the_result() -> None:
    job_id = new_id()
    worker = InlineWorker(InMemoryStorage(), ValidationReport(stats=ValidationStats(scenes=2)))
    request = checked_request()

    outcome = await storage_gateway(worker).run(job_id, request)

    assert outcome.report.valid
    assert worker.deferred == [(job_id, request.check_id)]
    stored = worker.storage.objects[composition_check_key(job_id, request.check_id, CHECK_REQUEST_NAME)]
    assert CompositionCheckRequest.model_validate_json(stored.data) == request


async def test_a_stored_result_is_reused_without_deferring_again() -> None:
    job_id = new_id()
    worker = InlineWorker(InMemoryStorage(), ValidationReport())
    gateway_ = storage_gateway(worker)
    request = checked_request()
    await gateway_.run(job_id, request)

    await gateway_.run(job_id, request)

    assert len(worker.deferred) == 1


async def test_frames_come_back_as_png_bytes() -> None:
    worker = InlineWorker(InMemoryStorage(), ValidationReport(), frames=2)

    outcome = await storage_gateway(worker).run(new_id(), checked_request(want_frames=True))

    assert [(frame.scene_id, frame.aspect, frame.png) for frame in outcome.frames] == [
        ("intro", "16:9", b"png-0"),
        ("intro", "16:9", b"png-1"),
    ]


async def test_a_check_that_never_finishes_times_out() -> None:
    worker = InlineWorker(InMemoryStorage(), ValidationReport())
    worker.silent = True

    with pytest.raises(CheckTimedOutError):
        await storage_gateway(worker, timeout=0.05).run(new_id(), checked_request())


class StubGateway:
    def __init__(self, outcome: CheckOutcome) -> None:
        self.outcome = outcome
        self.requests: list[tuple[UUID, CompositionCheckRequest]] = []

    async def run(self, job_id: UUID, request: CompositionCheckRequest) -> CheckOutcome:
        self.requests.append((job_id, request))
        return self.outcome


async def test_the_checker_maps_engine_issues_to_pipeline_issues() -> None:
    overflow = make_issue(IssueCode.TEXT_OVERFLOW, "too wide")
    issue = overflow.model_copy(
        update={"scene": "intro", "aspect": "16:9", "time_ms": 900, "selector": "#title", "detail": {"fontSizePx": 24}}
    )
    warning = make_issue(IssueCode.EMPTY_SCENE, "blank")
    job_id = new_id()
    stub = StubGateway(CheckOutcome(ValidationReport(issues=(issue, warning), stats=ValidationStats(scenes=2))))
    checker = RenderQueueChecker(job_id, stub)

    check = await checker.check("<html></html>", narration_document(), ["16:9"])

    assert not check.valid
    first, second = check.issues
    assert (first.code, first.severity, first.kind, first.scene_id, first.aspect, first.time_ms) == (
        "text_overflow",
        "error",
        "layout",
        "intro",
        "16:9",
        900,
    )
    assert first.detail == {"fontSizePx": 24, "selector": "#title"}
    assert (second.code, second.is_blocking, second.scene_id) == ("empty_scene", False, None)
    assert check.report["stats"] == {"scenes": 2, "aspects": 0, "samples": 0, "durationMs": 0}
    ((sent_job, sent),) = stub.requests
    assert sent_job == job_id
    assert not sent.want_frames
    assert sent.aspects == (EngineAspect.LANDSCAPE,)


async def test_sampling_asks_for_frames_and_returns_them() -> None:
    frame = CheckedFrame("intro", "16:9", 750, b"png")
    stub = StubGateway(CheckOutcome(ValidationReport(), (frame,)))

    frames = await RenderQueueChecker(new_id(), stub).sample_frames("<html></html>", narration_document(), ["16:9"])

    assert [(item.scene_id, item.aspect, item.time_ms, item.png) for item in frames] == [("intro", "16:9", 750, b"png")]
    assert stub.requests[0][1].want_frames


async def test_sampling_a_composition_that_failed_the_static_checks_is_an_engine_error() -> None:
    broken = make_issue(IssueCode.FORBIDDEN_ELEMENT, "iframe")
    stub = StubGateway(CheckOutcome(ValidationReport(issues=(broken,))))

    with pytest.raises(InvalidCompositionError):
        await RenderQueueChecker(new_id(), stub).sample_frames("<html></html>", narration_document(), ["16:9"])


async def test_sampling_nothing_without_errors_is_an_empty_list() -> None:
    stub = StubGateway(CheckOutcome(ValidationReport()))

    assert await RenderQueueChecker(new_id(), stub).sample_frames("x", narration_document(), ["16:9"]) == []
