from datetime import timedelta
from uuid import UUID

import pytest
from tests.fakes.media import EPOCH, World, add_render, add_rendition, fake_session
from tests.fakes.storage import InMemoryStorage
from tests.unit.modules.media.support import USER_A, USER_B

from motionile.core.ids import new_id
from motionile.modules.media import (
    Aspect,
    MediaKeyNotSignableError,
    MediaService,
    PresignedDelivery,
    RenderNotFoundError,
    RenderSource,
    RenderStage,
    RenderStatus,
    RenditionStatus,
)
from motionile.modules.media.models import MusicTrack

TTL = timedelta(seconds=900)


def build(world: World) -> MediaService:
    return MediaService(PresignedDelivery(InMemoryStorage(), TTL), world.render_store)


def add_track(world: World, **overrides: object) -> MusicTrack:
    audio = world.add_asset("music/track.m4a", owner=None, kind="audio")
    values: dict[str, object] = {
        "id": new_id(),
        "title": "Slow dawn",
        "audio_asset_id": audio.id,
        "mood": "calm",
        "bpm": 80,
        "duration_ms": 120_000,
        "license_name": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "attribution_text": "Slow dawn by Example Artist",
        "is_active": True,
        "created_by_user_id": None,
        "created_at": EPOCH,
        "updated_at": EPOCH,
        **overrides,
    }
    track = MusicTrack(**values)
    world.tracks[track.id] = track
    return track


async def test_a_render_is_returned_to_its_owner() -> None:
    world = World()
    render = add_render(world, USER_A, status="encoding", stage="encoding", progress=80, completed_at=None)

    view = await build(world).get_render(fake_session(), USER_A, render.id)

    assert view.id == render.id
    assert view.source is RenderSource.TESTBED
    assert view.status is RenderStatus.ENCODING
    assert view.stage is RenderStage.ENCODING
    assert view.progress == 80
    assert view.completed_at is None


async def test_a_failed_render_exposes_its_error_and_report() -> None:
    world = World()
    render = add_render(
        world,
        USER_A,
        status="failed",
        error_code="validation_failed",
        error_message="Text overflows",
        validation_report={"version": 1, "valid": False, "issues": []},
        stage_timings={"capturing": 1200},
    )

    view = await build(world).get_render(fake_session(), USER_A, render.id)

    assert view.error_code == "validation_failed"
    assert view.error_message == "Text overflows"
    assert view.validation_report == {"version": 1, "valid": False, "issues": []}
    assert view.stage_timings == {"capturing": 1200}


async def test_another_users_render_is_not_found() -> None:
    world = World()
    render = add_render(world, USER_A)
    service = build(world)

    with pytest.raises(RenderNotFoundError):
        await service.get_render(fake_session(), USER_B, render.id)
    with pytest.raises(RenderNotFoundError):
        await service.renditions_for(fake_session(), USER_B, render.id)


async def test_an_unknown_render_is_not_found() -> None:
    with pytest.raises(RenderNotFoundError):
        await build(World()).get_render(fake_session(), USER_A, new_id())


async def test_renditions_carry_playable_urls_in_aspect_order() -> None:
    world = World()
    render = add_render(world, USER_A)
    add_rendition(world, render, "1:1", width=1080, height=1080)
    add_rendition(world, render, "9:16", width=1080, height=1920)
    add_rendition(world, render, "16:9")

    items = await build(world).renditions_for(fake_session(), USER_A, render.id)

    assert [item.aspect for item in items] == [Aspect.LANDSCAPE, Aspect.PORTRAIT, Aspect.SQUARE]
    landscape = items[0]
    prefix = f"media/u/{USER_A}/renders/{render.id}"
    assert landscape.url == f"memory://{prefix}/16x9.mp4?expires=900"
    assert landscape.poster_url == f"memory://{prefix}/poster-16x9.webp?expires=900"
    assert landscape.poster_jpeg_url == f"memory://{prefix}/poster-16x9.jpg?expires=900"
    assert (landscape.width, landscape.height, landscape.duration_ms) == (1920, 1080, 5000)
    assert landscape.status is RenditionStatus.READY


async def test_subtitle_links_come_from_the_render() -> None:
    world = World()
    owner = USER_A
    vtt = world.add_asset(f"media/u/{owner}/renders/r/subtitles.vtt", owner=owner, kind="subtitle")
    srt = world.add_asset(f"media/u/{owner}/renders/r/subtitles.srt", owner=owner, kind="subtitle")
    render = add_render(world, owner, subtitles_vtt_asset_id=vtt.id, subtitles_srt_asset_id=srt.id)
    add_rendition(world, render, "16:9")
    add_rendition(world, render, "9:16")

    items = await build(world).renditions_for(fake_session(), owner, render.id)

    assert {item.subtitles_url for item in items} == {f"memory://media/u/{owner}/renders/r/subtitles.vtt?expires=900"}
    assert {item.subtitles_srt_url for item in items} == {
        f"memory://media/u/{owner}/renders/r/subtitles.srt?expires=900"
    }


async def test_renditions_without_subtitles_have_no_subtitle_links() -> None:
    world = World()
    render = add_render(world, USER_A)
    add_rendition(world, render, "16:9")

    [item] = await build(world).renditions_for(fake_session(), USER_A, render.id)

    assert item.subtitles_url is None
    assert item.subtitles_srt_url is None
    assert item.attribution is None


async def test_unfinished_renditions_have_no_playable_url() -> None:
    world = World()
    render = add_render(world, USER_A, status="encoding", progress=70, completed_at=None)
    add_rendition(
        world,
        render,
        "16:9",
        status="rendering",
        asset_id=None,
        poster_webp_asset_id=None,
        poster_jpeg_asset_id=None,
        duration_ms=None,
    )

    [item] = await build(world).renditions_for(fake_session(), USER_A, render.id)

    assert item.status is RenditionStatus.RENDERING
    assert item.url is None
    assert item.poster_url is None
    assert item.poster_jpeg_url is None


async def test_pending_assets_are_never_linked() -> None:
    world = World()
    render = add_render(world, USER_A)
    pending = world.add_asset(f"media/u/{USER_A}/renders/{render.id}/16x9.mp4", owner=USER_A, status="pending")
    add_rendition(world, render, "16:9", asset_id=pending.id)

    [item] = await build(world).renditions_for(fake_session(), USER_A, render.id)

    assert item.url is None


async def test_a_rendition_asset_owned_by_someone_else_is_not_linked() -> None:
    world = World()
    render = add_render(world, USER_A)
    foreign = world.add_asset(f"media/u/{USER_B}/renders/x/16x9.mp4", owner=USER_B)
    add_rendition(world, render, "16:9", asset_id=foreign.id)

    [item] = await build(world).renditions_for(fake_session(), USER_A, render.id)

    assert item.url is None


async def test_the_music_attribution_is_returned_when_a_track_was_used() -> None:
    world = World()
    track = add_track(world)
    render = add_render(world, USER_A, options={"musicTrackId": str(track.id)})
    add_rendition(world, render, "16:9")

    [item] = await build(world).renditions_for(fake_session(), USER_A, render.id)

    assert item.attribution is not None
    assert item.attribution.track_id == track.id
    assert item.attribution.title == "Slow dawn"
    assert item.attribution.license_name == "CC BY 4.0"
    assert item.attribution.license_url == "https://creativecommons.org/licenses/by/4.0/"
    assert item.attribution.attribution_text == "Slow dawn by Example Artist"


async def test_the_attribution_survives_deactivation() -> None:
    world = World()
    track = add_track(world, is_active=False)
    render = add_render(world, USER_A, options={"musicTrackId": str(track.id)})
    add_rendition(world, render, "16:9")

    [item] = await build(world).renditions_for(fake_session(), USER_A, render.id)

    assert item.attribution is not None
    assert item.attribution.track_id == track.id


@pytest.mark.parametrize("option", [None, "not-a-uuid", 7, ""])
async def test_a_missing_or_malformed_track_option_means_no_attribution(option: object) -> None:
    world = World()
    render = add_render(world, USER_A, options={"musicTrackId": option})
    add_rendition(world, render, "16:9")

    [item] = await build(world).renditions_for(fake_session(), USER_A, render.id)

    assert item.attribution is None


async def test_an_unknown_track_id_means_no_attribution() -> None:
    world = World()
    render = add_render(world, USER_A, options={"musicTrackId": str(UUID(int=7))})
    add_rendition(world, render, "16:9")

    [item] = await build(world).renditions_for(fake_session(), USER_A, render.id)

    assert item.attribution is None


async def test_a_render_without_renditions_lists_nothing() -> None:
    world = World()
    render = add_render(world, USER_A, status="queued", progress=0, completed_at=None)

    assert await build(world).renditions_for(fake_session(), USER_A, render.id) == []


async def test_signed_urls_cover_only_media_keys() -> None:
    service = build(World())
    key = f"media/u/{USER_A}/renders/r/16x9.mp4"

    assert await service.signed_url(key, TTL) == f"memory://{key}?expires=900"
    assert await service.signed_url(key, timedelta(seconds=60), owner_user_id=USER_A) == f"memory://{key}?expires=60"
    for forbidden in ("work/renders/r/composition.html", "voice/u/a/v/sample.wav", "tts/ab/a.mp3", "music/a.m4a"):
        with pytest.raises(MediaKeyNotSignableError):
            await service.signed_url(forbidden, TTL)


async def test_signed_urls_can_be_pinned_to_the_owner() -> None:
    service = build(World())

    with pytest.raises(MediaKeyNotSignableError):
        await service.signed_url(f"media/u/{USER_B}/renders/r/16x9.mp4", TTL, owner_user_id=USER_A)


def test_the_media_session_comes_from_the_delivery() -> None:
    service = build(World())

    grant = service.media_session(USER_A)

    assert grant.mode.value == "presigned"
    assert grant.cookies == ()


async def test_a_rendition_asset_stored_under_another_users_prefix_is_never_linked() -> None:
    world = World()
    render = add_render(world, USER_A)
    foreign = world.add_asset(f"media/u/{USER_B}/renders/r/16x9.mp4", owner=USER_A, kind="video")
    add_rendition(world, render, "16:9", asset_id=foreign.id)

    with pytest.raises(MediaKeyNotSignableError):
        await build(world).renditions_for(fake_session(), USER_A, render.id)
