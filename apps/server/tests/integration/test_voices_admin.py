from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.test_auth import csrf
from tests.integration.voices_support import (
    BASE,
    VoicesApi,
    locate_tools,
    make_audio,
    ready_clone,
    set_default_voice,
)

from motionile.engine.audio.models import SynthesisOptions, SynthesisResult, VoiceRef
from motionile.engine.audio.providers.base import ProviderRejectedError
from motionile.engine.audio.providers.fake import FakeTTSProvider
from motionile.engine.ffmpeg import FfmpegTools
from motionile.modules.media import voice_prefix
from motionile.modules.users import export_registry, purge_registry
from motionile.modules.voices import hooks as hooks_module

ADMIN = "/v1/admin/voices"


@pytest.fixture(scope="session")
def tools() -> FfmpegTools:
    return locate_tools()


@pytest.fixture
async def curator(voices_api: VoicesApi) -> AsyncClient:
    await voices_api.media.grant_permissions(voices_api.media.other_id, "voices", "voices.manage")
    return voices_api.media.other


async def synced(client: AsyncClient) -> list[dict[str, object]]:
    response = await client.post(f"{ADMIN}/sync", headers=csrf(client))
    assert response.status_code == 200, response.text
    listing = await client.get(ADMIN)
    return list(listing.json()["items"])


async def test_the_admin_endpoints_need_the_voices_manage_permission(voices_api: VoicesApi) -> None:
    primary = voices_api.media.primary
    voice_id = UUID(int=9)

    responses = [
        await primary.get(ADMIN),
        await primary.post(f"{ADMIN}/sync", headers=csrf(primary)),
        await primary.patch(f"{ADMIN}/{voice_id}", json={"status": "ready"}, headers=csrf(primary)),
        await primary.post(f"{ADMIN}/{voice_id}/preview", headers=csrf(primary)),
    ]

    assert [response.status_code for response in responses] == [403] * 4
    assert (await voices_api.media.anonymous.get(ADMIN)).status_code == 401


async def test_sync_adds_disabled_voices_once_and_curation_exposes_them(
    voices_api: VoicesApi, curator: AsyncClient
) -> None:
    primary = voices_api.media.primary

    first = await curator.post(f"{ADMIN}/sync", headers=csrf(curator))
    second = await curator.post(f"{ADMIN}/sync", headers=csrf(curator))
    items = (await curator.get(ADMIN)).json()["items"]

    assert first.json() == {"added": 4, "unchanged": 0}
    assert second.json() == {"added": 0, "unchanged": 4}
    assert {item["status"] for item in items} == {"disabled"}
    assert {item["provider"] for item in items} == {"fake"}
    assert (await primary.get(BASE)).json()["items"] == []
    disabled = (await curator.get(f"{ADMIN}?status=disabled&language=hi")).json()["items"]
    assert {item["name"] for item in disabled} == {"Esha", "Ravi"}
    target = next(item for item in items if item["name"] == "Aria")

    enabled = await curator.patch(
        f"{ADMIN}/{target['id']}",
        json={"name": "Aria warm", "language": "en-IN", "tags": ["warm", "female"], "status": "ready"},
        headers=csrf(curator),
    )

    assert enabled.status_code == 200, enabled.text
    body = enabled.json()
    assert (body["name"], body["language"], body["status"], body["hasPreview"]) == ("Aria warm", "en-IN", "ready", True)
    assert body["tags"] == ["warm", "female"]
    assert body["labels"] == {"gender": "female", "accent": "neutral"}
    listing = (await primary.get(f"{BASE}?language=en")).json()["items"]
    assert [item["id"] for item in listing] == [target["id"]]
    preview = await primary.get(f"{BASE}/{target['id']}/preview")
    assert preview.status_code == 200
    assert (await set_default_voice(primary, str(target["id"]))).status_code == 200
    preview_key = await voices_api.scalar(
        "SELECT a.storage_key FROM voices v JOIN assets a ON a.id = v.preview_asset_id WHERE v.id = :id",
        id=UUID(str(target["id"])),
    )
    assert preview_key == f"voice-preview/{target['id']}.wav"
    assert await voices_api.scalar("SELECT owner_user_id FROM assets WHERE storage_key = :k", k=preview_key) is None

    disabled_again = await curator.patch(f"{ADMIN}/{target['id']}", json={"status": "disabled"}, headers=csrf(curator))

    assert disabled_again.json()["status"] == "disabled"
    assert (await primary.get(BASE)).json()["items"] == []
    assert (await primary.get(f"{BASE}/{target['id']}")).status_code == 404
    refused = await set_default_voice(voices_api.media.other, str(target["id"]))
    assert (refused.status_code, refused.json()["code"]) == (422, "voice_not_available")
    resync = await curator.post(f"{ADMIN}/sync", headers=csrf(curator))
    assert resync.json() == {"added": 0, "unchanged": 4}
    renamed = (await curator.get(f"{ADMIN}?language=en")).json()["items"]
    assert [item["name"] for item in renamed if item["id"] == target["id"]] == ["Aria warm"]


async def test_curation_actions_are_audited(voices_api: VoicesApi, curator: AsyncClient) -> None:
    items = await synced(curator)
    await curator.patch(f"{ADMIN}/{items[0]['id']}", json={"tags": ["calm"]}, headers=csrf(curator))
    await curator.post(f"{ADMIN}/{items[0]['id']}/preview", headers=csrf(curator))

    rows = await voices_api.rows(
        "SELECT action, target_type, actor_user_id FROM audit_log WHERE action LIKE 'voices.%' ORDER BY created_at, id"
    )

    assert [row[0] for row in rows] == ["voices.synced", "voices.updated", "voices.preview_regenerated"]
    assert {row[2] for row in rows} == {voices_api.media.other_id}


async def test_enabling_fails_with_a_clear_code_when_the_preview_cannot_be_generated(
    voices_api: VoicesApi, curator: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    items = await synced(curator)

    async def reject(self: FakeTTSProvider, text: str, voice: VoiceRef, options: SynthesisOptions) -> SynthesisResult:
        del self, text, voice, options
        raise ProviderRejectedError("no speech")

    monkeypatch.setattr(FakeTTSProvider, "synthesize", reject)

    response = await curator.patch(f"{ADMIN}/{items[0]['id']}", json={"status": "ready"}, headers=csrf(curator))

    assert (response.status_code, response.json()["code"]) == (502, "voice_preview_failed")
    assert (
        await voices_api.scalar("SELECT status FROM voices WHERE id = :id", id=UUID(str(items[0]["id"]))) == "disabled"
    )


async def test_invalid_curation_requests_are_rejected(voices_api: VoicesApi, curator: AsyncClient) -> None:
    items = await synced(curator)
    target = items[0]["id"]

    bodies = [{}, {"status": "pending"}, {"name": ""}, {"tags": ["Not Allowed!"]}, {"unknown": 1}]
    responses = [await curator.patch(f"{ADMIN}/{target}", json=body, headers=csrf(curator)) for body in bodies]

    assert [response.status_code for response in responses] == [422] * 5
    assert await voices_api.scalar("SELECT count(*) FROM voices WHERE status = 'ready'") == 0


async def test_admin_routes_cannot_touch_cloned_voices(
    voices_api: VoicesApi, curator: AsyncClient, tools: FfmpegTools, tmp_path: Path
) -> None:
    consent = await make_audio(tools, tmp_path, "c.wav", 5)
    sample = await make_audio(tools, tmp_path, "s.wav", 20)
    voice_id = await ready_clone(voices_api, consent, sample)

    responses = [
        await curator.patch(f"{ADMIN}/{voice_id}", json={"status": "disabled"}, headers=csrf(curator)),
        await curator.post(f"{ADMIN}/{voice_id}/preview", headers=csrf(curator)),
    ]

    assert [response.status_code for response in responses] == [404, 404]
    assert (await curator.get(ADMIN)).json()["items"] == []
    assert await voices_api.scalar("SELECT status FROM voices WHERE id = :id", id=voice_id) == "ready"


async def test_the_purge_hook_deletes_provider_voices_previews_and_cache_entries(
    voices_api: VoicesApi, tools: FfmpegTools, tmp_path: Path
) -> None:
    consent = await make_audio(tools, tmp_path, "c.wav", 5)
    sample = await make_audio(tools, tmp_path, "s.wav", 20)
    owner = voices_api.media.primary_id
    voice_id = await ready_clone(voices_api, consent, sample)
    provider_voice_id = await voices_api.scalar("SELECT provider_voice_id FROM voices WHERE id = :id", id=voice_id)
    resources = voices_api.media.resources

    async with voices_api.database.transaction() as session:
        await purge_registry.run(resources, session, owner)

    assert provider_voice_id in voices_api.provider.deleted
    assert (
        await voices_api.scalar("SELECT count(*) FROM tts_cache WHERE provider_voice_id = :p", p=provider_voice_id) == 0
    )
    assert await voices_api.scalar("SELECT preview_asset_id FROM voices WHERE id = :id", id=voice_id) is None
    assert await voices_api.scalar("SELECT count(*) FROM assets WHERE storage_key LIKE 'voice-preview/%'") == 0
    prefix = voice_prefix(owner, voice_id)
    for name in ("consent.wav", "sample-0.wav", "sample-1.wav"):
        assert await voices_api.media.storage.head(prefix + name) is None


async def test_a_provider_failure_never_blocks_the_purge_and_raises_an_alert(
    voices_api: VoicesApi, tools: FfmpegTools, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    consent = await make_audio(tools, tmp_path, "c.wav", 5)
    sample = await make_audio(tools, tmp_path, "s.wav", 20)
    voice_id = await ready_clone(voices_api, consent, sample)
    alerts: list[str] = []

    def collect(code: str, **fields: object) -> None:
        del fields
        alerts.append(code)

    monkeypatch.setattr(hooks_module, "raise_alert", collect)

    async def down(provider_voice_id: str) -> None:
        del provider_voice_id
        raise ProviderRejectedError("down")

    monkeypatch.setattr(voices_api.provider, "delete", down)

    async with voices_api.database.transaction() as session:
        await purge_registry.run(voices_api.media.resources, session, voices_api.media.primary_id)

    assert alerts == ["voice_provider_delete_failed"]
    assert await voices_api.scalar("SELECT count(*) FROM voices WHERE id = :id", id=voice_id) == 1


async def test_the_data_export_lists_voices_and_consents_without_audio(
    voices_api: VoicesApi, tools: FfmpegTools, tmp_path: Path
) -> None:
    consent = await make_audio(tools, tmp_path, "c.wav", 5)
    sample = await make_audio(tools, tmp_path, "s.wav", 20)
    voice_id = await ready_clone(voices_api, consent, sample)

    async with voices_api.database.transaction() as session:
        exported = await export_registry.export(session, voices_api.media.primary_id)
        other = await export_registry.export(session, voices_api.media.other_id)

    section = cast("dict[str, list[dict[str, Any]]]", exported["voices"])
    [voice] = section["voices"]
    [record] = section["consents"]
    assert (voice["id"], voice["status"], voice["kind"]) == (str(voice_id), "ready", "cloned")
    assert record["voice_reference"] == str(voice_id)
    assert len(record["statement_sha256"]) == 64
    assert record["match_percent"] == 100
    assert "provider_voice_id" not in voice
    assert "storage_key" not in record
    assert other["voices"] == {"voices": [], "consents": []}
