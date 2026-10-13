from typing import Annotated

from fastapi import Depends, Request

from motionile.core.clock import Clock
from motionile.core.config import Settings
from motionile.core.db import Database
from motionile.core.events import EventBus
from motionile.core.pagination import CursorCodec
from motionile.core.redis import RedisStore
from motionile.core.resources import Resources
from motionile.core.security.encryption import KeyRing
from motionile.core.security.rbac import Principal, principal_of
from motionile.core.storage.base import Storage


def get_resources(request: Request) -> Resources:
    resources: object = getattr(request.app.state, "resources", None)
    if not isinstance(resources, Resources):
        message = "application resources are not configured"
        raise TypeError(message)
    return resources


ResourcesDep = Annotated[Resources, Depends(get_resources)]


def get_settings_dependency(resources: ResourcesDep) -> Settings:
    return resources.settings


def get_clock(resources: ResourcesDep) -> Clock:
    return resources.clock


def get_database(resources: ResourcesDep) -> Database:
    return resources.database


def get_redis_store(resources: ResourcesDep) -> RedisStore:
    return resources.redis_store


def get_storage(resources: ResourcesDep) -> Storage:
    return resources.storage


def get_cursor_codec(resources: ResourcesDep) -> CursorCodec:
    return resources.cursor_codec


def get_key_ring(resources: ResourcesDep) -> KeyRing:
    return resources.key_ring


def get_event_bus(resources: ResourcesDep) -> EventBus:
    return resources.events


def get_principal(request: Request) -> Principal | None:
    return principal_of(request)


SettingsDep = Annotated[Settings, Depends(get_settings_dependency)]
ClockDep = Annotated[Clock, Depends(get_clock)]
DatabaseDep = Annotated[Database, Depends(get_database)]
RedisStoreDep = Annotated[RedisStore, Depends(get_redis_store)]
StorageDep = Annotated[Storage, Depends(get_storage)]
CursorCodecDep = Annotated[CursorCodec, Depends(get_cursor_codec)]
KeyRingDep = Annotated[KeyRing, Depends(get_key_ring)]
EventBusDep = Annotated[EventBus, Depends(get_event_bus)]
PrincipalDep = Annotated[Principal | None, Depends(get_principal)]
