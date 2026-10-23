from pathlib import Path
from uuid import UUID

import pytest
from tests.integration.voices_support import (
    BASE,
    RUN_ATTEMPTS,
    VoicesApi,
    create_clone,
    locate_tools,
    make_audio,
)

from motionile.core.ids import new_id
from motionile.engine.ffmpeg import FfmpegTools
from motionile.modules.media import FakeConsentTranscripts
from motionile.modules.voices.factory import build_clone_runner
from motionile.modules.voices.runner import RETRYABLE_ERRORS


@pytest.fixture(scope="session")
def tools() -> FfmpegTools:
    return locate_tools()


@pytest.fixture
async def consent(tools: FfmpegTools, tmp_path: Path) -> bytes:
    return await make_audio(tools, tmp_path, "consent.wav", 5)


@pytest.fixture
async def sample(tools: FfmpegTools, tmp_path: Path) -> bytes:
    return await make_audio(tools, tmp_path, "sample.mp3", 20, "-c:a", "libmp3lame")


async def run_with_default_transcriber(api: VoicesApi, voice_id: UUID) -> dict[str, object]:
    runner = build_clone_runner(api.media.resources)
    reservation_id = dict(api.enqueued)[voice_id]
    for attempt in range(RUN_ATTEMPTS):
        try:
            await runner.run(voice_id, reservation_id)
        except RETRYABLE_ERRORS:
            if attempt == RUN_ATTEMPTS - 1:
                raise
        else:
            break
    return (await api.media.primary.get(f"{BASE}/{voice_id}")).json()


def hints_for(api: VoicesApi) -> FakeConsentTranscripts:
    return FakeConsentTranscripts(api.media.resources.redis_store)


async def test_a_hint_that_matches_the_sentence_makes_the_voice_ready(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    attempt, voice = await create_clone(voices_api, consent, sample)
    await hints_for(voices_api).put(voices_api.media.primary_id, str(attempt["consentSentence"]))

    result = await run_with_default_transcriber(voices_api, UUID(str(voice["id"])))

    assert (result["status"], result["failureCode"]) == ("ready", None)


async def test_a_hint_that_does_not_match_the_sentence_still_fails_the_consent_check(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    _, voice = await create_clone(voices_api, consent, sample)
    await hints_for(voices_api).put(voices_api.media.primary_id, "something else entirely unrelated")

    result = await run_with_default_transcriber(voices_api, UUID(str(voice["id"])))

    assert (result["status"], result["failureCode"]) == ("failed", "consent_mismatch")
    assert not voices_api.provider.cloned


async def test_without_a_hint_the_fake_transcriber_behaves_as_before(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    _, voice = await create_clone(voices_api, consent, sample)

    result = await run_with_default_transcriber(voices_api, UUID(str(voice["id"])))

    assert (result["status"], result["failureCode"]) == ("failed", "consent_mismatch")


async def test_a_hint_of_another_user_does_not_apply_to_the_recording(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    attempt, voice = await create_clone(voices_api, consent, sample)
    await hints_for(voices_api).put(new_id(), str(attempt["consentSentence"]))

    result = await run_with_default_transcriber(voices_api, UUID(str(voice["id"])))

    assert (result["status"], result["failureCode"]) == ("failed", "consent_mismatch")
