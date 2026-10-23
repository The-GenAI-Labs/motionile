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

    async def url_for(self, key: str, *, owner_user_id: UUID | None = None) -> str:
        return await self._storage.presigned_get_url(
            require_media_key(key, owner_user_id=owner_user_id), expires_in=self._ttl
        )

    async def signed_url(self, key: str, ttl: timedelta, *, owner_user_id: UUID | None = None) -> str:
        return await self._storage.presigned_get_url(
            require_media_key(key, owner_user_id=owner_user_id), expires_in=ttl
        )
