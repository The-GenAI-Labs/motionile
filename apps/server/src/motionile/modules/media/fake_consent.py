import hashlib
from datetime import timedelta
from uuid import UUID

from motionile.core.redis import RedisStore
from motionile.core.resources import Resources
from motionile.engine.audio.providers.fake import TranscriptTextSource
from motionile.modules.media.repository import SqlAssetRepository

CONSENT_TRANSCRIPT_NAMESPACE = "media.fake_consent_transcript"
CONSENT_TRANSCRIPT_TTL = timedelta(minutes=15)


class FakeConsentTranscripts:
    def __init__(self, store: RedisStore) -> None:
        self._store = store

    def _key(self, user_id: UUID) -> str:
        return self._store.keys.key(CONSENT_TRANSCRIPT_NAMESPACE, user_id)

    async def put(self, user_id: UUID, text: str) -> None:
        await self._store.set(self._key(user_id), text, ttl=CONSENT_TRANSCRIPT_TTL)

    async def clear(self, user_id: UUID) -> None:
        await self._store.delete(self._key(user_id))

    async def get(self, user_id: UUID) -> str | None:
        stored = await self._store.get(self._key(user_id))
        return stored.decode() if stored is not None else None


def consent_text_source(resources: Resources) -> TranscriptTextSource:
    transcripts = FakeConsentTranscripts(resources.redis_store)

    async def source(audio: bytes) -> str | None:
        digest = hashlib.sha256(audio).digest()
        async with resources.database.transaction() as session:
            owners = await SqlAssetRepository(session).voice_sample_owners(digest)
        for owner in owners:
            text = await transcripts.get(owner)
            if text is not None:
                return text
        return None

    return source
