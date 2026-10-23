import asyncio
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.voices_support import VoicesApi, create_clone, locate_tools, make_audio

from motionile.engine.audio.providers.fake import FakeTranscriptMode
from motionile.engine.ffmpeg import FfmpegTools
from motionile.modules.credits import CommitResult, CreditsService
from motionile.modules.users import purge_registry
from motionile.modules.voices.domain import STALLED_CLONE_AGE
from motionile.modules.voices.factory import build_clone_runner, build_maintenance
from motionile.modules.voices.models import VoiceConsent
from motionile.modules.voices.repository import NewConsent, SqlVoiceRepository

COST = 40
FUNDS = 100
PAUSE_SECONDS = 0.5
WALLET = "SELECT balance, reserved FROM credit_wallets WHERE user_id = :u"
REASONS = "SELECT reason FROM credit_ledger WHERE user_id = :u ORDER BY created_at, id"


@pytest.fixture(scope="session")
def tools() -> FfmpegTools:
    return locate_tools()


@pytest.fixture
async def consent(tools: FfmpegTools, tmp_path: Path) -> bytes:
    return await make_audio(tools, tmp_path, "consent.wav", 5)


@pytest.fixture
async def sample(tools: FfmpegTools, tmp_path: Path) -> bytes:
    return await make_audio(tools, tmp_path, "sample.mp3", 20, "-c:a", "libmp3lame")


async def priced_clone(api: VoicesApi, consent: bytes, sample: bytes) -> tuple[UUID, UUID, str]:
    await api.set_setting("voices.clone_credit_cost", COST)
    await api.fund(api.media.primary_id, FUNDS)
    attempt, voice = await create_clone(api, consent, sample)
    voice_id = UUID(str(voice["id"]))
    reservation_id = dict(api.enqueued)[voice_id]
    assert reservation_id is not None
    return voice_id, reservation_id, str(attempt["consentSentence"])


async def wallet(api: VoicesApi) -> list[tuple[int, int]]:
    rows = await api.rows(WALLET, u=api.media.primary_id)
    return [(row[0], row[1]) for row in rows]


async def reasons(api: VoicesApi) -> list[str]:
    return [row[0] for row in await api.rows(REASONS, u=api.media.primary_id)]


async def age_clone(api: VoicesApi, voice_id: UUID) -> None:
    async with api.database.transaction() as session:
        await session.execute(
            text("UPDATE voices SET created_at = created_at - make_interval(secs => :seconds) WHERE id = :id"),
            {"seconds": (STALLED_CLONE_AGE + timedelta(hours=1)).total_seconds(), "id": voice_id},
        )


async def test_a_reservation_settled_before_the_commit_fails_the_clone_and_charges_nothing(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    voice_id, reservation_id, sentence = await priced_clone(voices_api, consent, sample)
    resources = voices_api.media.resources
    async with voices_api.database.transaction() as session:
        await CreditsService(resources.clock, resources.settings.billing).release(
            session, reservation_id, "test-early-release"
        )

    await voices_api.run_clone(voice_id, sentence=sentence)

    [row] = await voices_api.rows(
        "SELECT status, failure_code, provider_voice_id FROM voices WHERE id = :id", id=voice_id
    )
    assert tuple(row) == ("failed", "credit_reservation_expired", None)
    assert await wallet(voices_api) == [(FUNDS, 0)]
    assert await reasons(voices_api) == ["purchase", "reserve", "release"]
    assert voices_api.provider.cloned == {}
    assert await voices_api.scalar("SELECT count(*) FROM voice_consents") == 0


async def test_a_reservation_that_outlived_its_ttl_in_the_sweeper_fails_the_clone_without_a_charge(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    voice_id, reservation_id, sentence = await priced_clone(voices_api, consent, sample)
    resources = voices_api.media.resources
    async with voices_api.database.transaction() as session:
        await session.execute(text("UPDATE credit_reservations SET expires_at = now() - interval '1 minute'"))
    async with voices_api.database.transaction() as session:
        released = await CreditsService(resources.clock, resources.settings.billing).release_stale(
            session, reservation_id
        )
    assert released is not None

    await voices_api.run_clone(voice_id, sentence=sentence)

    assert await voices_api.scalar("SELECT failure_code FROM voices WHERE id = :id", id=voice_id) == (
        "credit_reservation_expired"
    )
    assert await wallet(voices_api) == [(FUNDS, 0)]
    assert "commit" not in await reasons(voices_api)


async def test_the_stall_sweeper_releases_the_reservation_of_a_stalled_clone(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    voice_id, _, sentence = await priced_clone(voices_api, consent, sample)
    await age_clone(voices_api, voice_id)
    maintenance = build_maintenance(voices_api.media.resources)

    assert await maintenance.fail_stalled_clones(STALLED_CLONE_AGE) == 1
    assert await maintenance.fail_stalled_clones(STALLED_CLONE_AGE) == 0
    await voices_api.run_clone(voice_id, sentence=sentence)

    assert await voices_api.scalar("SELECT failure_code FROM voices WHERE id = :id", id=voice_id) == "clone_stalled"
    assert await wallet(voices_api) == [(FUNDS, 0)]
    assert await reasons(voices_api) == ["purchase", "reserve", "release"]


async def test_the_account_purge_releases_the_reservation_of_a_pending_clone(
    voices_api: VoicesApi, consent: bytes, sample: bytes
) -> None:
    await priced_clone(voices_api, consent, sample)
    assert await wallet(voices_api) == [(FUNDS, COST)]

    async with voices_api.database.transaction() as session:
        await purge_registry.run(voices_api.media.resources, session, voices_api.media.primary_id)

    assert await wallet(voices_api) == [(FUNDS, 0)]
    assert await reasons(voices_api) == ["purchase", "reserve", "release"]


async def test_finalization_that_commits_first_keeps_the_charge_and_the_sweeper_does_nothing(
    voices_api: VoicesApi, consent: bytes, sample: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    voice_id, reservation_id, sentence = await priced_clone(voices_api, consent, sample)
    await age_clone(voices_api, voice_id)
    committed = asyncio.Event()
    proceed = asyncio.Event()
    original = CreditsService.commit

    async def held_commit(
        self: CreditsService, session: AsyncSession, reservation_id: UUID, actual: int, key: str
    ) -> CommitResult:
        result = await original(self, session, reservation_id, actual, key)
        committed.set()
        await proceed.wait()
        return result

    monkeypatch.setattr(CreditsService, "commit", held_commit)
    voices_api.transcriber.fixed_text = sentence
    voices_api.transcriber.mode = FakeTranscriptMode.FIXED
    runner = build_clone_runner(voices_api.media.resources, voices_api.transcriber)
    finalizer = asyncio.create_task(runner.run(voice_id, reservation_id))
    await asyncio.wait_for(committed.wait(), timeout=60)

    sweeper = asyncio.create_task(build_maintenance(voices_api.media.resources).fail_stalled_clones(timedelta(0)))
    await asyncio.sleep(PAUSE_SECONDS)
    assert not sweeper.done()
    proceed.set()
    await asyncio.gather(finalizer, sweeper)

    assert await voices_api.scalar("SELECT status FROM voices WHERE id = :id", id=voice_id) == "ready"
    assert await wallet(voices_api) == [(FUNDS - COST, 0)]
    assert await reasons(voices_api) == ["purchase", "reserve", "commit"]
    assert len(voices_api.provider.cloned) == 1


async def test_a_sweeper_that_commits_first_wins_and_finalization_neither_charges_nor_readies(
    voices_api: VoicesApi, consent: bytes, sample: bytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    voice_id, reservation_id, sentence = await priced_clone(voices_api, consent, sample)
    await age_clone(voices_api, voice_id)
    reached = asyncio.Event()
    resume = asyncio.Event()
    original = SqlVoiceRepository.insert_consent

    async def paused_insert(self: SqlVoiceRepository, row: NewConsent) -> VoiceConsent:
        reached.set()
        await resume.wait()
        return await original(self, row)

    monkeypatch.setattr(SqlVoiceRepository, "insert_consent", paused_insert)
    voices_api.transcriber.mode = FakeTranscriptMode.FIXED
    voices_api.transcriber.fixed_text = sentence
    runner = build_clone_runner(voices_api.media.resources, voices_api.transcriber)
    finalizer = asyncio.create_task(runner.run(voice_id, reservation_id))
    await asyncio.wait_for(reached.wait(), timeout=60)

    swept = await build_maintenance(voices_api.media.resources).fail_stalled_clones(timedelta(0))
    resume.set()
    await finalizer

    assert swept == 1
    assert await voices_api.scalar("SELECT failure_code FROM voices WHERE id = :id", id=voice_id) == "clone_stalled"
    assert await wallet(voices_api) == [(FUNDS, 0)]
    assert await reasons(voices_api) == ["purchase", "reserve", "release"]
    assert await voices_api.scalar("SELECT count(*) FROM voice_consents") == 0
    assert voices_api.provider.cloned == {}
