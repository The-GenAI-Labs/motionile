import hashlib
from collections.abc import Callable, Sequence
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.voices import STATEMENT
from tests.unit.modules.voices.support import CONTEXT, USER, Harness, build_harness, submitted

from motionile.engine.audio.models import CloneSample
from motionile.engine.audio.providers.base import (
    ProviderRejectedError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from motionile.modules.voices import runner as runner_module
from motionile.modules.voices.domain import VoiceFailureCode, clone_reservation_ttl
from motionile.modules.voices.maintenance import VoiceMaintenance


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return build_harness(monkeypatch)


def collector(alerts: list[str]) -> Callable[..., None]:
    def collect(code: str, **fields: object) -> None:
        del fields
        alerts.append(code)

    return collect


def wallet(harness: Harness) -> tuple[int, int]:
    record = harness.credits_store.wallets[USER]
    return record.balance, record.reserved


async def test_a_matching_recording_makes_the_voice_ready_and_writes_the_consent(harness: Harness) -> None:
    voice_id, _ = await submitted(harness)
    harness.clock.advance(timedelta(seconds=5))

    await harness.runner.run(voice_id, None)

    voice = harness.world.voices[voice_id]
    assert voice.status == "ready"
    assert voice.provider_voice_id is not None
    assert voice.provider_voice_id in harness.provider.cloned
    assert harness.provider.clone_calls == [("My voice", "en", 2)]
    [consent] = harness.world.consents
    assert (consent.voice_id, consent.voice_reference, consent.user_id) == (voice_id, voice_id, USER)
    assert consent.statement_sha256 == hashlib.sha256(STATEMENT.encode()).digest()
    assert consent.statement_version == harness.runtime.version
    assert consent.match_percent == 100
    assert consent.sample_count == 2
    assert consent.sample_total_ms == 80_000
    assert consent.ip is None
    assert consent.transcript.startswith("I confirm")
    assert consent.accepted_at < harness.clock.now()
    consent_asset = harness.world.media.assets[consent.consent_asset_id]
    assert consent_asset.storage_key == f"voice/u/{USER}/{voice_id}/consent.wav"
    assert len(harness.world.media.assets) == 5
    assert await harness.attempts.get_submission(voice_id) is None


async def test_the_preview_is_a_system_asset_under_the_preview_prefix(harness: Harness) -> None:
    voice_id, _ = await submitted(harness)

    await harness.runner.run(voice_id, None)

    voice = harness.world.voices[voice_id]
    assert voice.preview_asset_id is not None
    preview = harness.world.media.assets[voice.preview_asset_id]
    assert preview.owner_user_id is None
    assert preview.storage_key == f"voice-preview/{voice_id}.wav"
    assert preview.storage_key in harness.storage.objects
    [call] = harness.tts.calls
    assert call[1].provider_voice_id == voice.provider_voice_id
    assert call[2].language == "en"


async def test_a_mismatching_recording_fails_the_voice_and_removes_every_file(harness: Harness) -> None:
    voice_id, _ = await submitted(harness, matching=False)

    await harness.runner.run(voice_id, None)

    voice = harness.world.voices[voice_id]
    assert (voice.status, voice.failure_code) == ("failed", "consent_mismatch")
    assert harness.provider.clone_calls == []
    assert harness.world.consents == []
    assert harness.world.media.assets == {}
    assert harness.storage.objects == {}
    assert await harness.attempts.get_submission(voice_id) is None


async def test_credits_are_committed_when_the_voice_becomes_ready(harness: Harness) -> None:
    voice_id, reservation_id = await submitted(harness, cost=40)
    assert wallet(harness) == (100, 40)

    await harness.runner.run(voice_id, reservation_id)

    assert wallet(harness) == (60, 0)
    assert harness.world.voices[voice_id].status == "ready"
    keys = [entry.idempotency_key for entry in harness.credits_store.ledger]
    assert f"voice-clone:{voice_id}:commit" in keys


async def test_credits_are_released_when_the_consent_does_not_match(harness: Harness) -> None:
    voice_id, reservation_id = await submitted(harness, cost=40, matching=False)

    await harness.runner.run(voice_id, reservation_id)

    assert wallet(harness) == (100, 0)
    keys = [entry.idempotency_key for entry in harness.credits_store.ledger]
    assert f"voice-clone:{voice_id}:release" in keys
    assert f"voice-clone:{voice_id}:commit" not in keys


async def test_a_provider_rejection_of_the_samples_fails_with_sample_invalid(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def reject(name: str, language: str | None, samples: Sequence[CloneSample], description: str | None) -> str:
        del name, language, samples, description
        raise ProviderRejectedError("bad samples", reason="invalid_samples")

    monkeypatch.setattr(harness.provider, "clone", reject)
    voice_id, reservation_id = await submitted(harness, cost=10)

    await harness.runner.run(voice_id, reservation_id)

    voice = harness.world.voices[voice_id]
    assert (voice.status, voice.failure_code) == ("failed", "sample_invalid")
    assert harness.world.media.assets == {}
    assert wallet(harness) == (100, 0)


async def test_another_provider_failure_fails_with_provider_failed(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail(name: str, language: str | None, samples: Sequence[CloneSample], description: str | None) -> str:
        del name, language, samples, description
        raise ProviderResponseError("garbled")

    monkeypatch.setattr(harness.provider, "clone", fail)
    voice_id, _ = await submitted(harness)

    await harness.runner.run(voice_id, None)

    assert harness.world.voices[voice_id].failure_code == "provider_failed"


async def test_a_transient_provider_error_is_reraised_and_the_retry_completes(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = harness.provider.clone
    attempts: list[int] = []

    async def flaky(name: str, language: str | None, samples: Sequence[CloneSample], description: str | None) -> str:
        attempts.append(1)
        if len(attempts) == 1:
            raise ProviderUnavailableError("down")
        return await original(name, language, samples, description)

    monkeypatch.setattr(harness.provider, "clone", flaky)
    voice_id, _ = await submitted(harness)

    with pytest.raises(ProviderUnavailableError):
        await harness.runner.run(voice_id, None)
    assert harness.world.voices[voice_id].status == "pending"
    assert len(harness.world.media.assets) == 3

    await harness.runner.run(voice_id, None)

    assert harness.world.voices[voice_id].status == "ready"


async def test_a_retry_after_the_clone_does_not_create_a_second_provider_voice(harness: Harness) -> None:
    voice_id, _ = await submitted(harness)
    harness.tts.failure = ProviderUnavailableError("tts down")

    with pytest.raises(ProviderUnavailableError):
        await harness.runner.run(voice_id, None)
    assert harness.world.voices[voice_id].provider_voice_id is not None
    harness.tts.failure = None

    await harness.runner.run(voice_id, None)

    assert harness.world.voices[voice_id].status == "ready"
    assert len(harness.provider.clone_calls) == 1
    assert len(harness.provider.cloned) == 1


async def test_a_preview_failure_deletes_the_provider_voice_and_fails_the_clone(harness: Harness) -> None:
    voice_id, _ = await submitted(harness)
    harness.tts.failure = ProviderRejectedError("no speech")

    await harness.runner.run(voice_id, None)

    voice = harness.world.voices[voice_id]
    assert (voice.status, voice.failure_code, voice.provider_voice_id) == ("failed", "preview_failed", None)
    assert harness.provider.cloned == {}
    assert len(harness.provider.deleted) == 1
    assert harness.world.consents == []
    assert harness.world.media.assets == {}


async def test_a_missing_submission_fails_the_voice(harness: Harness) -> None:
    voice_id, _ = await submitted(harness)
    await harness.attempts.delete_submission(voice_id)

    await harness.runner.run(voice_id, None)

    assert harness.world.voices[voice_id].failure_code == VoiceFailureCode.ATTEMPT_EXPIRED.value


async def test_a_voice_that_is_not_pending_is_left_alone(harness: Harness) -> None:
    voice_id, _ = await submitted(harness)
    await harness.runner.run(voice_id, None)
    calls = len(harness.provider.clone_calls)

    await harness.runner.run(voice_id, None)

    assert len(harness.provider.clone_calls) == calls
    assert len(harness.world.consents) == 1


def ledger_keys(harness: Harness) -> list[str]:
    return [entry.idempotency_key for entry in harness.credits_store.ledger]


def assert_clone_removed_without_charge(harness: Harness, voice_id: UUID, code: str) -> None:
    voice = harness.world.voices[voice_id]
    assert (voice.status, voice.failure_code, voice.provider_voice_id) == ("failed", code, None)
    assert harness.provider.cloned == {}
    assert len(harness.provider.deleted) == 1
    assert harness.world.consents == []
    assert harness.world.media.assets == {}
    assert harness.storage.objects == {}
    assert wallet(harness) == (100, 0)
    assert f"voice-clone:{voice_id}:commit" not in ledger_keys(harness)


async def test_a_reservation_released_before_the_commit_fails_the_clone_without_charging(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    alerts: list[str] = []
    monkeypatch.setattr(runner_module, "raise_alert", collector(alerts))
    voice_id, reservation_id = await submitted(harness, cost=40)
    assert reservation_id is not None
    await harness.wallet_service.release(AsyncSession(), reservation_id, "manual-release")

    await harness.runner.run(voice_id, reservation_id)

    assert_clone_removed_without_charge(harness, voice_id, "credit_reservation_expired")
    assert alerts == ["voice_clone_credit_commit_failed"]
    assert await harness.attempts.get_submission(voice_id) is None


async def test_a_reservation_expired_by_the_ttl_sweeper_fails_the_clone_without_charging(
    harness: Harness,
) -> None:
    voice_id, reservation_id = await submitted(harness, cost=40)
    assert reservation_id is not None
    harness.clock.advance(clone_reservation_ttl() + timedelta(seconds=1))
    assert await harness.wallet_service.release_stale(AsyncSession(), reservation_id) is not None
    assert harness.credits_store.reservations[reservation_id].status == "expired"

    await harness.runner.run(voice_id, reservation_id)

    assert_clone_removed_without_charge(harness, voice_id, "credit_reservation_expired")


async def test_a_clone_that_lost_its_reservation_id_never_becomes_ready_and_frees_the_credits(
    harness: Harness,
) -> None:
    voice_id, _ = await submitted(harness, cost=40)

    await harness.runner.run(voice_id, None)

    assert_clone_removed_without_charge(harness, voice_id, "credit_reservation_expired")
    assert f"voice-clone:{voice_id}:release" in ledger_keys(harness)


async def test_a_commit_that_succeeds_makes_the_voice_ready_in_the_same_transaction(harness: Harness) -> None:
    voice_id, reservation_id = await submitted(harness, cost=40)
    assert reservation_id is not None

    await harness.runner.run(voice_id, reservation_id)

    assert harness.world.voices[voice_id].status == "ready"
    assert harness.credits_store.reservations[reservation_id].status == "committed"
    assert f"voice-clone:{voice_id}:release" not in ledger_keys(harness)


async def test_the_stall_sweeper_releases_the_reservation_of_a_stalled_clone(harness: Harness) -> None:
    voice_id, reservation_id = await submitted(harness, cost=40)
    assert reservation_id is not None
    maintenance = VoiceMaintenance(
        harness.world.transaction, harness.world.store, harness.assets, harness.runner, harness.clock
    )
    harness.clock.advance(timedelta(hours=3))
    harness.world.voices[voice_id].created_at = harness.clock.now() - timedelta(hours=3)

    assert await maintenance.fail_stalled_clones(timedelta(hours=2)) == 1

    assert harness.world.voices[voice_id].failure_code == "clone_stalled"
    assert harness.credits_store.reservations[reservation_id].status == "released"
    assert wallet(harness) == (100, 0)
    assert ledger_keys(harness).count(f"voice-clone:{voice_id}:release") == 1
    assert await maintenance.fail_stalled_clones(timedelta(hours=2)) == 0


async def test_a_retried_task_after_the_sweeper_failed_the_clone_neither_charges_nor_releases_again(
    harness: Harness,
) -> None:
    voice_id, reservation_id = await submitted(harness, cost=40)
    await harness.runner.fail(voice_id, VoiceFailureCode.CLONE_STALLED)

    await harness.runner.run(voice_id, reservation_id)
    await harness.runner.fail(voice_id, VoiceFailureCode.CLONE_STALLED)

    assert wallet(harness) == (100, 0)
    keys = ledger_keys(harness)
    assert keys.count(f"voice-clone:{voice_id}:release") == 1
    assert f"voice-clone:{voice_id}:commit" not in keys


async def test_the_sweeper_after_a_finalized_clone_leaves_the_charge_alone(harness: Harness) -> None:
    voice_id, reservation_id = await submitted(harness, cost=40)
    await harness.runner.run(voice_id, reservation_id)
    maintenance = VoiceMaintenance(
        harness.world.transaction, harness.world.store, harness.assets, harness.runner, harness.clock
    )
    harness.clock.advance(timedelta(hours=3))
    harness.world.voices[voice_id].created_at = harness.clock.now() - timedelta(hours=3)

    assert await maintenance.fail_stalled_clones(timedelta(hours=2)) == 0
    await harness.runner.fail(voice_id, VoiceFailureCode.CLONE_STALLED)

    assert harness.world.voices[voice_id].status == "ready"
    assert wallet(harness) == (60, 0)
    assert f"voice-clone:{voice_id}:release" not in ledger_keys(harness)


async def test_failing_an_already_failed_clone_releases_a_reservation_left_behind(harness: Harness) -> None:
    voice_id, reservation_id = await submitted(harness, cost=40)
    assert reservation_id is not None
    voice = harness.world.voices[voice_id]
    voice.status = "failed"
    voice.failure_code = "provider_failed"
    assert wallet(harness) == (100, 40)

    await harness.runner.fail(voice_id, VoiceFailureCode.CLONE_STALLED)
    await harness.runner.fail(voice_id, VoiceFailureCode.CLONE_STALLED)

    assert voice.failure_code == "provider_failed"
    assert wallet(harness) == (100, 0)
    assert ledger_keys(harness).count(f"voice-clone:{voice_id}:release") == 1
    assert harness.credits_store.reservations[reservation_id].status == "released"


async def test_an_undeletable_provider_voice_is_alerted_on_failure(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    alerts: list[str] = []
    monkeypatch.setattr(runner_module, "raise_alert", collector(alerts))

    async def refuse(provider_voice_id: str) -> None:
        del provider_voice_id
        raise ProviderUnavailableError("down")

    voice_id, _ = await submitted(harness)
    harness.tts.failure = ProviderRejectedError("no speech")
    monkeypatch.setattr(harness.provider, "delete", refuse)

    await harness.runner.run(voice_id, None)

    assert harness.world.voices[voice_id].status == "failed"
    assert alerts == ["voice_provider_delete_failed"]


async def test_maintenance_fails_stalled_clones_and_removes_abandoned_uploads(harness: Harness) -> None:
    voice_id, _ = await submitted(harness)
    started = await harness.clone.start(USER, harness.runtime.version, CONTEXT)
    await harness.clone.replace_consent_recording(USER, started.attempt_id, b"abandoned")
    maintenance = VoiceMaintenance(
        harness.world.media.transaction, harness.world.store, harness.assets, harness.runner, harness.clock
    )
    harness.clock.advance(timedelta(hours=1))
    for asset in harness.world.media.assets.values():
        asset.created_at = harness.clock.now() - timedelta(hours=5)
    harness.world.voices[voice_id].created_at = harness.clock.now() - timedelta(hours=3)

    assert await maintenance.fail_stalled_clones(timedelta(hours=2)) == 1
    removed = await maintenance.purge_abandoned_samples(timedelta(hours=3))

    assert harness.world.voices[voice_id].failure_code == "clone_stalled"
    assert removed == 1
    assert harness.world.media.assets == {}
