from uuid import UUID

import pytest
from tests.unit.modules.voices.support import ADMIN, CONTEXT, OTHER, USER, Harness, build_harness, submitted

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.engine.audio.models import ProviderVoice
from motionile.engine.audio.providers.base import ProviderNotFoundError, ProviderRejectedError, ProviderUnavailableError
from motionile.modules.voices.exceptions import (
    VoiceBusyError,
    VoiceNotAvailableError,
    VoiceNotFoundError,
    VoicePreviewFailedError,
    VoicePreviewNotReadyError,
    VoiceProviderUnavailableError,
    VoiceUpdateEmptyError,
)
from motionile.modules.voices.repository import VoiceFilter
from motionile.modules.voices.selectable import selectable_voice

ALL = VoiceFilter()


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return build_harness(monkeypatch)


async def ready_clone(harness: Harness) -> UUID:
    voice_id, _ = await submitted(harness)
    await harness.runner.run(voice_id, None)
    assert harness.world.voices[voice_id].status == "ready"
    return voice_id


async def test_users_see_ready_builtin_voices_and_their_own_voices_only(harness: Harness) -> None:
    ready = harness.world.add_voice(name="Ready")
    harness.world.add_voice(name="Disabled", status="disabled")
    own = harness.world.add_voice(
        name="Own", kind="cloned", owner_user_id=USER, status="pending", provider_voice_id=None
    )
    failed = harness.world.add_voice(
        name="Failed", kind="cloned", owner_user_id=USER, status="failed", failure_code="consent_mismatch"
    )
    harness.world.add_voice(name="Theirs", kind="cloned", owner_user_id=OTHER)

    listing = await harness.service.list_voices(USER, ALL, None, 20)

    assert {item.id for item in listing.items} == {ready.id, own.id, failed.id}
    by_id = {item.id: item for item in listing.items}
    assert by_id[failed.id].failure_code == "consent_mismatch"
    assert by_id[own.id].status.value == "pending"
    assert not by_id[own.id].has_preview


async def test_the_list_filters_by_language_and_kind_and_pages_with_a_cursor(harness: Harness) -> None:
    english = harness.world.add_voice(name="English", language="en-IN")
    hindi = harness.world.add_voice(name="Hindi", language="hi")
    own = harness.world.add_voice(name="Own", kind="cloned", owner_user_id=USER, language="en")

    assert {item.id for item in (await harness.service.list_voices(USER, VoiceFilter("en"), None, 20)).items} == {
        english.id,
        own.id,
    }
    assert [
        item.id for item in (await harness.service.list_voices(USER, VoiceFilter(kind="cloned"), None, 20)).items
    ] == [own.id]
    first = await harness.service.list_voices(USER, ALL, None, 2)
    assert first.next_cursor is not None
    second = await harness.service.list_voices(USER, ALL, Cursor(first.next_cursor.created_at, first.next_cursor.id), 2)
    assert second.next_cursor is None
    assert {item.id for item in [*first.items, *second.items]} == {english.id, hindi.id, own.id}


async def test_a_voice_that_is_not_visible_is_not_found(harness: Harness) -> None:
    disabled = harness.world.add_voice(status="disabled")
    theirs = harness.world.add_voice(kind="cloned", owner_user_id=OTHER)
    mine = harness.world.add_voice(kind="cloned", owner_user_id=USER, status="pending", provider_voice_id=None)

    assert (await harness.service.get_voice(USER, mine.id)).status.value == "pending"
    for voice_id in (disabled.id, theirs.id, new_id()):
        with pytest.raises(VoiceNotFoundError):
            await harness.service.get_voice(USER, voice_id)
        with pytest.raises(VoiceNotFoundError):
            await harness.service.preview_url(USER, voice_id)


async def test_the_preview_url_needs_a_stored_preview(harness: Harness) -> None:
    voice = harness.world.add_voice()
    with pytest.raises(VoicePreviewNotReadyError):
        await harness.service.preview_url(USER, voice.id)

    await harness.service.admin_regenerate_preview(ADMIN, voice.id, CONTEXT)
    preview = await harness.service.preview_url(USER, voice.id)

    assert f"voice-preview/{voice.id}.wav" in preview.url
    assert preview.expires_at > harness.clock.now()


async def test_deleting_a_clone_removes_provider_voice_samples_preview_cache_and_row_but_keeps_the_consent(
    harness: Harness,
) -> None:
    voice_id = await ready_clone(harness)
    voice = harness.world.voices[voice_id]
    provider_voice_id = voice.provider_voice_id
    [consent] = harness.world.consents
    assert provider_voice_id is not None
    assert harness.world.media.entries

    await harness.service.delete_voice(USER, voice_id, CONTEXT)

    assert voice_id not in harness.world.voices
    assert provider_voice_id in harness.provider.deleted
    assert harness.world.media.entries == {}
    assert consent.voice_id is None
    assert consent.voice_reference == voice_id
    remaining = [asset.storage_key for asset in harness.world.media.assets.values()]
    assert remaining == [f"voice/u/{USER}/{voice_id}/consent.wav"]
    assert list(harness.storage.objects) == remaining
    assert [event.action for event in harness.audit][-1] == "voices.deleted"
    with pytest.raises(VoiceNotFoundError):
        await harness.service.delete_voice(USER, voice_id, CONTEXT)


async def test_a_provider_that_no_longer_knows_the_voice_counts_as_deleted(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    voice_id = await ready_clone(harness)

    async def gone(provider_voice_id: str) -> None:
        del provider_voice_id
        raise ProviderNotFoundError("gone", status_code=404)

    monkeypatch.setattr(harness.provider, "delete", gone)

    await harness.service.delete_voice(USER, voice_id, CONTEXT)

    assert voice_id not in harness.world.voices


async def test_a_provider_failure_keeps_the_voice_so_the_user_can_retry(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    voice_id = await ready_clone(harness)
    original = harness.provider.delete

    async def down(provider_voice_id: str) -> None:
        del provider_voice_id
        raise ProviderUnavailableError("down")

    monkeypatch.setattr(harness.provider, "delete", down)
    with pytest.raises(VoiceProviderUnavailableError):
        await harness.service.delete_voice(USER, voice_id, CONTEXT)
    assert voice_id in harness.world.voices
    assert len(harness.world.media.assets) == 5

    monkeypatch.setattr(harness.provider, "delete", original)
    await harness.service.delete_voice(USER, voice_id, CONTEXT)

    assert voice_id not in harness.world.voices


async def test_pending_builtin_and_foreign_voices_cannot_be_deleted(harness: Harness) -> None:
    pending = harness.world.add_voice(kind="cloned", owner_user_id=USER, status="pending", provider_voice_id=None)
    builtin = harness.world.add_voice()
    theirs = harness.world.add_voice(kind="cloned", owner_user_id=OTHER)

    with pytest.raises(VoiceBusyError):
        await harness.service.delete_voice(USER, pending.id, CONTEXT)
    for voice_id in (builtin.id, theirs.id):
        with pytest.raises(VoiceNotFoundError):
            await harness.service.delete_voice(USER, voice_id, CONTEXT)
    assert {pending.id, builtin.id, theirs.id} <= set(harness.world.voices)
    assert harness.provider.deleted == []


async def test_a_failed_voice_can_be_deleted_without_calling_the_provider(harness: Harness) -> None:
    failed = harness.world.add_voice(
        kind="cloned", owner_user_id=USER, status="failed", failure_code="provider_failed", provider_voice_id=None
    )

    await harness.service.delete_voice(USER, failed.id, CONTEXT)

    assert failed.id not in harness.world.voices
    assert harness.provider.deleted == []


async def test_sync_adds_new_provider_voices_as_disabled_and_is_idempotent(harness: Harness) -> None:
    first = await harness.service.admin_sync(ADMIN, CONTEXT)
    second = await harness.service.admin_sync(ADMIN, CONTEXT)

    assert (first.added, first.unchanged) == (4, 0)
    assert (second.added, second.unchanged) == (0, 4)
    assert {voice.status for voice in harness.world.voices.values()} == {"disabled"}
    assert {voice.kind for voice in harness.world.voices.values()} == {"builtin"}
    aria = next(voice for voice in harness.world.voices.values() if voice.name == "Aria")
    assert aria.labels == {"gender": "female", "accent": "neutral"}
    assert [event.action for event in harness.audit] == ["voices.synced", "voices.synced"]


async def test_sync_never_changes_curated_voices_and_skips_cloned_ones(harness: Harness) -> None:
    await harness.service.admin_sync(ADMIN, CONTEXT)
    aria = next(voice for voice in harness.world.voices.values() if voice.provider_voice_id == "fake-voice-aria")
    aria.name = "Curated"
    aria.status = "ready"
    harness.provider.cloned["fake-clone-1"] = ProviderVoice(
        "fake-clone-1", "Cloned", "en", {"category": "cloned"}, None
    )

    result = await harness.service.admin_sync(ADMIN, CONTEXT)

    assert result.added == 0
    assert (aria.name, aria.status) == ("Curated", "ready")
    assert not any(voice.provider_voice_id == "fake-clone-1" for voice in harness.world.voices.values())


async def test_a_failing_catalog_is_reported_as_a_provider_problem(harness: Harness) -> None:
    harness.switch.failure = ProviderUnavailableError("down")

    with pytest.raises(VoiceProviderUnavailableError):
        await harness.service.admin_sync(ADMIN, CONTEXT)


async def test_enabling_a_voice_generates_its_preview_first(harness: Harness) -> None:
    await harness.service.admin_sync(ADMIN, CONTEXT)
    voice = next(iter(harness.world.voices.values()))

    view = await harness.service.admin_update(
        ADMIN, voice.id, {"status": "ready", "tags": ["warm", "warm", "male"]}, CONTEXT
    )

    assert view.status.value == "ready"
    assert view.has_preview
    assert view.tags == ["warm", "male"]
    assert len(harness.tts.calls) == 1
    assert voice.preview_asset_id is not None
    assert harness.world.media.assets[voice.preview_asset_id].storage_key == f"voice-preview/{voice.id}.wav"
    assert harness.audit[-1].action == "voices.updated"


async def test_a_preview_failure_leaves_the_voice_disabled(harness: Harness) -> None:
    await harness.service.admin_sync(ADMIN, CONTEXT)
    voice = next(iter(harness.world.voices.values()))
    harness.tts.failure = ProviderRejectedError("no")

    with pytest.raises(VoicePreviewFailedError):
        await harness.service.admin_update(ADMIN, voice.id, {"status": "ready"}, CONTEXT)

    assert voice.status == "disabled"
    assert voice.preview_asset_id is None


async def test_curation_edits_name_language_and_disables_without_a_preview(harness: Harness) -> None:
    voice = harness.world.add_voice()

    view = await harness.service.admin_update(
        ADMIN, voice.id, {"name": "Warm", "language": "hi", "status": "disabled"}, CONTEXT
    )

    assert (view.name, view.language, view.status.value) == ("Warm", "hi", "disabled")
    assert harness.tts.calls == []
    with pytest.raises(VoiceUpdateEmptyError):
        await harness.service.admin_update(ADMIN, voice.id, {}, CONTEXT)


async def test_admin_operations_cannot_touch_cloned_voices(harness: Harness) -> None:
    clone = harness.world.add_voice(kind="cloned", owner_user_id=USER)

    with pytest.raises(VoiceNotFoundError):
        await harness.service.admin_update(ADMIN, clone.id, {"status": "disabled"}, CONTEXT)
    with pytest.raises(VoiceNotFoundError):
        await harness.service.admin_regenerate_preview(ADMIN, clone.id, CONTEXT)
    listing = await harness.service.admin_list(ALL, None, 20)
    assert listing.items == []


async def test_regenerating_a_preview_replaces_the_stored_clip(harness: Harness) -> None:
    voice = harness.world.add_voice()
    await harness.service.admin_regenerate_preview(ADMIN, voice.id, CONTEXT)
    first = voice.preview_asset_id

    await harness.service.admin_regenerate_preview(ADMIN, voice.id, CONTEXT)

    assert voice.preview_asset_id is not None
    assert voice.preview_asset_id != first
    assert first not in harness.world.media.assets
    assert sum(1 for key in harness.storage.objects if key.startswith("voice-preview/")) == 1


async def test_only_ready_builtin_voices_and_own_ready_clones_are_selectable(harness: Harness) -> None:
    builtin = harness.world.add_voice()
    disabled = harness.world.add_voice(status="disabled")
    mine = harness.world.add_voice(kind="cloned", owner_user_id=USER)
    pending = harness.world.add_voice(kind="cloned", owner_user_id=USER, status="pending", provider_voice_id=None)
    theirs = harness.world.add_voice(kind="cloned", owner_user_id=OTHER)
    session = harness.world.media.transaction

    async with session() as db:
        for voice in (builtin, mine):
            assert (await selectable_voice(db, USER, voice.id, harness.world.store)).id == voice.id
        for voice_id in (disabled.id, pending.id, theirs.id, new_id()):
            with pytest.raises(VoiceNotAvailableError):
                await selectable_voice(db, USER, voice_id, harness.world.store)
