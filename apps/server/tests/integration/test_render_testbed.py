import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from PIL import Image
from tests.integration.engine.render.support import (
    GOLDEN_ROOT,
    MALICIOUS_ROOT,
    TINY_COMPOSITION,
    Canary,
    resolve_tools,
)
from tests.integration.media_support import MediaApi
from tests.integration.render_support import (
    BED,
    FAKE_VOICE_ID,
    SEGMENT_MARKER,
    UNKNOWN_VOICE_ID,
    ChaosStorage,
    FakeVoiceLookup,
    RenderBed,
    scalar,
)
from tests.integration.test_auth import csrf

from motionile.core.config import AppEnv, AppSettings, ProvidersMode, RenderSettings, Settings
from motionile.engine.audio.wav import build_wav
from motionile.engine.ffmpeg import FfmpegTools, probe_file
from motionile.engine.render.models import Aspect, RenderEngineConfig
from motionile.engine.render.mux import OutputExpectation, collect_output_problems
from motionile.engine.render.synthetic import synthesize_tone
from motionile.modules.media import (
    MediaService,
    MusicUpload,
    delivery_for,
    music_service_for,
    render_commands_for,
    render_pipeline_for,
)
from motionile.modules.media.dependencies import get_media_service
from motionile.modules.media.pipeline.toolchain import build_toolchain

FPS = 24
TAIL_MS = 600
VIEWPORTS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
CASE_NAMES = ("exfil_fetch", "exfil_websocket", "external_image", "iframe_embed", "form_submit")


@pytest.fixture
def settings(settings: Settings, tmp_path_factory: pytest.TempPathFactory) -> Settings:
    work = tmp_path_factory.mktemp("rw")
    return settings.model_copy(
        update={
            "app": AppSettings(env=AppEnv.CI, providers_mode=ProvidersMode.FAKE),
            "render": RenderSettings(
                work_directory=work,
                x264_preset="veryfast",
                parallel_pages=3,
                chunk_seconds=2,
                tail_ms=TAIL_MS,
                scene_padding_ms=300,
                page_load_timeout_seconds=30,
                ready_timeout_seconds=30,
                frame_timeout_seconds=20,
                min_free_disk_mb=1,
            ),
        }
    )


@pytest.fixture(scope="session")
def tools() -> FfmpegTools:
    found = resolve_tools()
    if found is None:
        pytest.skip("ffmpeg and ffprobe are not available; set RENDER_FFMPEG_PATH and RENDER_FFPROBE_PATH")
    return found


@pytest.fixture
async def bed(media_api: MediaApi, tools: FfmpegTools, settings: Settings) -> AsyncIterator[RenderBed]:
    resources = media_api.resources
    chaos = ChaosStorage(resources.storage)
    resources.storage = chaos
    dispatched: list[UUID] = []
    service = MediaService(
        delivery_for(resources),
        commands=render_commands_for(resources, lambda _session, render_id: dispatched.append(render_id)),
    )
    media_api.app.dependency_overrides[get_media_service] = lambda: service
    media_api.app.state.voice_lookup = FakeVoiceLookup()
    await media_api.grant_permissions(media_api.primary_id, "bed", "render.testbed")
    pipeline = render_pipeline_for(resources, lambda fps: build_toolchain(settings, fps))
    work = settings.render.work_directory
    assert work is not None
    yield RenderBed(media_api, service, pipeline, chaos, tools, work, dispatched)
    media_api.app.dependency_overrides.pop(get_media_service, None)


def golden_html(name: str) -> str:
    return (GOLDEN_ROOT / name / "composition.html").read_text(encoding="utf-8")


def synth_options(scenes: list[dict[str, str]], **overrides: Any) -> dict[str, Any]:
    return {
        "aspects": ["16:9"],
        "fps": FPS,
        "narration": {"mode": "synthesize", "voiceId": str(FAKE_VOICE_ID), "scenes": scenes},
        **overrides,
    }


TINY_SCENES = [
    {"sceneId": "one", "text": "Frames stay identical across runs"},
    {"sceneId": "two", "text": "Second scene"},
]


async def fetch(url: str, **headers: str) -> httpx.Response:
    async with httpx.AsyncClient(timeout=30) as client:
        return await client.get(url, headers=headers)


@dataclass(frozen=True)
class Expected:
    render_id: UUID
    narration_ms: int
    directory: Path


async def check_rendition(bed: RenderBed, expected: Expected, aspect: str, item: dict[str, Any]) -> None:
    render_id, narration_ms, tmp_path = expected.render_id, expected.narration_ms, expected.directory
    assert item["status"] == "ready"
    assert (item["width"], item["height"]) == VIEWPORTS[aspect]
    ranged = await fetch(item["url"], Range="bytes=0-99")
    assert ranged.status_code == 206
    assert len(ranged.content) == 100
    assert ranged.headers["content-range"].startswith("bytes 0-99/")
    slug = aspect.replace(":", "x")
    key = f"media/u/{bed.api.primary_id}/renders/{render_id}/{slug}.mp4"
    video = await bed.download(key, tmp_path / f"{slug}.mp4")
    frames = -(-(narration_ms + TAIL_MS) * FPS // 1000)
    config = RenderEngineConfig(fps=FPS, tools=bed.tools)
    assert await collect_output_problems(config, video, OutputExpectation(Aspect(aspect), frames, FPS)) == []
    probe = await probe_file(bed.tools, video, count_frames=True)
    assert probe.video_streams[0].frame_count == frames
    poster = await fetch(item["posterUrl"])
    assert poster.headers["content-type"] == "image/webp"
    webp = tmp_path / f"{slug}.webp"
    webp.write_bytes(poster.content)
    with Image.open(webp) as image:
        assert image.size == VIEWPORTS[aspect]
    assert (await fetch(item["posterJpegUrl"])).content[:2] == b"\xff\xd8"


@pytest.mark.slow
async def test_a_golden_composition_renders_in_all_three_aspects(bed: RenderBed, tmp_path: Path) -> None:
    created = await bed.post_golden("responsive-scene", aspects=["16:9", "9:16", "1:1"])

    assert created.status_code == 202, created.text
    render_id = UUID(created.json()["id"])
    assert created.json()["status"] == "queued"
    assert created.json()["source"] == "testbed"
    assert bed.dispatched == [render_id]
    queued = await bed.state(render_id)
    assert queued["renditions"] == []

    body = await bed.completed(render_id)

    assert body["progress"] == 100
    assert body["errorCode"] is None
    assert set(body["stageTimings"]) == {"preparing", "voicing", "mixing", "capturing", "encoding", "finalizing"}
    assert body["validationReport"]["valid"] is True
    renditions = {item["aspect"]: item for item in body["renditions"]}
    assert set(renditions) == {"16:9", "9:16", "1:1"}
    for aspect, item in renditions.items():
        await check_rendition(bed, Expected(render_id, body["durationMs"], tmp_path), aspect, item)
    first = body["renditions"][0]
    vtt = await fetch(first["subtitlesUrl"])
    srt = await fetch(first["subtitlesSrtUrl"])
    assert vtt.text.startswith("WEBVTT")
    assert "-->" in vtt.text
    assert srt.text.startswith("1\n00:00:")
    owner = bed.api.primary_id
    mixed = await bed.download(f"media/u/{owner}/renders/{render_id}/audio.m4a", tmp_path / "audio.m4a")
    audio = (await probe_file(bed.tools, mixed)).audio_streams[0]
    assert (audio.codec_name, audio.sample_rate) == ("aac", 48000)
    assert await scalar(bed.api, "SELECT mixed_audio_asset_id IS NOT NULL FROM renders WHERE id = :id", id=render_id)
    assert bed.leftover_directories() == []

    snapshot = await bed.client.get(f"{BED}/{render_id}/events")
    assert snapshot.status_code == 200
    assert snapshot.headers["content-type"].startswith("text/event-stream")
    assert snapshot.text.startswith("event: snapshot\n")
    assert json.loads(snapshot.text.split("data: ")[1].split("\n")[0])["status"] == "completed"


@pytest.mark.slow
async def test_a_resumed_render_equals_a_clean_render_and_skips_finished_segments(
    bed: RenderBed, tmp_path: Path
) -> None:
    clean = UUID((await bed.post_golden("kinetic-typography")).json()["id"])
    await bed.completed(clean)
    clean_puts = [key for key in bed.storage.puts if f"/{clean}/" in key and SEGMENT_MARKER in key]
    assert len(clean_puts) >= 3
    uploaded_before_failure = len(bed.storage.puts)

    interrupted = UUID((await bed.post_golden("kinetic-typography")).json()["id"])
    seen = 0

    async def fail_on_third_segment(key: str) -> None:
        nonlocal seen
        if f"/{interrupted}/" in key and SEGMENT_MARKER in key:
            seen += 1
            if seen == 3:
                raise ConnectionError("injected storage outage")

    bed.storage.before_put = fail_on_third_segment
    with pytest.raises(ConnectionError):
        await bed.run(interrupted)
    bed.storage.before_put = None
    stored = [key for key in bed.storage.puts[uploaded_before_failure:] if f"/{interrupted}/" in key]
    segments_before = [key for key in stored if SEGMENT_MARKER in key]
    assert len(segments_before) == 2
    assert (await bed.state(interrupted))["status"] == "capturing"
    assert bed.leftover_directories() == []

    resume_from = len(bed.storage.puts)
    await bed.completed(interrupted)

    again = [key for key in bed.storage.puts[resume_from:] if SEGMENT_MARKER in key]
    assert not set(again) & set(segments_before)
    assert len(again) == len(clean_puts) - 2
    owner = bed.api.primary_id
    assert await bed.video_hashes(owner, interrupted, "16x9", tmp_path) == await bed.video_hashes(
        owner, clean, "16x9", tmp_path
    )


@pytest.mark.slow
async def test_cancelling_during_capture_ends_cancelled_and_cleans_up(bed: RenderBed) -> None:
    created = await bed.post_golden("kinetic-typography")
    render_id = UUID(created.json()["id"])
    cancelled = False

    async def cancel_on_first_segment(key: str) -> None:
        nonlocal cancelled
        if SEGMENT_MARKER in key and not cancelled:
            cancelled = True
            response = await bed.client.post(f"{BED}/{render_id}/cancel", headers=csrf(bed.client))
            assert response.status_code == 200

    bed.storage.before_put = cancel_on_first_segment

    await bed.run(render_id)

    bed.storage.before_put = None
    body = await bed.state(render_id)
    assert cancelled
    assert body["status"] == "cancelled"
    assert body["cancelRequestedAt"] is not None
    assert body["renditions"] == []
    assert bed.leftover_directories() == []
    again = await bed.client.post(f"{BED}/{render_id}/cancel", headers=csrf(bed.client))
    assert again.status_code == 200
    assert again.json()["status"] == "cancelled"


async def test_a_queued_render_is_cancelled_at_once(bed: RenderBed) -> None:
    render_id = UUID((await bed.post_golden("responsive-scene")).json()["id"])

    response = await bed.client.post(f"{BED}/{render_id}/cancel", headers=csrf(bed.client))

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    await bed.run(render_id)
    assert (await bed.state(render_id))["status"] == "cancelled"
    assert bed.storage.puts.count(f"work/renders/{render_id}/narration.json") == 0


@pytest.mark.slow
async def test_a_too_small_font_fails_validation_with_the_issue_in_the_report(bed: RenderBed) -> None:
    slide = '<div class="slide mo-body" id="slide">slide</div>'
    footnote = '<p id="footnote" style="font-size: 14px">tiny words that nobody can read</p>'
    html = TINY_COMPOSITION.replace(slide, slide + footnote)
    created = await bed.post_upload(html, synth_options(TINY_SCENES))
    assert created.status_code == 202, created.text

    body = await bed.run_and_read(UUID(created.json()["id"]))

    assert body["status"] == "failed"
    assert body["errorCode"] == "validation_failed"
    codes = [(issue["code"], issue.get("aspect")) for issue in body["validationReport"]["issues"]]
    assert ("font_too_small", "16:9") in codes
    assert body["validationReport"]["valid"] is False
    assert body["stage"] == "capturing"
    assert body["renditions"] == []


@pytest.mark.slow
@pytest.mark.parametrize("name", CASE_NAMES)
async def test_a_malicious_composition_fails_safely_without_reaching_the_network(bed: RenderBed, name: str) -> None:
    canary = Canary()
    await canary.start()
    try:
        html = canary.fill((MALICIOUS_ROOT / f"{name}.html").read_text(encoding="utf-8"))
        scenes = [{"sceneId": "main", "text": "Hello world from the hostile test"}]
        created = await bed.post_upload(html, synth_options(scenes))
        assert created.status_code == 202, created.text

        body = await bed.run_and_read(UUID(created.json()["id"]))
    finally:
        await canary.stop()

    assert body["status"] == "failed"
    assert body["errorCode"] in {"network_violation", "invalid_composition"}
    assert canary.hits == []
    assert body["errorMessage"]
    assert canary.authority not in body["errorMessage"]
    assert "Traceback" not in body["errorMessage"]
    assert body["renditions"] == []
    assert bed.leftover_directories() == []


@pytest.mark.slow
async def test_uploaded_narration_audio_drives_the_render(bed: RenderBed, tmp_path: Path) -> None:
    tone = await synthesize_tone(bed.tools, tmp_path / "tone.m4a", 2200)
    wav = build_wav(b"\x00\x00" * 24000, sample_rate=16000, embedded_text="Second scene")
    options = {
        "aspects": ["16:9"],
        "fps": FPS,
        "narration": {
            "mode": "upload",
            "scenes": [
                {"sceneId": "one", "audioPart": "audio-one", "text": "Frames stay identical across runs"},
                {"sceneId": "two", "audioPart": "audio-two"},
            ],
        },
    }
    created = await bed.post_upload(
        TINY_COMPOSITION,
        options,
        {
            "audio-one": ("one.m4a", tone.read_bytes(), "audio/mp4"),
            "audio-two": ("two.wav", wav, "audio/wav"),
        },
    )
    assert created.status_code == 202, created.text
    render_id = UUID(created.json()["id"])
    assert f"work/renders/{render_id}/upload-one.m4a" in bed.storage.puts
    assert f"work/renders/{render_id}/upload-two.wav" in bed.storage.puts

    await bed.completed(render_id)

    narration = json.loads(await bed.read_object(f"work/renders/{render_id}/narration.json"))
    first, second = narration["scenes"]
    assert [word["text"] for word in first["words"]] == ["Frames", "stay", "identical", "across", "runs"]
    assert second["words"]
    assert abs((first["durationMs"] - 300) - 2200) <= 120
    assert abs(second["durationMs"] - 1500) <= 120
    assert narration["totalDurationMs"] == first["durationMs"] + second["durationMs"]


async def test_uploaded_audio_that_is_not_audio_is_rejected_with_a_problem(bed: RenderBed) -> None:
    options = {
        "aspects": ["16:9"],
        "narration": {"mode": "upload", "scenes": [{"sceneId": "one", "audioPart": "audio-one"}]},
    }

    response = await bed.post_upload(
        TINY_COMPOSITION, options, {"audio-one": ("one.wav", b"this is not audio at all", "audio/wav")}
    )

    assert response.status_code == 422
    assert response.json()["code"] == "render_audio_rejected"
    assert response.json()["reason"] == "not_audio"
    assert bed.dispatched == []


@pytest.mark.slow
async def test_the_tts_cache_serves_the_second_render_of_the_same_narration(bed: RenderBed) -> None:
    scenes = json.loads((GOLDEN_ROOT / "responsive-scene" / "narration.json").read_text("utf-8"))["scenes"]
    count = len(scenes)
    first = UUID((await bed.post_golden("responsive-scene")).json()["id"])
    await bed.completed(first)
    usage = await scalar(bed.api, "SELECT count(*) FROM usage_records WHERE stage = 'tts'")
    entries = await scalar(bed.api, "SELECT count(*) FROM tts_cache")
    assert usage == count
    assert entries == count

    second = UUID((await bed.post_golden("responsive-scene")).json()["id"])
    await bed.completed(second)

    assert await scalar(bed.api, "SELECT count(*) FROM usage_records WHERE stage = 'tts'") == usage
    assert await scalar(bed.api, "SELECT count(*) FROM tts_cache") == entries
    assert await scalar(bed.api, "SELECT sum(hit_count) FROM tts_cache") == count


async def test_the_golden_catalog_and_music_picker_list_their_items(bed: RenderBed, tmp_path: Path) -> None:
    catalog = await bed.client.get(f"{BED}/golden")
    assert catalog.status_code == 200
    items = {item["name"]: item for item in catalog.json()["items"]}
    assert set(items) >= {"kinetic-typography", "responsive-scene"}
    kinetic = items["kinetic-typography"]
    assert kinetic["sceneIds"] == ["question", "timing", "close"]
    assert kinetic["scenes"][0]["text"].startswith("Every great video")
    assert kinetic["title"] == "Kinetic typography"

    tone = await synthesize_tone(bed.tools, tmp_path / "bed.m4a", 6000)
    async with bed.api.database.transaction() as session:
        track = await music_service_for(bed.api.resources).upload(
            session,
            bed.api.primary_id,
            MusicUpload(
                content=tone.read_bytes(),
                title="Slow dawn",
                mood="calm",
                license_name="CC BY 4.0",
                license_url="https://creativecommons.org/licenses/by/4.0/",
                attribution_text="Slow dawn",
                activate=True,
            ),
        )
        await music_service_for(bed.api.resources).upload(
            session,
            bed.api.primary_id,
            MusicUpload(
                content=tone.read_bytes(),
                title="Hidden",
                mood="calm",
                license_name="CC BY 4.0",
                license_url="https://creativecommons.org/licenses/by/4.0/",
            ),
        )
    tracks = await bed.client.get(f"{BED}/music-tracks")
    assert tracks.status_code == 200
    assert [item["title"] for item in tracks.json()["items"]] == ["Slow dawn"]
    assert tracks.json()["items"][0]["id"] == str(track.id)
    assert set(tracks.json()["items"][0]) == {"id", "title", "mood", "bpm", "durationMs", "attribution"}


@pytest.mark.parametrize("name", ["%2e%2e", "does-not-exist", "Kinetic-Typography", "a" * 80, "..%2Fx"])
async def test_a_golden_name_outside_the_catalog_is_rejected(bed: RenderBed, name: str) -> None:
    response = await bed.client.post(
        f"{BED}/golden/{name}", json={"voiceId": str(FAKE_VOICE_ID)}, headers=csrf(bed.client)
    )

    assert response.status_code in {404, 422}
    assert bed.dispatched == []


async def test_an_unknown_voice_or_inactive_music_is_rejected_before_anything_is_queued(bed: RenderBed) -> None:
    unknown = await bed.client.post(
        f"{BED}/golden/responsive-scene", json={"voiceId": str(UNKNOWN_VOICE_ID)}, headers=csrf(bed.client)
    )
    inactive = await bed.post_golden("responsive-scene", musicTrackId=str(UUID(int=77)))

    assert unknown.status_code == 404
    assert unknown.json()["code"] == "voice_not_found"
    assert inactive.status_code == 422
    assert inactive.json()["code"] == "music_track_unavailable"
    assert bed.dispatched == []
    assert await scalar(bed.api, "SELECT count(*) FROM renders") == 0


async def test_unknown_options_fields_are_rejected(bed: RenderBed) -> None:
    response = await bed.post_upload(TINY_COMPOSITION, {**synth_options(TINY_SCENES), "bitrate": 5})

    assert response.status_code == 422
    assert response.json()["errors"][0]["field"].startswith("body.options")


async def test_every_route_requires_the_testbed_permission(bed: RenderBed) -> None:
    render_id = UUID((await bed.post_golden("responsive-scene")).json()["id"])
    outsider = bed.api.other
    headers = csrf(outsider)
    body = {"voiceId": str(FAKE_VOICE_ID)}

    responses = [
        await outsider.get(f"{BED}/golden"),
        await outsider.post(f"{BED}/golden/responsive-scene", json=body, headers=headers),
        await outsider.get(f"{BED}/music-tracks"),
        await bed.post_upload(TINY_COMPOSITION, synth_options(TINY_SCENES), client=outsider),
        await outsider.get(f"{BED}/{render_id}"),
        await outsider.get(f"{BED}/{render_id}/events"),
        await outsider.post(f"{BED}/{render_id}/cancel", headers=headers),
    ]

    assert [response.status_code for response in responses] == [403] * 7


async def test_anonymous_callers_are_unauthenticated(bed: RenderBed) -> None:
    anonymous = bed.api.anonymous
    render_id = UUID(int=1)

    responses = [
        await anonymous.get(f"{BED}/golden"),
        await anonymous.get(f"{BED}/music-tracks"),
        await anonymous.get(f"{BED}/{render_id}"),
        await anonymous.get(f"{BED}/{render_id}/events"),
    ]

    assert [response.status_code for response in responses] == [401] * 4


async def test_another_admins_render_is_a_404_on_every_route(bed: RenderBed) -> None:
    await bed.api.grant_permissions(bed.api.other_id, "bedother", "render.testbed")
    render_id = UUID((await bed.post_golden("responsive-scene")).json()["id"])
    other = bed.api.other

    read = await other.get(f"{BED}/{render_id}")
    stream = await other.get(f"{BED}/{render_id}/events")
    cancel = await other.post(f"{BED}/{render_id}/cancel", headers=csrf(other))
    public = await other.get(f"/v1/renders/{render_id}")
    missing = await other.get(f"{BED}/{UUID(int=404)}")

    assert [response.status_code for response in (read, stream, cancel, public, missing)] == [404] * 5
    assert {read.json()["code"], cancel.json()["code"]} == {"render_not_found"}
    assert (await bed.state(render_id))["status"] == "queued"
    assert (await bed.client.get(f"/v1/renders/{render_id}")).status_code == 200


async def test_the_creation_endpoint_is_rate_limited_per_user(bed: RenderBed) -> None:
    bed.api.resources.rate_limiter.enabled = True
    try:
        statuses = [(await bed.post_golden("responsive-scene")).status_code for _ in range(11)]
    finally:
        bed.api.resources.rate_limiter.enabled = False

    assert statuses[:10] == [202] * 10
    assert statuses[10] == 429
