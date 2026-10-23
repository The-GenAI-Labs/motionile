from pathlib import Path
from uuid import UUID

import pytest
from tests.integration.test_auth import csrf
from tests.integration.voices_support import (
    BASE,
    VoicesApi,
    create_clone,
    fetch_url,
    locate_tools,
    make_audio,
    make_video,
    post_sample,
    put_consent,
    ready_clone,
    set_default_voice,
    start_attempt,
    submit_attempt,
)

from motionile.core.config import VoicesSettings
from motionile.engine.audio.providers.base import ProviderUnavailableError
from motionile.engine.ffmpeg import FfmpegTools
from motionile.modules.media import voice_prefix


@pytest.fixture(scope="session")
def tools() -> FfmpegTools:
    return locate_tools()


@pytest.fixture
async def consent(tools: FfmpegTools, tmp_path: Path) -> bytes:
    return await make_audio(tools, tmp_path, "consent.wav", 5)


@pytest.fixture
async def sample(tools: FfmpegTools, tmp_path: Path) -> bytes:
    return await make_audio(tools, tmp_path, "sample.mp3", 20, "-c:a", "libmp3lame")


async def test_a_correct_recording_makes_a_ready_voice_with_a_complete_consent_row(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    primary = voices_api.media.primary
    attempt, voice = await create_clone(voices_api, consent, sample)
    voice_id = str(voice["id"])
    assert voice["status"] == "pending"
    assert voice["id"] == attempt["voiceId"]
    assert (await primary.get(f"{BASE}/{voice_id}")).json()["status"] == "pending"

    await voices_api.run_clone(UUID(voice_id), sentence=str(attempt["consentSentence"]))

    ready = (await primary.get(f"{BASE}/{voice_id}")).json()
    assert (ready["status"], ready["kind"], ready["failureCode"], ready["hasPreview"]) == (
        "ready",
        "cloned",
        None,
        True,
    )
    [row] = await voices_api.rows(
        "SELECT statement_version, encode(statement_sha256, 'hex'), accepted_at, host(ip), user_agent,"
        " challenge_sentence, match_percent, sample_count, sample_total_ms, voice_id, user_id, a.storage_key, a.kind "
        "FROM voice_consents c JOIN assets a ON a.id = c.consent_asset_id WHERE voice_reference = :id",
        id=UUID(voice_id),
    )
    assert row[0] == "2026-10-19"
    assert len(row[1]) == 64
    assert row[2] is not None
    assert row[3] is not None
    assert row[5] == attempt["consentSentence"]
    assert (row[6], row[7]) == (100, 2)
    assert 39_000 <= row[8] <= 41_000
    assert (str(row[9]), str(row[10])) == (voice_id, str(voices_api.media.primary_id))
    assert row[11] == f"{voice_prefix(voices_api.media.primary_id, UUID(voice_id))}consent.wav"
    assert row[12] == "voice_sample"
    assert voices_api.provider.cloned


async def test_the_ready_voice_can_be_the_default_voice_and_has_a_playable_preview(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    primary = voices_api.media.primary
    voice_id = await ready_clone(voices_api, consent, sample)

    chosen = await set_default_voice(primary, str(voice_id))
    preview = await primary.get(f"{BASE}/{voice_id}/preview")

    assert chosen.status_code == 200
    assert chosen.json()["defaultVoiceId"] == str(voice_id)
    assert preview.status_code == 200
    audio = await fetch_url(preview.json()["url"])
    assert audio.status_code == 200
    assert audio.content[:4] == b"RIFF"
    listing = (await primary.get(BASE)).json()
    assert [item["id"] for item in listing["items"]] == [str(voice_id)]
    assert (await set_default_voice(primary, None)).json()["defaultVoiceId"] is None


async def test_a_default_voice_must_be_selectable_by_the_user(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    other_voice = await ready_clone(voices_api, consent, sample, voices_api.media.other)
    pending = (await create_clone(voices_api, consent, sample))[1]

    for voice_id in (str(other_voice), str(pending["id"]), str(UUID(int=1))):
        response = await set_default_voice(voices_api.media.primary, voice_id)
        assert response.status_code == 422
        assert response.json()["code"] == "voice_not_available"
    assert (await voices_api.media.primary.get("/v1/users/me/preferences")).json()["defaultVoiceId"] is None


async def test_a_wrong_consent_recording_fails_the_voice_and_removes_its_files(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    attempt, voice = await create_clone(voices_api, consent, sample)
    voice_id = UUID(str(voice["id"]))

    await voices_api.run_clone(voice_id, sentence=str(attempt["consentSentence"]), matching=False)

    failed = (await voices_api.media.primary.get(f"{BASE}/{voice_id}")).json()
    assert (failed["status"], failed["failureCode"]) == ("failed", "consent_mismatch")
    prefix = voice_prefix(voices_api.media.primary_id, voice_id)
    assert await voices_api.scalar("SELECT count(*) FROM assets WHERE storage_key LIKE :p", p=prefix + "%") == 0
    assert await voices_api.scalar("SELECT count(*) FROM voice_consents") == 0
    assert voices_api.provider.cloned == {}
    assert await voices_api.media.storage.head(f"{prefix}consent.wav") is None
    assert await voices_api.media.storage.head(f"{prefix}sample-0.wav") is None


async def test_a_cloning_cost_is_reserved_committed_on_success_and_released_on_failure(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    primary_id = voices_api.media.primary_id
    await voices_api.set_setting("voices.clone_credit_cost", 40)
    await voices_api.fund(primary_id, 100)

    attempt, voice = await create_clone(voices_api, consent, sample)
    assert await voices_api.rows("SELECT balance, reserved FROM credit_wallets WHERE user_id = :u", u=primary_id) == [
        (100, 40)
    ]
    await voices_api.run_clone(UUID(str(voice["id"])), sentence=str(attempt["consentSentence"]))
    assert await voices_api.rows("SELECT balance, reserved FROM credit_wallets WHERE user_id = :u", u=primary_id) == [
        (60, 0)
    ]

    failing_attempt, failing = await create_clone(voices_api, consent, sample)
    assert await voices_api.rows("SELECT balance, reserved FROM credit_wallets WHERE user_id = :u", u=primary_id) == [
        (60, 40)
    ]
    await voices_api.run_clone(
        UUID(str(failing["id"])), sentence=str(failing_attempt["consentSentence"]), matching=False
    )

    assert await voices_api.rows("SELECT balance, reserved FROM credit_wallets WHERE user_id = :u", u=primary_id) == [
        (60, 0)
    ]
    reasons = await voices_api.rows(
        "SELECT reason FROM credit_ledger WHERE user_id = :u ORDER BY created_at, id", u=primary_id
    )
    assert [row[0] for row in reasons] == ["purchase", "reserve", "commit", "reserve", "release"]


async def test_not_enough_credits_refuse_the_submit_with_the_insufficient_credits_problem(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    primary = voices_api.media.primary
    await voices_api.set_setting("voices.clone_credit_cost", 40)
    await voices_api.fund(voices_api.media.primary_id, 10)
    attempt = (await start_attempt(primary)).json()
    await put_consent(primary, str(attempt["attemptId"]), consent)
    await post_sample(primary, str(attempt["attemptId"]), sample)
    await post_sample(primary, str(attempt["attemptId"]), sample)

    response = await submit_attempt(primary, str(attempt["attemptId"]))

    assert response.status_code == 402
    assert response.json()["code"] == "insufficient_credits"
    assert voices_api.enqueued == []
    assert await voices_api.scalar("SELECT count(*) FROM voices") == 0
    assert (await primary.get(f"{BASE}/clones/{attempt['attemptId']}")).status_code == 200


async def test_the_quota_blocks_a_second_clone_and_a_failed_voice_does_not_count(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    primary = voices_api.media.primary
    await voices_api.set_setting("voices.max_cloned_per_user", 1)
    attempt, voice = await create_clone(voices_api, consent, sample)

    blocked = await start_attempt(primary)
    assert (blocked.status_code, blocked.json()["code"]) == (409, "voice_quota_exceeded")

    await voices_api.run_clone(UUID(str(voice["id"])), sentence=str(attempt["consentSentence"]), matching=False)
    assert (await start_attempt(primary)).status_code == 201


async def test_the_statement_version_must_match_the_current_one(voices_api: VoicesApi) -> None:
    primary = voices_api.media.primary

    stale = await primary.post(
        f"{BASE}/clones", json={"statementVersion": "2019-01-01", "accepted": True}, headers=csrf(primary)
    )
    declined = await primary.post(
        f"{BASE}/clones", json={"statementVersion": "2026-10-19", "accepted": False}, headers=csrf(primary)
    )

    assert (stale.status_code, stale.json()["code"]) == (409, "consent_statement_outdated")
    assert declined.status_code == 422


async def test_sample_totals_are_bounded_at_submit_and_at_upload(
    voices_api: VoicesApi, tools: FfmpegTools, tmp_path: Path
) -> None:
    resources = voices_api.media.resources
    resources.settings = resources.settings.model_copy(
        update={"voices": VoicesSettings(sample_min_total_seconds=30, sample_max_total_seconds=45)}
    )
    primary = voices_api.media.primary
    consent = await make_audio(tools, tmp_path, "c.wav", 5)
    twenty = await make_audio(tools, tmp_path, "s20.wav", 20)
    attempt = (await start_attempt(primary)).json()
    attempt_id = str(attempt["attemptId"])
    await put_consent(primary, attempt_id, consent)
    await post_sample(primary, attempt_id, twenty)

    short = await submit_attempt(primary, attempt_id)
    await post_sample(primary, attempt_id, twenty)
    over = await post_sample(primary, attempt_id, twenty)

    assert (short.status_code, short.json()["code"]) == (422, "samples_too_short")
    assert (over.status_code, over.json()["code"]) == (422, "samples_too_long")
    state = (await primary.get(f"{BASE}/clones/{attempt_id}")).json()
    assert len(state["samples"]) == 2
    assert (await submit_attempt(primary, attempt_id)).status_code == 202


async def test_the_consent_recording_must_last_between_three_and_thirty_seconds(
    voices_api: VoicesApi, tools: FfmpegTools, tmp_path: Path
) -> None:
    primary = voices_api.media.primary
    attempt_id = str((await start_attempt(primary)).json()["attemptId"])

    short = await put_consent(primary, attempt_id, await make_audio(tools, tmp_path, "short.wav", 1))
    long = await put_consent(primary, attempt_id, await make_audio(tools, tmp_path, "long.wav", 35))
    fine = await put_consent(primary, attempt_id, await make_audio(tools, tmp_path, "fine.wav", 6))

    assert (short.status_code, short.json()["code"]) == (422, "audio_too_short")
    assert (long.status_code, long.json()["code"]) == (422, "audio_too_long")
    assert fine.status_code == 200
    assert 5_000 <= fine.json()["consentRecording"]["durationMs"] <= 7_000


async def test_a_submit_without_a_consent_recording_is_refused(voices_api: VoicesApi, sample: bytes) -> None:
    primary = voices_api.media.primary
    attempt_id = str((await start_attempt(primary)).json()["attemptId"])
    await post_sample(primary, attempt_id, sample)
    await post_sample(primary, attempt_id, sample)

    response = await submit_attempt(primary, attempt_id)

    assert (response.status_code, response.json()["code"]) == (422, "consent_recording_missing")


async def test_uploads_that_are_not_audio_are_rejected(
    voices_api: VoicesApi, tools: FfmpegTools, tmp_path: Path
) -> None:
    primary = voices_api.media.primary
    attempt_id = str((await start_attempt(primary)).json()["attemptId"])
    png = b"\x89PNG\r\n\x1a\n" + bytes(200)
    attacks = {
        "audio_not_audio": [b"<html><script>alert(1)</script></html>" * 20, png, b"", b"MZ" + bytes(500)],
        "audio_video_stream_present": [await make_video(tools, tmp_path)],
    }

    for code, payloads in attacks.items():
        for payload in payloads:
            for response in (
                await put_consent(primary, attempt_id, payload),
                await post_sample(primary, attempt_id, payload),
            ):
                assert response.status_code == 422, (code, response.text)
                assert response.json()["code"] == code

    assert await voices_api.scalar("SELECT count(*) FROM assets") == 0


async def test_a_body_far_over_the_limit_is_cut_off_while_streaming(voices_api: VoicesApi) -> None:
    resources = voices_api.media.resources
    resources.settings = resources.settings.model_copy(update={"voices": VoicesSettings(sample_max_bytes=1_048_576)})
    primary = voices_api.media.primary
    attempt_id = str((await start_attempt(primary)).json()["attemptId"])

    response = await post_sample(primary, attempt_id, b"RIFF" + bytes(3_000_000))

    assert (response.status_code, response.json()["code"]) == (413, "audio_too_large")
    assert await voices_api.scalar("SELECT count(*) FROM assets") == 0


async def test_an_oversized_upload_is_rejected_before_it_is_processed(voices_api: VoicesApi) -> None:
    resources = voices_api.media.resources
    resources.settings = resources.settings.model_copy(update={"voices": VoicesSettings(sample_max_bytes=1_048_576)})
    primary = voices_api.media.primary
    attempt_id = str((await start_attempt(primary)).json()["attemptId"])

    response = await post_sample(primary, attempt_id, b"RIFF" + bytes(1_100_000))

    assert (response.status_code, response.json()["code"]) == (413, "audio_too_large")
    assert await voices_api.scalar("SELECT count(*) FROM assets") == 0


async def test_a_polyglot_upload_is_stored_only_as_the_transcoded_wav(
    voices_api: VoicesApi, tools: FfmpegTools, tmp_path: Path
) -> None:
    primary = voices_api.media.primary
    attempt_id = str((await start_attempt(primary)).json()["attemptId"])
    marker = b"<script>alert('polyglot')</script>"
    polyglot = await make_audio(tools, tmp_path, "poly.wav", 6) + marker * 10

    response = await put_consent(primary, attempt_id, polyglot, "evil.html")

    assert response.status_code == 200, response.text
    [key] = [row[0] for row in await voices_api.rows("SELECT storage_key FROM assets")]
    stored = b"".join([chunk async for chunk in voices_api.media.storage.get(key)])
    assert stored[:4] == b"RIFF"
    assert marker not in stored
    assert key.endswith("/consent.wav")


async def test_another_users_attempt_and_voice_are_not_found(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    other = voices_api.media.other
    attempt = (await start_attempt(voices_api.media.primary)).json()
    attempt_id = str(attempt["attemptId"])
    await put_consent(voices_api.media.primary, attempt_id, consent)
    state = (await post_sample(voices_api.media.primary, attempt_id, sample)).json()
    voice_id = await ready_clone(voices_api, consent, sample)

    attempts = [
        await other.get(f"{BASE}/clones/{attempt_id}"),
        await put_consent(other, attempt_id, consent),
        await post_sample(other, attempt_id, sample),
        await other.delete(f"{BASE}/clones/{attempt_id}/samples/{state['samples'][0]['id']}", headers=csrf(other)),
        await submit_attempt(other, attempt_id),
    ]
    voices = [
        await other.get(f"{BASE}/{voice_id}"),
        await other.get(f"{BASE}/{voice_id}/preview"),
        await other.delete(f"{BASE}/{voice_id}", headers=csrf(other)),
    ]

    assert [response.status_code for response in attempts] == [404] * 5
    assert {response.json()["code"] for response in attempts} == {"clone_attempt_not_found"}
    assert [response.status_code for response in voices] == [404] * 3
    assert {response.json()["code"] for response in voices} == {"voice_not_found"}
    assert (await other.get(BASE)).json()["items"] == []
    assert await voices_api.scalar("SELECT count(*) FROM voices") == 1


async def test_anonymous_callers_are_unauthorized(voices_api: VoicesApi) -> None:
    anonymous = voices_api.media.anonymous
    some = UUID(int=5)

    responses = [
        await anonymous.get(BASE),
        await anonymous.get(f"{BASE}/{some}"),
        await anonymous.get(f"{BASE}/{some}/preview"),
        await anonymous.get(f"{BASE}/clones/{some}"),
    ]

    assert [response.status_code for response in responses] == [401] * 4


async def test_a_sample_can_be_removed_from_an_attempt(voices_api: VoicesApi, sample: bytes) -> None:
    primary = voices_api.media.primary
    attempt_id = str((await start_attempt(primary)).json()["attemptId"])
    first = (await post_sample(primary, attempt_id, sample)).json()
    sample_id = first["samples"][0]["id"]

    removed = await primary.delete(f"{BASE}/clones/{attempt_id}/samples/{sample_id}", headers=csrf(primary))
    again = await primary.delete(f"{BASE}/clones/{attempt_id}/samples/{sample_id}", headers=csrf(primary))

    assert removed.status_code == 200
    assert removed.json()["samples"] == []
    assert again.status_code == 404
    assert again.json()["code"] == "clone_sample_not_found"
    assert await voices_api.scalar("SELECT count(*) FROM assets") == 0


async def test_deleting_a_voice_removes_everything_but_the_consent_evidence(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    primary = voices_api.media.primary
    storage = voices_api.media.storage
    owner = voices_api.media.primary_id
    voice_id = await ready_clone(voices_api, consent, sample)
    await set_default_voice(primary, str(voice_id))
    prefix = voice_prefix(owner, voice_id)
    preview_key = await voices_api.scalar(
        "SELECT a.storage_key FROM voices v JOIN assets a ON a.id = v.preview_asset_id WHERE v.id = :id", id=voice_id
    )
    provider_voice_id = await voices_api.scalar("SELECT provider_voice_id FROM voices WHERE id = :id", id=voice_id)
    assert await voices_api.scalar("SELECT count(*) FROM tts_cache WHERE provider_voice_id = :p", p=provider_voice_id)
    assert await storage.head(f"{prefix}sample-0.wav") is not None

    deleted = await primary.delete(f"{BASE}/{voice_id}", headers=csrf(primary))

    assert deleted.status_code == 204
    assert provider_voice_id in voices_api.provider.deleted
    assert await voices_api.scalar("SELECT count(*) FROM voices WHERE id = :id", id=voice_id) == 0
    assert (
        await voices_api.scalar("SELECT count(*) FROM tts_cache WHERE provider_voice_id = :p", p=provider_voice_id) == 0
    )
    for key in (f"{prefix}sample-0.wav", f"{prefix}sample-1.wav", preview_key):
        assert await storage.head(key) is None
    assert await storage.head(f"{prefix}consent.wav") is not None
    assert await voices_api.rows("SELECT voice_id, voice_reference FROM voice_consents") == [(None, voice_id)]
    assert (await primary.get("/v1/users/me/preferences")).json()["defaultVoiceId"] is None
    assert (await primary.get(f"{BASE}/{voice_id}")).status_code == 404
    assert (await primary.delete(f"{BASE}/{voice_id}", headers=csrf(primary))).status_code == 404


async def test_a_pending_voice_cannot_be_deleted(voices_api: VoicesApi, consent: bytes, sample: bytes) -> None:
    primary = voices_api.media.primary
    _, voice = await create_clone(voices_api, consent, sample)

    response = await primary.delete(f"{BASE}/{voice['id']}", headers=csrf(primary))

    assert (response.status_code, response.json()["code"]) == (409, "voice_busy")
    assert await voices_api.scalar("SELECT count(*) FROM voices") == 1


async def test_a_provider_failure_keeps_the_voice_and_a_retry_succeeds(
    voices_api: VoicesApi, consent: bytes, sample: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = voices_api.media.primary
    voice_id = await ready_clone(voices_api, consent, sample)
    provider = voices_api.provider
    original = provider.delete

    async def down(provider_voice_id: str) -> None:
        del provider_voice_id
        raise ProviderUnavailableError("down")

    monkeypatch.setattr(provider, "delete", down)
    failed = await primary.delete(f"{BASE}/{voice_id}", headers=csrf(primary))
    monkeypatch.setattr(provider, "delete", original)

    assert (failed.status_code, failed.json()["code"]) == (502, "voice_provider_unavailable")
    assert (await primary.get(f"{BASE}/{voice_id}")).json()["status"] == "ready"
    assert (await primary.delete(f"{BASE}/{voice_id}", headers=csrf(primary))).status_code == 204


async def test_the_voice_preview_is_not_ready_until_it_exists(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    primary = voices_api.media.primary
    _, voice = await create_clone(voices_api, consent, sample)

    response = await primary.get(f"{BASE}/{voice['id']}/preview")

    assert (response.status_code, response.json()["code"]) == (404, "voice_preview_not_ready")


async def test_a_retried_submit_with_the_same_key_returns_the_same_voice(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    primary = voices_api.media.primary
    attempt_id = str((await start_attempt(primary)).json()["attemptId"])
    await put_consent(primary, attempt_id, consent)
    await post_sample(primary, attempt_id, sample)
    await post_sample(primary, attempt_id, sample)

    first = await submit_attempt(primary, attempt_id, key="same-key-1")
    second = await submit_attempt(primary, attempt_id, key="same-key-1")
    missing = await primary.post(
        f"{BASE}/clones/{attempt_id}/submit",
        json={"name": "My voice", "language": "en"},
        headers=csrf(primary),
    )

    assert first.status_code == second.status_code == 202
    assert first.json()["id"] == second.json()["id"]
    assert len(voices_api.enqueued) == 1
    assert missing.status_code == 400
