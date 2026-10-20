from datetime import timedelta
from uuid import UUID

import httpx
from sqlalchemy import text
from tests.integration.media_support import VIDEO_BYTES, MediaApi
from tests.unit.modules.media.support import KEY_FILE

from motionile.core.config import MediaDeliveryMode
from motionile.core.ids import new_id
from motionile.modules.media import CloudFrontDelivery, CloudFrontSigner, MediaService, rendition_key
from motionile.modules.media.delivery.factory import load_signing_key
from motionile.modules.media.dependencies import get_media_service

SESSION = "/v1/media/session"


async def test_the_media_session_requires_authentication(media_api: MediaApi) -> None:
    response = await media_api.anonymous.get(SESSION)

    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


async def test_the_presigned_session_reports_the_mode_and_sets_no_cookies(media_api: MediaApi) -> None:
    response = await media_api.primary.get(SESSION)

    assert response.status_code == 200
    assert response.json() == {"mode": "presigned", "expiresAt": None}
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers


async def test_the_cloudfront_session_sets_signed_cookies_scoped_to_the_caller(media_api: MediaApi) -> None:
    signer = CloudFrontSigner(load_signing_key(KEY_FILE.read_bytes()), "KTESTPAIR0001")
    delivery = CloudFrontDelivery(
        signer,
        "cdn.motionile.test",
        media_api.resources.clock,
        cookie_domain=".motionile.test",
        cookie_ttl=timedelta(seconds=600),
    )
    media_api.app.dependency_overrides[get_media_service] = lambda: MediaService(delivery)

    response = await media_api.primary.get(SESSION)

    assert response.status_code == 200
    assert response.json()["mode"] == MediaDeliveryMode.CLOUDFRONT.value
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 3
    assert {cookie.split("=", 1)[0] for cookie in cookies} == {
        "CloudFront-Policy",
        "CloudFront-Signature",
        "CloudFront-Key-Pair-Id",
    }
    for cookie in cookies:
        lowered = cookie.lower()
        assert "secure" in lowered
        assert "httponly" in lowered
        assert "samesite=lax" in lowered
        assert "path=/" in lowered
        assert "domain=.motionile.test" in lowered
        assert "max-age=600" in lowered
    assert response.headers["cache-control"] == "no-store"
    media_api.app.dependency_overrides.pop(get_media_service)


async def test_a_render_is_returned_to_its_owner(media_api: MediaApi) -> None:
    render_id = await media_api.seed_render(media_api.primary_id)

    response = await media_api.primary.get(f"/v1/renders/{render_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(render_id)
    assert body["status"] == "completed"
    assert body["progress"] == 100
    assert body["source"] == "testbed"
    assert body["durationMs"] == 5000


async def test_another_users_render_and_renditions_are_not_found(media_api: MediaApi) -> None:
    render_id = await media_api.seed_render(media_api.primary_id)

    render = await media_api.other.get(f"/v1/renders/{render_id}")
    renditions = await media_api.other.get(f"/v1/renders/{render_id}/renditions")

    for response in (render, renditions):
        assert response.status_code == 404
        assert response.json()["code"] == "render_not_found"
        assert response.headers["content-type"].startswith("application/problem+json")


async def test_an_unknown_render_looks_exactly_like_a_foreign_one(media_api: MediaApi) -> None:
    foreign = await media_api.seed_render(media_api.primary_id)

    unknown = await media_api.other.get(f"/v1/renders/{new_id()}")
    foreign_response = await media_api.other.get(f"/v1/renders/{foreign}")

    assert unknown.status_code == foreign_response.status_code == 404
    assert unknown.json()["code"] == foreign_response.json()["code"]


async def test_renders_require_authentication(media_api: MediaApi) -> None:
    render_id = await media_api.seed_render(media_api.primary_id)

    for path in (f"/v1/renders/{render_id}", f"/v1/renders/{render_id}/renditions"):
        response = await media_api.anonymous.get(path)
        assert response.status_code == 401


async def test_a_malformed_render_id_is_a_validation_problem(media_api: MediaApi) -> None:
    response = await media_api.primary.get("/v1/renders/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_failed"


async def test_renditions_list_presigned_urls_for_every_asset(media_api: MediaApi) -> None:
    render_id = await media_api.seed_render(media_api.primary_id, aspects=("9:16", "16:9"))

    response = await media_api.primary.get(f"/v1/renders/{render_id}/renditions")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["aspect"] for item in items] == ["16:9", "9:16"]
    first = items[0]
    assert first["status"] == "ready"
    assert (first["width"], first["height"], first["durationMs"]) == (1920, 1080, 5000)
    for field in ("url", "posterUrl", "posterJpegUrl", "subtitlesUrl", "subtitlesSrtUrl"):
        assert first[field].startswith("http")
        assert "X-Amz-Signature" in first[field]
    assert first["attribution"] is None
    assert f"/media/u/{media_api.primary_id}/renders/{render_id}/16x9.mp4" in first["url"]


async def test_a_presigned_rendition_url_streams_and_supports_range_requests(media_api: MediaApi) -> None:
    render_id = await media_api.seed_render(media_api.primary_id)
    [item] = (await media_api.primary.get(f"/v1/renders/{render_id}/renditions")).json()["items"]

    async with httpx.AsyncClient() as http:
        full = await http.get(item["url"])
        ranged = await http.get(item["url"], headers={"Range": "bytes=100-199"})
        tail = await http.get(item["url"], headers={"Range": "bytes=-50"})

    assert full.status_code == 200
    assert full.content == VIDEO_BYTES
    assert full.headers["content-type"] == "video/mp4"
    assert ranged.status_code == 206
    assert ranged.headers["content-range"] == f"bytes 100-199/{len(VIDEO_BYTES)}"
    assert ranged.content == VIDEO_BYTES[100:200]
    assert tail.status_code == 206
    assert tail.content == VIDEO_BYTES[-50:]


async def test_the_music_attribution_is_part_of_the_rendition(media_api: MediaApi) -> None:
    track_id = await media_api_track(media_api)
    render_id = await media_api.seed_render(media_api.primary_id, options={"musicTrackId": str(track_id)})

    [item] = (await media_api.primary.get(f"/v1/renders/{render_id}/renditions")).json()["items"]

    assert item["attribution"] == {
        "trackId": str(track_id),
        "title": "Attributed",
        "licenseName": "CC BY 4.0",
        "licenseUrl": "https://creativecommons.org/licenses/by/4.0/",
        "attributionText": "Attributed by Example Artist",
    }


async def media_api_track(media_api: MediaApi) -> UUID:
    track_id = new_id()
    audio_id = new_id()
    async with media_api.database.transaction() as session:
        await session.execute(
            text(
                "INSERT INTO assets (id, owner_user_id, kind, storage_key, content_type, size_bytes, sha256, status, "
                "metadata) VALUES (:id, NULL, 'audio', :key, 'audio/mp4', 1, :sha, 'ready', '{}'::jsonb)"
            ),
            {"id": audio_id, "key": f"music/{track_id}.m4a", "sha": bytes(32)},
        )
        await session.execute(
            text(
                "INSERT INTO music_tracks (id, title, audio_asset_id, mood, duration_ms, license_name, license_url, "
                "attribution_text, is_active) VALUES (:id, 'Attributed', :audio, 'calm', 60000, 'CC BY 4.0', "
                "'https://creativecommons.org/licenses/by/4.0/', 'Attributed by Example Artist', false)"
            ),
            {"id": track_id, "audio": audio_id},
        )
    return track_id


async def test_the_rendition_keys_follow_the_owner_prefix(media_api: MediaApi) -> None:
    render_id = await media_api.seed_render(media_api.primary_id)

    assert await media_api.storage.exists(rendition_key(media_api.primary_id, render_id, "16:9"))
    assert not await media_api.storage.exists(rendition_key(media_api.other_id, render_id, "16:9"))
