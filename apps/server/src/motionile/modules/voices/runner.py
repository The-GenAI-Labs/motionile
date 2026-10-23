from collections.abc import Callable
from uuid import UUID

import structlog
from botocore.exceptions import BotoCoreError, ClientError
from redis.exceptions import RedisError
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.alerts import raise_alert
from motionile.core.clock import Clock
from motionile.core.config import VoicesSettings
from motionile.core.db import after_commit
from motionile.core.storage.base import ObjectNotFoundError
from motionile.engine.audio.models import CloneSample, Transcript
from motionile.engine.audio.providers.base import (
    ProviderError,
    ProviderRateLimitedError,
    ProviderRejectedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    Transcriber,
    VoiceCloner,
)
from motionile.engine.audio.voice_clone import ConsentVerdict, evaluate_consent
from motionile.modules.credits import CreditsService, ReservationNotActiveError, ReservationNotFoundError
from motionile.modules.media import (
    AssetNotFoundError,
    AssetService,
    AssetView,
    SpeechService,
    voice_prefix,
)
from motionile.modules.voices.clone import AttemptStore, CloneSubmission
from motionile.modules.voices.domain import VoiceFailureCode, VoiceKind, VoiceStatus
from motionile.modules.voices.models import Voice
from motionile.modules.voices.ports import Transaction
from motionile.modules.voices.preview import PreviewGenerator, delete_provider_voice
from motionile.modules.voices.repository import NewConsent, StoreFactory
from motionile.modules.voices.reservations import commit_key, release_clone_reservation

logger = structlog.get_logger(__name__)

RETRYABLE_ERRORS: tuple[type[Exception], ...] = (
    ProviderUnavailableError,
    ProviderTimeoutError,
    ProviderRateLimitedError,
    BotoCoreError,
    ClientError,
    OSError,
    OperationalError,
    InterfaceError,
    RedisError,
)
MAX_TRANSCRIPT_CHARACTERS = 600
PERCENT = 100
PREVIEW_PREFIX_ROOT = "voice-preview"


class CloneRejectedError(Exception):
    def __init__(self, code: VoiceFailureCode) -> None:
        super().__init__(code.value)
        self.code = code


class CloneRunner:
    def __init__(  # noqa: PLR0913
        self,
        *,
        transaction: Transaction,
        store_factory: StoreFactory,
        assets: AssetService,
        attempts: AttemptStore,
        speech: SpeechService,
        previews: PreviewGenerator,
        transcriber: Callable[[], Transcriber],
        cloner: Callable[[], VoiceCloner],
        credit_service: CreditsService,
        settings: VoicesSettings,
        clock: Clock,
    ) -> None:
        self._transaction = transaction
        self._store_factory = store_factory
        self._assets = assets
        self._attempts = attempts
        self._speech = speech
        self._previews = previews
        self._transcriber = transcriber
        self._cloner = cloner
        self._credits = credit_service
        self._settings = settings
        self._clock = clock

    async def run(self, voice_id: UUID, reservation_id: UUID | None) -> None:
        async with self._transaction() as session:
            voice = await self._store_factory(session).get(voice_id)
        if (
            voice is None
            or voice.status != VoiceStatus.PENDING.value
            or voice.kind != VoiceKind.CLONED.value
            or voice.owner_user_id is None
        ):
            return
        submission = await self._attempts.get_submission(voice_id)
        if submission is None:
            await self.fail(voice_id, VoiceFailureCode.ATTEMPT_EXPIRED)
            return
        try:
            await self._execute(voice, voice.owner_user_id, submission, reservation_id)
        except CloneRejectedError as rejected:
            await self.fail(voice_id, rejected.code)
        except RETRYABLE_ERRORS:
            raise
        except Exception:
            logger.exception("voices.clone_crashed", voice_id=str(voice_id))
            await self.fail(voice_id, VoiceFailureCode.PROVIDER_FAILED)

    async def fail(self, voice_id: UUID, code: VoiceFailureCode) -> None:
        async with self._transaction() as session:
            voice = await self._store_factory(session).get(voice_id)
        if voice is None or voice.owner_user_id is None or voice.kind != VoiceKind.CLONED.value:
            return
        user_id = voice.owner_user_id
        provider_voice_id = voice.provider_voice_id
        if voice.status == VoiceStatus.FAILED.value:
            async with self._transaction() as session:
                await self._release(session, user_id, voice_id)
            return
        if voice.status != VoiceStatus.PENDING.value:
            return
        async with self._transaction() as session:
            if not await self._store_factory(session).mark_failed(voice_id, code.value):
                return
            await self._assets.delete_by_prefix(session, user_id, voice_prefix(user_id, voice_id))
            await self._assets.delete_by_prefix(session, None, f"{PREVIEW_PREFIX_ROOT}/{voice_id}.")
            await self._release(session, user_id, voice_id)
            after_commit(session, lambda: self._attempts.delete_submission(voice_id))
        logger.info("voices.clone_failed", voice_id=str(voice_id), failure_code=code.value)
        if provider_voice_id is not None:
            await self._remove_provider_voice(voice, provider_voice_id)

    async def _execute(
        self, voice: Voice, user_id: UUID, submission: CloneSubmission, reservation_id: UUID | None
    ) -> None:
        transcript = await self._transcribe(user_id, submission, voice.language)
        verdict = evaluate_consent(submission.sentence, transcript.text, self._settings.consent_match_threshold)
        if not verdict.matched:
            raise CloneRejectedError(VoiceFailureCode.CONSENT_MISMATCH)
        provider_voice_id = voice.provider_voice_id or await self._create_at_provider(voice, user_id, submission)
        try:
            preview = await self._previews.generate(
                voice.id, voice.provider, provider_voice_id, voice.language, user_id=user_id
            )
        except ProviderError as error:
            if error.retryable:
                raise
            raise CloneRejectedError(VoiceFailureCode.PREVIEW_FAILED) from error
        await self._finalize(
            voice=voice,
            user_id=user_id,
            submission=submission,
            transcript=transcript,
            verdict=verdict,
            preview=preview,
            reservation_id=reservation_id,
        )

    async def _transcribe(self, user_id: UUID, submission: CloneSubmission, language: str) -> Transcript:
        consent = await self._read(user_id, submission.consent_asset_id)
        try:
            return await self._transcriber().transcribe(consent, "consent.wav", language)
        except ProviderError as error:
            if error.retryable:
                raise
            raise CloneRejectedError(VoiceFailureCode.TRANSCRIPTION_FAILED) from error

    async def _create_at_provider(self, voice: Voice, user_id: UUID, submission: CloneSubmission) -> str:
        samples = [
            CloneSample(f"sample-{index}.wav", await self._read(user_id, asset_id))
            for index, asset_id in enumerate(submission.sample_asset_ids)
        ]
        try:
            provider_voice_id = await self._cloner().clone(voice.name, voice.language, samples, None)
        except ProviderRejectedError as error:
            raise CloneRejectedError(VoiceFailureCode.SAMPLE_INVALID) from error
        except ProviderError as error:
            if error.retryable:
                raise
            raise CloneRejectedError(VoiceFailureCode.PROVIDER_FAILED) from error
        async with self._transaction() as session:
            recorded = await self._store_factory(session).set_provider_voice_id(voice.id, provider_voice_id)
        if not recorded:
            await self._delete_at_provider_id(voice, provider_voice_id)
            raise CloneRejectedError(VoiceFailureCode.PROVIDER_FAILED)
        return provider_voice_id

    async def _read(self, user_id: UUID, asset_id: UUID) -> bytes:
        try:
            async with self._transaction() as session:
                asset = await self._assets.get(session, user_id, asset_id)
            return await self._assets.read_bytes(asset)
        except (AssetNotFoundError, ObjectNotFoundError) as error:
            raise CloneRejectedError(VoiceFailureCode.SAMPLE_INVALID) from error

    async def _finalize(  # noqa: PLR0913
        self,
        *,
        voice: Voice,
        user_id: UUID,
        submission: CloneSubmission,
        transcript: Transcript,
        verdict: ConsentVerdict,
        preview: AssetView,
        reservation_id: UUID | None,
    ) -> None:
        async with self._transaction() as session:
            store = self._store_factory(session)
            await store.insert_consent(
                NewConsent(
                    voice_id=voice.id,
                    user_id=user_id,
                    statement_version=submission.statement_version,
                    statement_sha256=bytes.fromhex(submission.statement_sha256),
                    accepted_at=submission.accepted_at,
                    ip=submission.ip,
                    user_agent=submission.user_agent,
                    consent_asset_id=submission.consent_asset_id,
                    challenge_sentence=submission.sentence,
                    transcript=transcript.text[:MAX_TRANSCRIPT_CHARACTERS],
                    match_percent=min(PERCENT, max(0, round(verdict.similarity * PERCENT))),
                    sample_count=len(submission.sample_asset_ids),
                    sample_total_ms=submission.sample_total_ms,
                )
            )
            if not await store.mark_ready(voice.id, preview.id):
                raise CloneRejectedError(VoiceFailureCode.PROVIDER_FAILED)
            await self._commit_credits(session, voice.id, reservation_id, submission.credits_reserved)
            after_commit(session, lambda: self._attempts.delete_submission(voice.id))
        logger.info("voices.clone_ready", voice_id=str(voice.id))

    async def _commit_credits(
        self, session: AsyncSession, voice_id: UUID, reservation_id: UUID | None, amount: int
    ) -> None:
        if amount <= 0:
            return
        try:
            if reservation_id is None:
                raise ReservationNotFoundError
            await self._credits.commit(session, reservation_id, amount, commit_key(voice_id))
        except (ReservationNotActiveError, ReservationNotFoundError) as error:
            raise_alert(
                "voice_clone_credit_commit_failed",
                voice_id=str(voice_id),
                reservation_id=str(reservation_id) if reservation_id is not None else None,
            )
            raise CloneRejectedError(VoiceFailureCode.CREDIT_RESERVATION_EXPIRED) from error

    async def _release(self, session: AsyncSession, user_id: UUID, voice_id: UUID) -> None:
        if not await release_clone_reservation(self._credits, session, user_id, voice_id):
            logger.info("voices.no_active_reservation", voice_id=str(voice_id))

    async def _remove_provider_voice(self, voice: Voice, provider_voice_id: str) -> None:
        try:
            await self._speech.delete_cache_for_voice(voice.provider, provider_voice_id)
        except Exception:
            logger.exception("voices.cache_delete_failed", voice_id=str(voice.id))
        await self._delete_at_provider_id(voice, provider_voice_id)

    async def _delete_at_provider_id(self, voice: Voice, provider_voice_id: str) -> None:
        try:
            await delete_provider_voice(self._cloner(), provider_voice_id)
        except Exception:
            logger.exception("voices.provider_delete_failed", voice_id=str(voice.id))
            raise_alert(
                "voice_provider_delete_failed",
                provider=voice.provider,
                provider_voice_id=provider_voice_id,
                voice_id=str(voice.id),
            )
