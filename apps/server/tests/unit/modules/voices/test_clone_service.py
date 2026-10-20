from datetime import timedelta
from ipaddress import IPv4Address
from typing import get_args

import pytest
from tests.fakes.voices import STATEMENT, VERSION
from tests.unit.modules.voices.support import CONTEXT, OTHER, USER, Harness, build_harness

from motionile.core.errors import AppError
from motionile.engine.audio.audio_validation import AudioRejectedError, RejectionCode
from motionile.engine.audio.voice_clone import CONSENT_PHRASE
from motionile.modules.audit import AuditContext
from motionile.modules.credits import InsufficientCreditsError
from motionile.modules.voices.clone import MAX_SAMPLE_FILES
from motionile.modules.voices.exceptions import (
    CloneAttemptBusyError,
    CloneAttemptNotFoundError,
    CloneSampleNotFoundError,
    ConsentRecordingMissingError,
    ConsentStatementOutdatedError,
    SamplesTooLongError,
    SamplesTooShortError,
    TooManySamplesError,
    VoiceQuotaExceededError,
)
from motionile.modules.voices.schemas import CloneSubmitRequest

SUBMIT = CloneSubmitRequest(name="My voice", language="en")


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> Harness:
    return build_harness(monkeypatch)


async def test_start_returns_the_statement_a_fresh_sentence_and_the_limits(harness: Harness) -> None:
    started = await harness.clone.start(USER, VERSION, CONTEXT)

    assert started.statement_text == STATEMENT
    assert started.statement_version == VERSION
    assert started.consent_sentence.startswith(CONSENT_PHRASE)
    assert started.limits.sample_min_total_seconds == 30
    assert started.limits.sample_max_total_seconds == 300
    assert started.limits.consent_max_seconds == 30
    assert started.expires_at == harness.clock.now() + timedelta(seconds=3600)
    other = await harness.clone.start(USER, VERSION, CONTEXT)
    assert other.consent_sentence != started.consent_sentence
    assert other.voice_id != started.voice_id


async def test_start_stores_the_attempt_with_a_ttl_and_the_acceptance_evidence(harness: Harness) -> None:
    context = AuditContext(ip=IPv4Address("203.0.113.9"), user_agent="Browser/1.0")

    started = await harness.clone.start(USER, VERSION, context)

    [key] = [key for key in harness.values.values if "voices.attempt:" in key]
    assert harness.values.ttls[key] == timedelta(seconds=3600)
    stored = await harness.attempts.get(started.attempt_id, USER)
    assert stored is not None
    assert (stored.ip, stored.user_agent) == ("203.0.113.9", "Browser/1.0")
    assert stored.accepted_at == harness.clock.now()
    assert len(stored.statement_sha256) == 64


async def test_a_different_statement_version_is_refused(harness: Harness) -> None:
    with pytest.raises(ConsentStatementOutdatedError):
        await harness.clone.start(USER, "2020-01-01", CONTEXT)
    assert harness.values.values == {}


async def test_start_refuses_a_user_at_the_quota_and_failed_voices_do_not_count(harness: Harness) -> None:
    harness.runtime.max_cloned = 1
    harness.world.add_voice(owner_user_id=USER, kind="cloned", status="failed", failure_code="consent_mismatch")
    await harness.clone.start(USER, VERSION, CONTEXT)
    harness.world.add_voice(owner_user_id=USER, kind="cloned", status="ready")

    with pytest.raises(VoiceQuotaExceededError):
        await harness.clone.start(USER, VERSION, CONTEXT)

    await harness.clone.start(OTHER, VERSION, CONTEXT)


async def test_another_users_attempt_is_not_found_on_every_operation(harness: Harness) -> None:
    attempt_id = await harness.prepared_attempt()

    with pytest.raises(CloneAttemptNotFoundError):
        await harness.clone.state(OTHER, attempt_id)
    with pytest.raises(CloneAttemptNotFoundError):
        await harness.clone.add_sample(OTHER, attempt_id, b"x")
    with pytest.raises(CloneAttemptNotFoundError):
        await harness.clone.replace_consent_recording(OTHER, attempt_id, b"x")
    with pytest.raises(CloneAttemptNotFoundError):
        await harness.clone.submit(OTHER, attempt_id, SUBMIT, CONTEXT)
    assert len(harness.processor.received) == 2


async def test_an_expired_attempt_is_not_found(harness: Harness) -> None:
    attempt_id = await harness.prepared_attempt()

    harness.clock.advance(timedelta(seconds=3601))

    with pytest.raises(CloneAttemptNotFoundError):
        await harness.clone.state(USER, attempt_id)


async def test_uploads_store_only_the_transcoded_audio_under_the_voice_prefix(harness: Harness) -> None:
    attempt_id = await harness.prepared_attempt(samples=2)

    state = await harness.clone.state(USER, attempt_id)

    keys = sorted(harness.storage.objects)
    assert [key.rsplit("/", 1)[1] for key in keys] == ["consent.wav", "sample-0.wav", "sample-1.wav"]
    assert all(key.startswith(f"voice/u/{USER}/{state.voice_id}/") for key in keys)
    assert all(harness.storage.objects[key].data.startswith(b"wav:") for key in keys)
    assert state.total_sample_ms == 80_000
    assert state.consent_recording is not None
    assets = harness.world.media.assets.values()
    assert {asset.kind for asset in assets} == {"voice_sample"}
    assert {asset.owner_user_id for asset in assets} == {USER}


async def test_the_consent_recording_is_validated_with_the_consent_limits(harness: Harness) -> None:
    started = await harness.clone.start(USER, VERSION, CONTEXT)

    await harness.clone.replace_consent_recording(USER, started.attempt_id, b"x")

    [(_, limits)] = harness.processor.received
    assert (limits.min_duration_ms, limits.max_duration_ms) == (3000, 30_000)
    assert limits.max_bytes == harness.settings.voices.sample_max_bytes


async def test_samples_are_validated_with_the_sample_limits(harness: Harness) -> None:
    started = await harness.clone.start(USER, VERSION, CONTEXT)

    await harness.clone.add_sample(USER, started.attempt_id, b"x")

    [(_, limits)] = harness.processor.received
    assert limits.max_duration_ms == 300_000
    assert limits.max_bytes == harness.settings.voices.sample_max_bytes


async def test_replacing_the_consent_recording_deletes_the_previous_object(harness: Harness) -> None:
    started = await harness.clone.start(USER, VERSION, CONTEXT)
    first = await harness.clone.replace_consent_recording(USER, started.attempt_id, b"first")
    second = await harness.clone.replace_consent_recording(USER, started.attempt_id, b"second")

    assert first.consent_recording is not None
    assert second.consent_recording is not None
    [data] = [stored.data for stored in harness.storage.objects.values()]
    assert data == b"wav:second"
    assert len(harness.world.media.assets) == 1


async def test_rejected_audio_maps_to_the_audio_problem_codes_and_stores_nothing(harness: Harness) -> None:
    started = await harness.clone.start(USER, VERSION, CONTEXT)
    for rejection in get_args(RejectionCode.__value__):
        harness.processor.rejection = AudioRejectedError(rejection, "rejected")
        with pytest.raises(AppError) as raised:
            await harness.clone.add_sample(USER, started.attempt_id, b"x")
        assert raised.value.code == f"audio_{rejection}"
    assert harness.storage.objects == {}


async def test_samples_beyond_the_total_maximum_and_the_file_count_are_refused(harness: Harness) -> None:
    harness.processor.seconds = 200
    started = await harness.clone.start(USER, VERSION, CONTEXT)
    await harness.clone.add_sample(USER, started.attempt_id, b"a")

    with pytest.raises(SamplesTooLongError):
        await harness.clone.add_sample(USER, started.attempt_id, b"b")

    harness.processor.seconds = 2
    for _ in range(MAX_SAMPLE_FILES - 1):
        await harness.clone.add_sample(USER, started.attempt_id, b"c")
    with pytest.raises(TooManySamplesError):
        await harness.clone.add_sample(USER, started.attempt_id, b"d")


async def test_removing_a_sample_deletes_its_object_and_unknown_ids_are_not_found(harness: Harness) -> None:
    attempt_id = await harness.prepared_attempt(samples=2)
    state = await harness.clone.state(USER, attempt_id)
    removed = state.samples[0]

    after = await harness.clone.remove_sample(USER, attempt_id, removed.id)

    assert [sample.id for sample in after.samples] == [state.samples[1].id]
    assert len(harness.storage.objects) == 2
    with pytest.raises(CloneSampleNotFoundError):
        await harness.clone.remove_sample(USER, attempt_id, removed.id)
    again = await harness.clone.add_sample(USER, attempt_id, b"n")
    assert len(again.samples) == 2


async def test_a_busy_attempt_refuses_a_second_concurrent_change(harness: Harness) -> None:
    attempt_id = await harness.prepared_attempt()

    async with harness.attempts.locked(attempt_id):
        with pytest.raises(CloneAttemptBusyError):
            await harness.clone.add_sample(USER, attempt_id, b"x")

    await harness.clone.add_sample(USER, attempt_id, b"x")


async def test_submit_requires_the_consent_recording_and_enough_sample_time(harness: Harness) -> None:
    started = await harness.clone.start(USER, VERSION, CONTEXT)
    await harness.clone.add_sample(USER, started.attempt_id, b"a")
    with pytest.raises(ConsentRecordingMissingError):
        await harness.clone.submit(USER, started.attempt_id, SUBMIT, CONTEXT)

    harness.processor.seconds = 10
    other = await harness.clone.start(USER, VERSION, CONTEXT)
    await harness.clone.replace_consent_recording(USER, other.attempt_id, b"c")
    with pytest.raises(SamplesTooShortError):
        await harness.clone.submit(USER, other.attempt_id, SUBMIT, CONTEXT)
    await harness.clone.add_sample(USER, other.attempt_id, b"a")
    await harness.clone.add_sample(USER, other.attempt_id, b"b")
    with pytest.raises(SamplesTooShortError):
        await harness.clone.submit(USER, other.attempt_id, SUBMIT, CONTEXT)
    assert harness.world.voices == {}


async def test_submit_creates_a_pending_voice_defers_the_task_and_consumes_the_attempt(harness: Harness) -> None:
    attempt_id = await harness.prepared_attempt()
    state = await harness.clone.state(USER, attempt_id)

    voice = await harness.clone.submit(USER, attempt_id, SUBMIT, CONTEXT)

    assert voice.id == state.voice_id
    assert (voice.status.value, voice.kind.value, voice.name, voice.language) == ("pending", "cloned", "My voice", "en")
    stored = harness.world.voices[voice.id]
    assert (stored.owner_user_id, stored.provider_voice_id) == (USER, None)
    assert harness.enqueued == [(voice.id, None)]
    with pytest.raises(CloneAttemptNotFoundError):
        await harness.clone.state(USER, attempt_id)
    submission = await harness.attempts.get_submission(voice.id)
    assert submission is not None
    assert submission.sample_total_ms == 40_000
    assert submission.credits_reserved == 0
    assert [event.action for event in harness.audit] == ["voices.clone_submitted"]


async def test_submit_checks_the_quota_again(harness: Harness) -> None:
    attempt_id = await harness.prepared_attempt()
    harness.runtime.max_cloned = 1
    harness.world.add_voice(owner_user_id=USER, kind="cloned", status="ready")

    with pytest.raises(VoiceQuotaExceededError):
        await harness.clone.submit(USER, attempt_id, SUBMIT, CONTEXT)

    assert harness.enqueued == []


async def test_a_clone_cost_reserves_credits_with_keys_derived_from_the_voice(harness: Harness) -> None:
    harness.runtime.cost = 40
    await harness.fund(USER, 100)
    attempt_id = await harness.prepared_attempt()

    voice = await harness.clone.submit(USER, attempt_id, SUBMIT, CONTEXT)

    [(voice_id, reservation_id)] = harness.enqueued
    assert voice_id == voice.id
    assert reservation_id is not None
    reservation = harness.credits_store.reservations[reservation_id]
    assert (reservation.amount, reservation.ref_type, reservation.ref_id) == (40, "voice_clone", voice.id)
    assert reservation.idempotency_key == f"voice-clone:{voice.id}:reserve"
    assert reservation.expires_at - harness.clock.now() == timedelta(
        seconds=harness.settings.billing.reservation_ttl_seconds
    )
    submission = await harness.attempts.get_submission(voice.id)
    assert submission is not None
    assert submission.credits_reserved == 40


async def test_insufficient_credits_fail_the_submit_and_keep_the_attempt(harness: Harness) -> None:
    harness.runtime.cost = 40
    await harness.fund(USER, 10)
    attempt_id = await harness.prepared_attempt()

    with pytest.raises(InsufficientCreditsError):
        await harness.clone.submit(USER, attempt_id, SUBMIT, CONTEXT)

    assert harness.enqueued == []
    assert harness.world.voices == {}
    assert (await harness.clone.state(USER, attempt_id)).attempt_id == attempt_id
