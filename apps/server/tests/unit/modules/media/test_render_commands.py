from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from tests.fakes.media import fake_session
from tests.fakes.render_jobs import FlakyStorage
from tests.unit.modules.media.render_support import COMPOSITION, VOICE, Rig, build_rig, render_options, request_options
from tests.unit.modules.media.support import USER_A, USER_B

from motionile.engine.audio.audio_validation import AudioRejectedError, ValidatedAudio
from motionile.engine.audio.wav import build_wav
from motionile.modules.media import (
    CompositionTooLargeError,
    MediaService,
    MusicTrackUnavailableError,
    PresignedDelivery,
    RenderAudioRejectedError,
    RenderNotFoundError,
    RenderOptionsInvalidError,
    RenderSource,
    RenderStatus,
    SceneScript,
)
from motionile.modules.media.render_commands import COMPOSITION_MAX_BYTES
from motionile.modules.media.render_events import RenderProgress
from motionile.modules.media.render_options import RenderOptions, stored_options

WAV = build_wav(b"\x00\x00" * 4000, sample_rate=16000)


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return build_rig(tmp_path / "work")


def upload_options() -> RenderOptions:
    return stored_options(
        request_options(
            narration={
                "mode": "upload",
                "scenes": [{"sceneId": "intro", "audioPart": "audio-intro"}],
            }
        ),
        None,
        24,
    )


async def test_creating_a_render_stores_the_composition_and_queues_the_run(rig: Rig) -> None:
    async with rig.world.transaction() as session:
        view = await rig.commands().create_render(session, USER_A, COMPOSITION, render_options(), RenderSource.JOB)

    stored = rig.render(view.id)
    asset = rig.world.assets[stored.composition_asset_id]
    assert view.status is RenderStatus.QUEUED
    assert view.progress == 0
    assert view.source is RenderSource.JOB
    assert asset.storage_key == f"media/u/{USER_A}/renders/{view.id}/composition.html"
    assert asset.content_type == "text/plain"
    assert asset.kind == "html"
    assert rig.storage.objects[asset.storage_key].data == COMPOSITION.encode()
    assert rig.dispatched == [view.id]
    assert view.options["musicTrackId"] is None
    assert view.options["aspects"] == ["16:9", "9:16"]
    assert view.options["narration"]["voice"]["providerVoiceId"] == VOICE.provider_voice_id


async def test_uploaded_scene_audio_goes_under_the_work_prefix(rig: Rig) -> None:
    view = await rig.commands().create_render(
        fake_session(),
        USER_A,
        COMPOSITION,
        upload_options(),
        RenderSource.JOB,
        audio_uploads={"audio-intro": WAV},
    )

    key = f"work/renders/{view.id}/upload-intro.wav"
    assert rig.storage.objects[key].data == WAV
    assert rig.render(view.id).checkpoints["upload"]["keys"] == {"intro": key}


async def test_upload_parts_must_match_the_scenes(rig: Rig) -> None:
    commands = rig.commands()

    with pytest.raises(RenderOptionsInvalidError):
        await commands.create_render(
            fake_session(),
            USER_A,
            COMPOSITION,
            upload_options(),
            RenderSource.JOB,
            audio_uploads={},
        )
    with pytest.raises(RenderOptionsInvalidError):
        await commands.create_render(
            fake_session(), USER_A, COMPOSITION, render_options(), RenderSource.JOB, audio_uploads={"x": WAV}
        )
    assert rig.dispatched == []


async def test_rejected_audio_is_reported_with_its_reason(rig: Rig) -> None:
    async def reject(data: bytes) -> ValidatedAudio:
        del data
        raise AudioRejectedError("too_short", "shorter than the minimum")

    commands = rig.commands(reject)

    with pytest.raises(RenderAudioRejectedError) as raised:
        await commands.create_render(
            fake_session(),
            USER_A,
            COMPOSITION,
            upload_options(),
            RenderSource.JOB,
            audio_uploads={"audio-intro": WAV},
        )

    assert raised.value.code == "render_audio_rejected"
    assert raised.value.extensions == {"reason": "too_short"}
    assert rig.dispatched == []


async def test_an_oversized_composition_is_rejected(rig: Rig) -> None:
    with pytest.raises(CompositionTooLargeError):
        await rig.commands().create_render(
            fake_session(), USER_A, "x" * (COMPOSITION_MAX_BYTES + 1), render_options(), RenderSource.JOB
        )

    assert rig.world.renders == {}


async def test_an_inactive_music_track_is_rejected_before_anything_is_stored(rig: Rig) -> None:
    track = rig.add_track(active=False)

    with pytest.raises(MusicTrackUnavailableError):
        await rig.queue_render(render_options(musicTrackId=str(track.id)))

    assert rig.world.renders == {}
    assert not any(key.startswith("media/") for key in rig.storage.objects)


async def test_an_active_music_track_is_stored_in_the_options(rig: Rig) -> None:
    track = rig.add_track()

    render_id = await rig.queue_render(render_options(musicTrackId=str(track.id)))

    assert rig.render(render_id).options["musicTrackId"] == str(track.id)


async def create_then_fail(rig: Rig) -> None:
    async with rig.world.transaction() as session:
        await rig.commands().create_render(
            session,
            USER_A,
            COMPOSITION,
            upload_options(),
            RenderSource.JOB,
            audio_uploads={"audio-intro": WAV},
        )
        raise RuntimeError("rollback")


async def test_a_failed_transaction_discards_the_stored_objects(rig: Rig) -> None:
    with pytest.raises(RuntimeError):
        await create_then_fail(rig)

    assert not [key for key in rig.storage.objects if key.startswith(("work/", "media/"))]


async def test_cancelling_a_queued_render_cancels_it_at_once(rig: Rig) -> None:
    render_id = await rig.queue_render()
    async with rig.events.subscribe(render_id) as subscription:
        async with rig.world.transaction() as session:
            view = await rig.commands().cancel_render(session, USER_A, render_id)
        received: RenderProgress | None = None
        for _ in range(3):
            received = await subscription.next(0.2)
            if received is not None:
                break

    assert view.status is RenderStatus.CANCELLED
    assert view.cancel_requested_at is not None
    assert view.completed_at is not None
    assert await rig.events.cancel_flagged(render_id)
    assert received is not None
    assert received.status is RenderStatus.CANCELLED


async def test_cancelling_an_active_render_only_requests_it(rig: Rig) -> None:
    render_id = await rig.queue_render()
    rig.render(render_id).status = "capturing"

    async with rig.world.transaction() as session:
        view = await rig.commands().cancel_render(session, USER_A, render_id)

    assert view.status is RenderStatus.CAPTURING
    assert view.cancel_requested_at is not None
    assert await rig.events.cancel_flagged(render_id)


async def test_cancelling_a_finished_render_changes_nothing(rig: Rig) -> None:
    render_id = await rig.queue_render()
    rig.render(render_id).status = "completed"

    async with rig.world.transaction() as session:
        first = await rig.commands().cancel_render(session, USER_A, render_id)
        second = await rig.commands().cancel_render(session, USER_A, render_id)

    assert first.status is RenderStatus.COMPLETED
    assert second.status is RenderStatus.COMPLETED
    assert not await rig.events.cancel_flagged(render_id)


async def test_a_foreign_render_cannot_be_cancelled_and_looks_missing(rig: Rig) -> None:
    render_id = await rig.queue_render()

    with pytest.raises(RenderNotFoundError):
        await rig.commands().cancel_render(fake_session(), USER_B, render_id)
    with pytest.raises(RenderNotFoundError):
        await rig.commands().cancel_render(fake_session(), USER_A, UUID(int=5))

    assert rig.render(render_id).cancel_requested_at is None


async def test_narration_is_assembled_with_the_requested_padding(rig: Rig) -> None:
    scenes = [SceneScript(scene_id="a", text="Hello there"), SceneScript(scene_id="b", text="Goodbye now")]

    padded = await rig.commands().narrate(fake_session(), USER_A, scenes, VOICE, padding_ms=250)
    plain = await rig.commands().narrate(fake_session(), USER_A, scenes, VOICE, padding_ms=0)

    assert [scene.id for scene in padded.scenes] == ["a", "b"]
    assert padded.scenes[1].start_ms == padded.scenes[0].duration_ms
    assert padded.scenes[0].duration_ms - plain.scenes[0].duration_ms == 250
    assert padded.scenes[1].duration_ms == plain.scenes[1].duration_ms
    assert padded.total_duration_ms == sum(scene.duration_ms for scene in padded.scenes)


async def test_narration_rejects_empty_and_overlong_input(rig: Rig, tmp_path: Path) -> None:
    with pytest.raises(RenderOptionsInvalidError):
        await rig.commands().narrate(fake_session(), USER_A, [], VOICE)
    long_rig = build_rig(tmp_path / "long", max_duration_ms=1000)
    with pytest.raises(RenderOptionsInvalidError) as raised:
        await long_rig.commands().narrate(fake_session(), USER_A, [SceneScript(scene_id="a", text="word " * 40)], VOICE)
    assert raised.value.code == "duration_limit_exceeded"


async def test_the_service_refuses_render_commands_when_unconfigured() -> None:
    service = MediaService(PresignedDelivery(FlakyStorage(), timedelta(seconds=1)))

    with pytest.raises(RuntimeError):
        await service.cancel_render(fake_session(), USER_A, UUID(int=1))
