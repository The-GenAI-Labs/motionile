import json
from pathlib import Path
from uuid import UUID

import pytest
from tests.unit.modules.media.render_support import (
    Rig,
    build_rig,
    render_options,
    request_options,
)
from tests.unit.modules.media.support import USER_A

from motionile.engine.audio.providers.base import ProviderRejectedError, ProviderUnavailableError
from motionile.engine.audio.wav import build_wav
from motionile.engine.render.models import (
    Aspect,
    CaptureCancelledError,
    IssueCode,
    NetworkViolationError,
    ValidationReport,
    make_issue,
)
from motionile.modules.media.domain import RenderStage
from motionile.modules.media.pipeline import classify
from motionile.modules.media.render_events import RenderProgress
from motionile.modules.media.render_options import stored_options

STAGE_ORDER = ["preparing", "voicing", "mixing", "capturing", "encoding", "finalizing"]


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return build_rig(tmp_path / "work")


async def collect(rig: Rig, render_id: UUID) -> list[RenderProgress]:
    received: list[RenderProgress] = []
    async with rig.events.subscribe(render_id) as subscription:
        await rig.pipeline.run(render_id)
        silent = 0
        while silent < 2:
            message = await subscription.next(0.2)
            if message is None:
                silent += 1
                continue
            silent = 0
            received.append(message)
    return received


async def test_a_render_runs_every_stage_and_completes(rig: Rig) -> None:
    render_id = await rig.queue_render()

    messages = await collect(rig, render_id)

    render = rig.render(render_id)
    assert render.status == "completed"
    assert render.progress == 100
    assert render.completed_at is not None
    assert set(render.checkpoints) == set(STAGE_ORDER)
    assert set(render.stage_timings) == set(STAGE_ORDER)
    assert render.mixed_audio_asset_id is not None
    assert render.subtitles_vtt_asset_id is not None
    assert render.subtitles_srt_asset_id is not None
    assert render.duration_ms is not None
    assert render.duration_ms > 0
    assert {item.aspect for item in rig.world.renditions.values()} == {"16:9", "9:16"}
    assert all(item.status == "ready" for item in rig.world.renditions.values())
    assert messages[-1].status.value == "completed"
    assert [message.progress for message in messages] == sorted(message.progress for message in messages)
    keys = set(rig.storage.objects)
    assert f"media/u/{USER_A}/renders/{render_id}/16x9.mp4" in keys
    assert f"media/u/{USER_A}/renders/{render_id}/poster-9x16.webp" in keys
    assert f"media/u/{USER_A}/renders/{render_id}/subtitles.vtt" in keys
    assert f"media/u/{USER_A}/renders/{render_id}/audio.m4a" in keys


async def test_each_stage_moves_the_status_with_its_checkpoint(rig: Rig) -> None:
    render_id = await rig.queue_render()
    rig.toolchain.capture_failure_at = (Aspect.LANDSCAPE, 0)

    with pytest.raises(ConnectionError):
        await rig.pipeline.run(render_id)

    render = rig.render(render_id)
    assert render.status == "capturing"
    assert render.stage == "capturing"
    assert set(render.checkpoints) >= {"preparing", "voicing", "mixing"}
    assert "capturing" not in render.checkpoints
    keys = render.checkpoints["voicing"]["keys"]
    assert keys["narration"] == f"work/renders/{render_id}/narration.json"
    assert render.checkpoints["voicing"]["paddingMs"] == 400


async def test_a_retry_resumes_without_repeating_finished_work(rig: Rig) -> None:
    render_id = await rig.queue_render()
    rig.toolchain.capture_failure_at = (Aspect.PORTRAIT, 1)
    with pytest.raises(ConnectionError):
        await rig.pipeline.run(render_id)
    captured_before = list(rig.toolchain.captured)
    spoken_before = len(rig.speech.calls)
    validations_before = rig.toolchain.validations
    assert (Aspect.PORTRAIT, 0) in captured_before
    assert all(aspect is not Aspect.PORTRAIT or index == 0 for aspect, index in captured_before)

    rig.toolchain.capture_failure_at = None
    await rig.pipeline.run(render_id)

    captured_after = rig.toolchain.captured[len(captured_before) :]
    assert rig.render(render_id).status == "completed"
    assert len(rig.speech.calls) == spoken_before
    assert rig.toolchain.validations == validations_before
    assert not set(captured_after) & set(captured_before)
    assert (Aspect.PORTRAIT, 1) in captured_after


async def test_finished_aspects_are_not_encoded_twice(rig: Rig) -> None:
    render_id = await rig.queue_render()
    rig.toolchain.assemble_failure = Aspect.PORTRAIT
    with pytest.raises(ConnectionError):
        await rig.pipeline.run(render_id)
    assert rig.toolchain.assembled == [Aspect.LANDSCAPE]
    assert rig.render(render_id).status == "encoding"

    rig.toolchain.assemble_failure = None
    await rig.pipeline.run(render_id)

    assert rig.toolchain.assembled == [Aspect.LANDSCAPE, Aspect.PORTRAIT]
    assert rig.render(render_id).status == "completed"


async def test_a_failing_validation_ends_the_render_with_the_report(rig: Rig) -> None:
    issue = make_issue(IssueCode.FONT_TOO_SMALL, "Text is 24px")
    rig.toolchain.report = ValidationReport(issues=(issue,))
    render_id = await rig.queue_render()

    await rig.pipeline.run(render_id)

    render = rig.render(render_id)
    assert render.status == "failed"
    assert render.error_code == "validation_failed"
    assert render.validation_report is not None
    assert "font_too_small" in [item["code"] for item in render.validation_report["issues"]]
    assert rig.toolchain.captured == []


async def test_a_sandbox_violation_fails_safely_and_keeps_the_issue(rig: Rig) -> None:
    rig.toolchain.validation_failure = NetworkViolationError(["https://evil.example/x"])
    render_id = await rig.queue_render()

    await rig.pipeline.run(render_id)

    render = rig.render(render_id)
    assert render.status == "failed"
    assert render.error_code == "network_violation"
    assert render.error_message is not None
    assert "evil.example" not in render.error_message
    assert render.validation_report is not None
    assert "network_violation" in [item["code"] for item in render.validation_report["issues"]]


async def test_an_invalid_composition_fails_in_preparing(rig: Rig) -> None:
    render_id = await rig.queue_render(html="<html><body><iframe src='https://x.example'></iframe></body></html>")

    await rig.pipeline.run(render_id)

    render = rig.render(render_id)
    assert render.status == "failed"
    assert render.error_code == "invalid_composition"
    assert render.stage == "preparing"
    assert rig.speech.calls == []


async def test_a_scene_mismatch_is_an_invalid_composition(rig: Rig) -> None:
    render_id = await rig.queue_render(html='<html><body><section data-scene="intro"></section></body></html>')

    await rig.pipeline.run(render_id)

    assert rig.render(render_id).error_code == "invalid_composition"


async def test_cancellation_requested_before_the_start_ends_cancelled(rig: Rig) -> None:
    render_id = await rig.queue_render()
    await rig.events.flag_cancel(render_id)

    await rig.pipeline.run(render_id)

    render = rig.render(render_id)
    assert render.status == "cancelled"
    assert render.completed_at is not None
    assert render.error_code is None


async def test_cancellation_during_capture_ends_cancelled_and_removes_the_temp_directory(
    rig: Rig, tmp_path: Path
) -> None:
    render_id = await rig.queue_render()
    rig.toolchain.capture_failure_at = (Aspect.LANDSCAPE, 1)
    rig.toolchain.capture_failure = CaptureCancelledError("cancelled")

    await rig.pipeline.run(render_id)

    assert rig.render(render_id).status == "cancelled"
    assert list((tmp_path / "work").iterdir()) == []


async def test_the_temp_directory_is_removed_when_the_task_will_retry(rig: Rig, tmp_path: Path) -> None:
    render_id = await rig.queue_render()
    rig.toolchain.capture_failure_at = (Aspect.LANDSCAPE, 0)

    with pytest.raises(ConnectionError):
        await rig.pipeline.run(render_id)

    assert list((tmp_path / "work").iterdir()) == []


async def test_a_terminal_render_is_left_alone(rig: Rig) -> None:
    render_id = await rig.queue_render()
    await rig.pipeline.run(render_id)
    puts = len(rig.storage.puts)

    await rig.pipeline.run(render_id)

    assert len(rig.storage.puts) == puts


async def test_a_missing_render_is_ignored(rig: Rig) -> None:
    await rig.pipeline.run(UUID(int=99))


async def test_a_deactivated_music_track_fails_the_render(rig: Rig) -> None:
    track = rig.add_track()
    render_id = await rig.queue_render(render_options(musicTrackId=str(track.id)))
    track.is_active = False

    await rig.pipeline.run(render_id)

    render = rig.render(render_id)
    assert render.status == "failed"
    assert render.error_code == "music_track_unavailable"


async def test_the_music_track_reaches_the_mix(rig: Rig) -> None:
    track = rig.add_track()
    render_id = await rig.queue_render(render_options(musicTrackId=str(track.id)))

    await rig.pipeline.run(render_id)

    assert rig.render(render_id).status == "completed"
    assert rig.toolchain.mixes[0].music is not None
    assert rig.toolchain.mixes[0].tail_ms == 1000
    assert rig.toolchain.mixes[0].padding_ms == 400


async def test_a_narration_over_the_limit_fails_with_duration_limit_exceeded(tmp_path: Path) -> None:
    short = build_rig(tmp_path / "work", max_duration_ms=1000)
    render_id = await short.queue_render()

    await short.pipeline.run(render_id)

    render = short.render(render_id)
    assert render.status == "failed"
    assert render.error_code == "duration_limit_exceeded"


async def test_a_rejected_synthesis_fails_the_render_with_tts_failed(rig: Rig) -> None:
    rig.speech.provider.failure = ProviderRejectedError("secret provider detail", status_code=400)
    render_id = await rig.queue_render()

    await rig.pipeline.run(render_id)

    render = rig.render(render_id)
    assert render.error_code == "tts_failed"
    assert render.error_message is not None
    assert "secret" not in render.error_message


async def test_a_transient_provider_error_is_left_to_the_task_retry(rig: Rig) -> None:
    rig.speech.provider.failure = ProviderUnavailableError("down")
    render_id = await rig.queue_render()

    with pytest.raises(ProviderUnavailableError):
        await rig.pipeline.run(render_id)

    assert rig.render(render_id).status == "voicing"


async def test_an_uploaded_narration_is_aligned_and_rendered(rig: Rig) -> None:
    audio = {
        "audio-intro": build_wav(b"\x00\x00" * 8000, sample_rate=16000, embedded_text="Hello there friend"),
        "audio-outro": build_wav(b"\x00\x00" * 6000, sample_rate=16000),
    }
    options = stored_options(
        request_options(
            narration={
                "mode": "upload",
                "scenes": [
                    {"sceneId": "intro", "audioPart": "audio-intro", "text": "Hello there friend"},
                    {"sceneId": "outro", "audioPart": "audio-outro"},
                ],
            }
        ),
        None,
        24,
    )
    render_id = await rig.queue_render(options, audio_uploads=audio)

    await rig.pipeline.run(render_id)

    render = rig.render(render_id)
    assert render.status == "completed"
    narration = json.loads(rig.storage.objects[f"work/renders/{render_id}/narration.json"].data)
    assert [scene["id"] for scene in narration["scenes"]] == ["intro", "outro"]
    assert [word["text"] for word in narration["scenes"][0]["words"]] == ["Hello", "there", "friend"]
    assert narration["scenes"][1]["words"]
    assert rig.speech.calls == []


async def test_progress_never_goes_backwards_and_touches_updated_at(rig: Rig) -> None:
    render_id = await rig.queue_render()
    before = rig.render(render_id).updated_at

    messages = await collect(rig, render_id)

    assert rig.render(render_id).updated_at > before
    values = [message.progress for message in messages]
    assert values == sorted(values)
    assert values[-1] == 100
    assert {message.stage for message in messages if message.stage} <= set(RenderStage)


async def test_a_state_change_by_another_actor_stops_the_run_quietly(rig: Rig) -> None:
    render_id = await rig.queue_render()

    def fail_elsewhere() -> None:
        render = rig.render(render_id)
        render.status = "failed"
        render.error_code = "render_stalled"
        render.completed_at = render.updated_at

    rig.toolchain.after_mix = fail_elsewhere

    await rig.pipeline.run(render_id)

    assert rig.render(render_id).status == "failed"
    assert rig.render(render_id).error_code == "render_stalled"
    assert rig.toolchain.captured == []


def test_error_classification_keeps_infrastructure_errors_retryable() -> None:
    assert classify(ConnectionError("db")) is None
    assert classify(OSError("disk")) is None
    assert classify(TimeoutError()) is None
