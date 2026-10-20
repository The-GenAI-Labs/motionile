from datetime import timedelta
from uuid import UUID

from motionile.core.config import MediaDeliveryMode
from motionile.core.storage.base import Storage
from motionile.modules.media.delivery.base import MediaSessionGrant, require_media_key


class PresignedDelivery:
    mode = MediaDeliveryMode.PRESIGNED

    def __init__(self, storage: Storage, ttl: timedelta) -> None:
        self._storage = storage
        self._ttl = ttl

    def session(self, user_id: UUID) -> MediaSessionGrant:
        del user_id
        return MediaSessionGrant(self.mode, None)

    async def url_for(self, key: str) -> str:
        return await self._storage.presigned_get_url(require_media_key(key), expires_in=self._ttl)

    async def signed_url(self, key: str, ttl: timedelta) -> str:
        return await self._storage.presigned_get_url(require_media_key(key), expires_in=ttl)
