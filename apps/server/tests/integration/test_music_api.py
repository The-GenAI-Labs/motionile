import importlib
import os
import shutil
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from tests.integration.media_support import MediaApi
from tests.integration.test_auth import csrf

from motionile.engine.ffmpeg import FfmpegTools, probe_bytes, run_ffmpeg
from motionile.modules.media import FormLimits

UPLOAD_MODULE = "motionile.modules.media.music_upload"
BASE = "/v1/admin/music"
SINE = "sine=frequency=440:duration=6"
LICENSE = "https://creativecommons.org/licenses/by/4.0/"


@pytest.fixture(scope="session")
def tools() -> FfmpegTools:
    ffmpeg = os.environ.get("RENDER_FFMPEG_PATH") or shutil.which("ffmpeg")
    ffprobe = os.environ.get("RENDER_FFPROBE_PATH") or shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg and ffprobe are unavailable; set RENDER_FFMPEG_PATH and RENDER_FFPROBE_PATH")
    return FfmpegTools(ffmpeg=ffmpeg, ffprobe=ffprobe)


async def make_media(tools: FfmpegTools, directory: Path, name: str, source: str, *arguments: str) -> bytes:
    path = directory / name
    await run_ffmpeg(tools, ["-f", "lavfi", "-i", source, *arguments, "-y", str(path)], timeout_seconds=120)
    return path.read_bytes()


@pytest.fixture
async def tone(tools: FfmpegTools, tmp_path: Path) -> bytes:
    return await make_media(tools, tmp_path, "tone.mp3", SINE, "-c:a", "libmp3lame")


@pytest.fixture
async def admin(media_api: MediaApi) -> AsyncClient:
    await media_api.grant_permissions(media_api.other_id, "music", "music.manage")
    return media_api.other


def fields(**overrides: Any) -> dict[str, str]:
    values: dict[str, Any] = {
        "title": "Slow dawn",
        "mood": "calm",
        "bpm": "80",
        "licenseName": "CC BY 4.0",
        "licenseUrl": LICENSE,
        "attributionText": "Slow dawn by Example Artist",
        **overrides,
    }
    return {name: str(value) for name, value in values.items() if value is not None}


async def upload(
    client: AsyncClient, content: bytes, *, filename: str = "tone.mp3", extra: dict[str, Any] | None = None
) -> Response:
    return await client.post(
        BASE,
        files={"file": (filename, content, "audio/mpeg")},
        data=fields(**(extra or {})),
        headers=csrf(client),
    )


async def stored_tracks(media_api: MediaApi) -> int:
    async with media_api.database.transaction() as session:
        return (await session.execute(text("SELECT count(*) FROM music_tracks"))).scalar_one()


async def audit_actions(media_api: MediaApi) -> list[str]:
    async with media_api.database.transaction() as session:
        rows = await session.execute(
            text("SELECT action FROM audit_log WHERE action LIKE 'music.%' ORDER BY created_at, id")
        )
        return [row[0] for row in rows]


async def test_every_route_requires_authentication(media_api: MediaApi) -> None:
    track = UUID(int=1)
    calls = [
        ("GET", BASE),
        ("GET", f"{BASE}/{track}"),
        ("POST", f"{BASE}/{track}/activate"),
        ("POST", f"{BASE}/{track}/deactivate"),
    ]
    for method, path in calls:
        response = await media_api.anonymous.request(method, path)
        assert response.status_code == 401, (method, path)


async def test_users_without_the_permission_are_forbidden(media_api: MediaApi, tone: bytes) -> None:
    await media_api.grant_permissions(media_api.other_id, "voices", "voices.manage")
    track = UUID(int=1)
    for client in (media_api.primary, media_api.other):
        assert (await client.get(BASE)).status_code == 403
        assert (await client.get(f"{BASE}/{track}")).status_code == 403
        assert (await upload(client, tone)).status_code == 403
        patch = await client.patch(f"{BASE}/{track}", json={"title": "x"}, headers=csrf(client))
        assert patch.status_code == 403
        assert (await client.post(f"{BASE}/{track}/activate", headers=csrf(client))).status_code == 403
        assert (await client.post(f"{BASE}/{track}/deactivate", headers=csrf(client))).status_code == 403
    assert await stored_tracks(media_api) == 0


async def test_uploading_transcodes_stores_and_audits_a_track(
    media_api: MediaApi, admin: AsyncClient, tone: bytes, tools: FfmpegTools
) -> None:
    response = await upload(admin, tone)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["isActive"] is False
    assert (body["title"], body["mood"], body["bpm"]) == ("Slow dawn", "calm", 80)
    assert body["licenseName"] == "CC BY 4.0"
    assert body["licenseUrl"] == LICENSE
    assert body["attributionText"] == "Slow dawn by Example Artist"
    assert body["createdByUserId"] == str(media_api.other_id)
    assert 5_500 <= body["durationMs"] <= 6_600
    key = f"music/{body['id']}.m4a"
    assert body["previewUrl"].startswith("http")
    stored = b"".join([chunk async for chunk in media_api.storage.get(key)])
    probe = await probe_bytes(tools, stored)
    [stream] = probe.audio_streams
    assert (stream.codec_name, stream.sample_rate, stream.channels) == ("aac", 48_000, 2)
    info = await media_api.storage.head(key)
    assert info is not None
    assert info.content_type == "audio/mp4"
    async with media_api.database.transaction() as session:
        row = (
            await session.execute(
                text("SELECT owner_user_id, kind, status, storage_key FROM assets WHERE id = :id"),
                {"id": UUID(body["audioAssetId"])},
            )
        ).one()
    assert tuple(row) == (None, "audio", "ready", key)
    assert await audit_actions(media_api) == ["music.created"]


async def test_a_track_can_be_activated_on_upload(admin: AsyncClient, tone: bytes) -> None:
    response = await upload(admin, tone, extra={"activate": "true", "bpm": None, "attributionText": None})

    assert response.status_code == 201
    assert response.json()["isActive"] is True
    assert response.json()["bpm"] is None
    assert response.json()["attributionText"] is None


@pytest.mark.parametrize(
    "extra",
    [
        {"licenseUrl": "http://example.com/license"},
        {"licenseUrl": "https://example.com/has space"},
        {"licenseName": None},
        {"licenseUrl": None},
        {"title": "   "},
        {"mood": "NOT VALID"},
        {"bpm": "10"},
        {"unexpected": "field"},
    ],
)
async def test_invalid_metadata_is_rejected_before_any_work(
    media_api: MediaApi, admin: AsyncClient, tone: bytes, extra: dict[str, Any]
) -> None:
    response = await upload(admin, tone, extra=extra)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"
    assert await stored_tracks(media_api) == 0


async def test_a_missing_file_is_rejected(admin: AsyncClient) -> None:
    response = await admin.post(BASE, data=fields(), headers=csrf(admin))

    assert response.status_code == 422


async def test_text_renamed_to_mp3_is_rejected(media_api: MediaApi, admin: AsyncClient) -> None:
    response = await upload(admin, b"definitely not audio\n" * 500)

    assert response.status_code == 422
    assert response.json()["code"] == "music_not_audio", response.text
    assert await stored_tracks(media_api) == 0


async def test_a_polyglot_with_a_foreign_prefix_is_rejected(
    media_api: MediaApi, admin: AsyncClient, tone: bytes
) -> None:
    for prefix in (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 20, b"PK\x03\x04\x14\x00\x00\x00" + b"\x00" * 40):
        response = await upload(admin, prefix + tone)

        assert response.status_code == 422
        assert response.json()["code"] == "music_not_audio"
    assert await stored_tracks(media_api) == 0


async def test_a_file_with_a_video_stream_is_rejected(
    media_api: MediaApi, admin: AsyncClient, tools: FfmpegTools, tmp_path: Path
) -> None:
    video = tmp_path / "clip.mp4"
    await run_ffmpeg(
        tools,
        [
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:d=6",
            "-f",
            "lavfi",
            "-i",
            SINE,
            "-t",
            "6",
            "-c:v",
            "mpeg4",
            "-c:a",
            "aac",
            "-y",
            str(video),
        ],
        timeout_seconds=120,
    )

    response = await upload(admin, video.read_bytes(), filename="clip.mp3")

    assert response.status_code == 422
    assert response.json()["code"] == "music_video_stream"
    assert await stored_tracks(media_api) == 0


async def test_audio_that_is_too_short_is_rejected(
    media_api: MediaApi, admin: AsyncClient, tools: FfmpegTools, tmp_path: Path
) -> None:
    short = await make_media(tools, tmp_path, "short.mp3", "sine=frequency=440:duration=1", "-c:a", "libmp3lame")

    response = await upload(admin, short)

    assert response.status_code == 422
    assert response.json()["code"] == "music_too_short"
    assert await stored_tracks(media_api) == 0


async def test_an_oversized_file_is_rejected_with_413(
    media_api: MediaApi, admin: AsyncClient, tone: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importlib.import_module(UPLOAD_MODULE), "MUSIC_MAX_BYTES", len(tone) - 1)

    response = await upload(admin, tone)

    assert response.status_code == 413
    assert response.json()["code"] == "music_too_large"
    assert await stored_tracks(media_api) == 0


async def test_a_body_over_the_form_limit_is_refused_before_it_is_processed(
    media_api: MediaApi, admin: AsyncClient, tone: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importlib.import_module(UPLOAD_MODULE), "MUSIC_FORM_LIMITS", FormLimits(len(tone) // 2, 2, 8))

    response = await upload(admin, tone)

    assert response.status_code == 413
    assert response.json()["code"] == "music_too_large"
    assert await stored_tracks(media_api) == 0


async def test_garbage_after_a_valid_signature_is_rejected(media_api: MediaApi, admin: AsyncClient) -> None:
    response = await upload(admin, b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\xde\xad\xbe\xef" * 200)

    assert response.status_code == 422
    assert response.json()["code"] in {"music_unreadable", "music_not_audio"}
    assert await stored_tracks(media_api) == 0


async def test_listing_filters_and_paginates(admin: AsyncClient, tone: bytes) -> None:
    calm = (await upload(admin, tone, extra={"title": "Calm one", "activate": "true"})).json()
    await upload(admin, tone, extra={"title": "Calm two"})
    await upload(admin, tone, extra={"title": "Bright", "mood": "upbeat"})

    everything = (await admin.get(BASE, params={"limit": 2})).json()
    rest = (await admin.get(BASE, params={"limit": 2, "cursor": everything["nextCursor"]})).json()
    calm_only = (await admin.get(BASE, params={"mood": "calm"})).json()
    active = (await admin.get(BASE, params={"active": "true"})).json()
    inactive = (await admin.get(BASE, params={"active": "false"})).json()

    assert [item["title"] for item in everything["items"]] == ["Bright", "Calm two"]
    assert [item["title"] for item in rest["items"]] == ["Calm one"]
    assert rest["nextCursor"] is None
    assert sorted(item["title"] for item in calm_only["items"]) == ["Calm one", "Calm two"]
    assert [item["id"] for item in active["items"]] == [calm["id"]]
    assert len(inactive["items"]) == 2


async def test_listing_rejects_a_forged_cursor_and_bad_filters(admin: AsyncClient) -> None:
    assert (await admin.get(BASE, params={"cursor": "forged.value"})).status_code == 422
    assert (await admin.get(BASE, params={"mood": "NOT VALID"})).status_code == 422
    assert (await admin.get(BASE, params={"limit": 0})).status_code == 422


async def test_a_track_is_fetched_by_id(admin: AsyncClient, tone: bytes) -> None:
    created = (await upload(admin, tone)).json()

    response = await admin.get(f"{BASE}/{created['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]
    missing = await admin.get(f"{BASE}/{UUID(int=5)}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "music_track_not_found"


async def test_metadata_and_license_can_be_edited_and_cleared(
    media_api: MediaApi, admin: AsyncClient, tone: bytes
) -> None:
    created = (await upload(admin, tone)).json()

    response = await admin.patch(
        f"{BASE}/{created['id']}",
        json={"title": "Fast dusk", "bpm": None, "attributionText": None, "licenseName": "CC0"},
        headers=csrf(admin),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["title"], body["bpm"], body["attributionText"], body["licenseName"]) == (
        "Fast dusk",
        None,
        None,
        "CC0",
    )
    assert body["mood"] == "calm"
    assert body["licenseUrl"] == LICENSE
    assert body["updatedAt"] >= created["updatedAt"]
    assert await audit_actions(media_api) == ["music.created", "music.updated"]


@pytest.mark.parametrize(
    "body",
    [{}, {"title": None}, {"licenseUrl": "http://insecure.example"}, {"isActive": True}, {"mood": "BAD"}],
)
async def test_invalid_edits_are_rejected(admin: AsyncClient, tone: bytes, body: dict[str, Any]) -> None:
    created = (await upload(admin, tone)).json()

    response = await admin.patch(f"{BASE}/{created['id']}", json=body, headers=csrf(admin))

    assert response.status_code == 422


async def test_editing_an_unknown_track_is_not_found(admin: AsyncClient) -> None:
    response = await admin.patch(f"{BASE}/{UUID(int=5)}", json={"title": "x"}, headers=csrf(admin))

    assert response.status_code == 404


async def test_tracks_can_be_activated_and_deactivated(media_api: MediaApi, admin: AsyncClient, tone: bytes) -> None:
    created = (await upload(admin, tone)).json()

    activated = await admin.post(f"{BASE}/{created['id']}/activate", headers=csrf(admin))
    again = await admin.post(f"{BASE}/{created['id']}/activate", headers=csrf(admin))
    deactivated = await admin.post(f"{BASE}/{created['id']}/deactivate", headers=csrf(admin))

    assert activated.json()["isActive"] is True
    assert again.json()["isActive"] is True
    assert deactivated.json()["isActive"] is False
    assert await audit_actions(media_api) == ["music.created", "music.activated", "music.deactivated"]
    missing = await admin.post(f"{BASE}/{UUID(int=5)}/activate", headers=csrf(admin))
    assert missing.status_code == 404


async def test_writes_require_a_csrf_token(admin: AsyncClient, tone: bytes) -> None:
    created = (await upload(admin, tone)).json()

    response = await admin.post(f"{BASE}/{created['id']}/activate")

    assert response.status_code in {401, 403}


async def test_music_writes_are_rate_limited_per_user(media_api: MediaApi, admin: AsyncClient, tone: bytes) -> None:
    created = (await upload(admin, tone)).json()
    media_api.resources.rate_limiter.enabled = True
    statuses = [
        (await admin.post(f"{BASE}/{created['id']}/activate", headers=csrf(admin))).status_code for _ in range(21)
    ]

    assert statuses[:19].count(200) == 19
    assert statuses[-1] == 429
