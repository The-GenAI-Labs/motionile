from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, get_args
from uuid import UUID

import pytest
from tests.fakes.media import World, fake_session
from tests.fakes.storage import InMemoryStorage
from tests.unit.modules.media.support import USER_A

from motionile.core.errors import AppError
from motionile.core.ids import new_id
from motionile.engine.audio.audio_validation import AudioRejectedError, RejectionCode
from motionile.modules.audit import AuditContext, AuditEvent
from motionile.modules.media import (
    AssetService,
    MusicFilter,
    MusicService,
    MusicTrackNotFoundError,
    MusicTrackUnavailableError,
    MusicUpload,
)
from motionile.modules.media import music as music_module
from motionile.modules.media.exceptions import MusicUpdateEmptyError
from motionile.modules.media.music_audio import REJECTIONS, ProcessedMusic, rejection_for

AUDIO = b"transcoded music"
PREVIEW_TTL = timedelta(seconds=600)


@dataclass
class ScriptedProcessor:
    result: ProcessedMusic | AudioRejectedError = field(default_factory=lambda: ProcessedMusic(AUDIO, 95_000))
    received: list[bytes] = field(default_factory=list[bytes])

    async def process(self, data: bytes) -> ProcessedMusic:
        self.received.append(data)
        if isinstance(self.result, AudioRejectedError):
            raise rejection_for(self.result)
        return self.result


@dataclass
class Harness:
    world: World
    storage: InMemoryStorage
    processor: ScriptedProcessor
    service: MusicService
    audit: list[tuple[AuditEvent, AuditContext | None]] = field(
        default_factory=list[tuple[AuditEvent, AuditContext | None]]
    )


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    world = World()
    storage = InMemoryStorage()
    processor = ScriptedProcessor()
    service = MusicService(
        AssetService(storage, world.asset_store),
        storage,
        processor,
        preview_ttl=PREVIEW_TTL,
        store_factory=world.music_store,
    )
    recorded: list[tuple[AuditEvent, AuditContext | None]] = []

    async def record(session: object, event: AuditEvent, context: AuditContext | None = None) -> UUID:
        del session
        recorded.append((event, context))
        return new_id()

    monkeypatch.setattr(music_module, "record_audit", record)
    return Harness(world, storage, processor, service, recorded)


def upload(**overrides: Any) -> MusicUpload:
    values: dict[str, Any] = {
        "content": b"source audio",
        "title": "Slow dawn",
        "mood": "calm",
        "license_name": "CC BY 4.0",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "bpm": 80,
        "attribution_text": "Slow dawn by Example Artist",
        **overrides,
    }
    return MusicUpload(**values)


async def test_an_uploaded_track_starts_inactive_with_its_license_recorded(harness: Harness) -> None:
    view = await harness.service.upload(fake_session(), USER_A, upload())

    assert not view.is_active
    assert (view.title, view.mood, view.bpm) == ("Slow dawn", "calm", 80)
    assert view.duration_ms == 95_000
    assert view.license_name == "CC BY 4.0"
    assert view.license_url == "https://creativecommons.org/licenses/by/4.0/"
    assert view.attribution_text == "Slow dawn by Example Artist"
    assert view.created_by_user_id == USER_A
    assert view.preview_url == f"memory://music/{view.id}.m4a?expires=600"


async def test_the_transcoded_audio_is_stored_as_a_system_asset_under_music(harness: Harness) -> None:
    view = await harness.service.upload(fake_session(), USER_A, upload())

    [asset] = harness.world.assets.values()
    assert asset.id == view.audio_asset_id
    assert asset.storage_key == f"music/{view.id}.m4a"
    assert asset.owner_user_id is None
    assert (asset.kind, asset.content_type, asset.duration_ms) == ("audio", "audio/mp4", 95_000)
    assert harness.storage.objects[asset.storage_key].data == AUDIO
    assert harness.processor.received == [b"source audio"]


async def test_a_track_can_be_activated_on_upload(harness: Harness) -> None:
    view = await harness.service.upload(fake_session(), USER_A, upload(activate=True))

    assert view.is_active


async def test_an_upload_is_audited_without_the_audio(harness: Harness) -> None:
    context = AuditContext(request_id="req-1")

    view = await harness.service.upload(fake_session(), USER_A, upload(), context)

    [(event, recorded_context)] = harness.audit
    assert event.action == "music.created"
    assert event.actor_user_id == USER_A
    assert event.target_type == "music_track"
    assert event.target_id == str(view.id)
    assert event.metadata["title"] == "Slow dawn"
    assert event.metadata["licenseName"] == "CC BY 4.0"
    assert recorded_context is context
    assert "source audio" not in repr(event.metadata)


async def test_a_rejected_file_leaves_no_asset_and_no_track(harness: Harness) -> None:
    harness.processor.result = rejection_for_code("not_audio")

    with pytest.raises(AppError) as raised:
        await harness.service.upload(fake_session(), USER_A, upload())

    assert raised.value.code == "music_not_audio"
    assert harness.world.assets == {}
    assert harness.world.tracks == {}
    assert harness.storage.objects == {}
    assert harness.audit == []


def rejection_for_code(code: RejectionCode) -> AudioRejectedError:
    return AudioRejectedError(code, f"rejected as {code}")


@pytest.mark.parametrize(
    ("code", "status", "problem"),
    [
        ("not_audio", 422, "music_not_audio"),
        ("too_large", 413, "music_too_large"),
        ("too_short", 422, "music_too_short"),
        ("too_long", 422, "music_too_long"),
        ("video_stream_present", 422, "music_video_stream"),
        ("unsupported_format", 422, "music_unsupported_format"),
        ("probe_failed", 422, "music_unreadable"),
    ],
)
def test_engine_rejections_map_to_stable_problem_codes(code: RejectionCode, status: int, problem: str) -> None:
    error = rejection_for(rejection_for_code(code))

    assert error.status_code == status
    assert error.code == problem


def test_every_engine_rejection_code_has_a_problem_mapping() -> None:
    assert set(REJECTIONS) == set(get_args(RejectionCode.__value__))


async def test_a_track_is_returned_by_id(harness: Harness) -> None:
    created = await harness.service.upload(fake_session(), USER_A, upload())

    fetched = await harness.service.get(fake_session(), created.id)

    assert fetched.id == created.id


async def test_an_unknown_track_is_not_found(harness: Harness) -> None:
    with pytest.raises(MusicTrackNotFoundError):
        await harness.service.get(fake_session(), new_id())


async def test_activating_and_deactivating_are_audited_and_idempotent(harness: Harness) -> None:
    created = await harness.service.upload(fake_session(), USER_A, upload())
    harness.audit.clear()

    activated = await harness.service.activate(fake_session(), USER_A, created.id)
    again = await harness.service.activate(fake_session(), USER_A, created.id)
    deactivated = await harness.service.deactivate(fake_session(), USER_A, created.id)
    unchanged = await harness.service.deactivate(fake_session(), USER_A, created.id)

    assert activated.is_active
    assert again.is_active
    assert not deactivated.is_active
    assert not unchanged.is_active
    assert [event.action for event, _ in harness.audit] == ["music.activated", "music.deactivated"]


async def test_toggling_an_unknown_track_is_not_found(harness: Harness) -> None:
    with pytest.raises(MusicTrackNotFoundError):
        await harness.service.activate(fake_session(), USER_A, new_id())
    with pytest.raises(MusicTrackNotFoundError):
        await harness.service.deactivate(fake_session(), USER_A, new_id())


async def test_metadata_updates_change_only_the_given_fields_and_are_audited(harness: Harness) -> None:
    created = await harness.service.upload(fake_session(), USER_A, upload())
    harness.audit.clear()

    updated = await harness.service.update(
        fake_session(), USER_A, created.id, {"title": "Fast dusk", "bpm": None, "attribution_text": "New credit"}
    )

    assert updated.title == "Fast dusk"
    assert updated.bpm is None
    assert updated.attribution_text == "New credit"
    assert updated.mood == "calm"
    assert updated.license_name == "CC BY 4.0"
    [(event, _)] = harness.audit
    assert event.action == "music.updated"
    assert event.metadata == {"fields": ["attribution_text", "bpm", "title"]}


async def test_updates_ignore_fields_that_are_not_editable(harness: Harness) -> None:
    created = await harness.service.upload(fake_session(), USER_A, upload())

    with pytest.raises(MusicUpdateEmptyError):
        await harness.service.update(fake_session(), USER_A, created.id, {"is_active": True, "audio_asset_id": 1})

    assert not (await harness.service.get(fake_session(), created.id)).is_active


async def test_an_empty_update_is_refused(harness: Harness) -> None:
    created = await harness.service.upload(fake_session(), USER_A, upload())

    with pytest.raises(MusicUpdateEmptyError):
        await harness.service.update(fake_session(), USER_A, created.id, {})


async def test_updating_an_unknown_track_is_not_found(harness: Harness) -> None:
    with pytest.raises(MusicTrackNotFoundError):
        await harness.service.update(fake_session(), USER_A, new_id(), {"title": "x"})


async def test_listing_filters_by_mood_and_state(harness: Harness) -> None:
    calm = await harness.service.upload(fake_session(), USER_A, upload(mood="calm", activate=True))
    await harness.service.upload(fake_session(), USER_A, upload(mood="upbeat", title="Bright"))

    everything = await harness.service.list_tracks(fake_session(), MusicFilter(), None, 10)
    only_calm = await harness.service.list_tracks(fake_session(), MusicFilter(mood="calm"), None, 10)
    only_active = await harness.service.list_tracks(fake_session(), MusicFilter(active=True), None, 10)
    only_inactive = await harness.service.list_tracks(fake_session(), MusicFilter(active=False), None, 10)

    assert len(everything.items) == 2
    assert [item.id for item in only_calm.items] == [calm.id]
    assert [item.id for item in only_active.items] == [calm.id]
    assert [item.title for item in only_inactive.items] == ["Bright"]
    assert everything.next_cursor is None


async def test_listing_reports_a_cursor_when_more_rows_follow(harness: Harness) -> None:
    for index in range(3):
        await harness.service.upload(fake_session(), USER_A, upload(title=f"Track {index}"))

    page = await harness.service.list_tracks(fake_session(), MusicFilter(), None, 2)

    assert len(page.items) == 2
    assert page.next_cursor is not None
    assert page.next_cursor.id == page.items[-1].id


async def test_only_active_tracks_can_be_required_for_a_render(harness: Harness) -> None:
    inactive = await harness.service.upload(fake_session(), USER_A, upload())
    active = await harness.service.upload(fake_session(), USER_A, upload(activate=True, title="Live"))

    assert (await harness.service.require_active(fake_session(), active.id)).id == active.id
    with pytest.raises(MusicTrackUnavailableError) as inactive_error:
        await harness.service.require_active(fake_session(), inactive.id)
    with pytest.raises(MusicTrackUnavailableError):
        await harness.service.require_active(fake_session(), new_id())
    assert inactive_error.value.code == "music_track_unavailable"
