from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol
from uuid import UUID

from motionile.core.config import MediaDeliveryMode
from motionile.core.storage.base import InvalidStorageKeyError, validate_key
from motionile.modules.media.exceptions import MediaKeyNotSignableError
from motionile.modules.media.keys import MEDIA_ROOT, user_media_prefix

WILDCARD = "*"


@dataclass(frozen=True, slots=True)
class DeliveryCookie:
    name: str
    value: str
    max_age: int
    domain: str | None
    path: str = "/"
    secure: bool = True
    http_only: bool = True
    same_site: Literal["lax"] = "lax"


@dataclass(frozen=True, slots=True)
class MediaSessionGrant:
    mode: MediaDeliveryMode
    expires_at: datetime | None
    cookies: tuple[DeliveryCookie, ...] = ()


class MediaDelivery(Protocol):
    mode: MediaDeliveryMode

    def session(self, user_id: UUID) -> MediaSessionGrant: ...

    async def url_for(self, key: str, *, owner_user_id: UUID | None = None) -> str: ...

    async def signed_url(self, key: str, ttl: timedelta, *, owner_user_id: UUID | None = None) -> str: ...


def require_media_key(key: str, *, owner_user_id: UUID | None = None) -> str:
    try:
        validate_key(key)
    except InvalidStorageKeyError:
        raise MediaKeyNotSignableError from None
    if not key.startswith(f"{MEDIA_ROOT}/") or WILDCARD in key:
        raise MediaKeyNotSignableError
    if owner_user_id is not None and not key.startswith(user_media_prefix(owner_user_id)):
        raise MediaKeyNotSignableError
    return key
