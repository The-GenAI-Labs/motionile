from datetime import timedelta
from typing import Any, ClassVar
from uuid import UUID

import pytest
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped

from motionile.core.config import DatabaseSettings, RedisSettings
from motionile.core.db import (
    AFTER_COMMIT_KEY,
    NAMING_CONVENTION,
    Base,
    CreatedAtMixin,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    after_commit,
    create_engine,
    run_after_commit,
)
from motionile.core.ids import is_uuid7
from motionile.core.redis import MissingTTLError, RedisKeyBuilder, RedisStore, create_redis_client


class IsolatedBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = Base.type_annotation_map


class Widget(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, IsolatedBase):
    __tablename__ = "widgets_for_tests"

    name: Mapped[str]
    payload: Mapped[bytes]


class Entry(UUIDPrimaryKeyMixin, CreatedAtMixin, IsolatedBase):
    __tablename__ = "entries_for_tests"


def test_metadata_uses_naming_convention() -> None:
    assert dict(Base.metadata.naming_convention) | NAMING_CONVENTION == dict(Base.metadata.naming_convention)


def test_mixins_define_standard_columns() -> None:
    columns = Widget.__table__.c

    assert columns.id.primary_key
    assert columns.created_at.server_default is not None
    assert columns.updated_at.onupdate is not None
    assert columns.deleted_at.nullable
    assert str(columns.name.type) == "TEXT"
    assert columns.payload.type.python_type is bytes
    assert "updated_at" not in Entry.__table__.c


def test_primary_key_default_generates_uuid7() -> None:
    default = Widget.__table__.c.id.default
    assert default is not None
    generated = default.arg(None)

    assert isinstance(generated, UUID)
    assert is_uuid7(generated)


def test_create_engine_applies_pool_and_driver_settings() -> None:
    settings = DatabaseSettings(url="postgresql://u:p@db.example/app", pool_size=3, statement_cache_size=0)

    engine = create_engine(settings, application_name="motionile-test")

    assert engine.url.drivername == "postgresql+asyncpg"
    assert "Pool size: 3" in engine.pool.status()


def test_create_engine_uses_direct_url_when_asked() -> None:
    settings = DatabaseSettings(url="postgresql://pooled/app", direct_url="postgresql://direct/app")

    assert create_engine(settings, application_name="x", direct=True).url.host == "direct"


class FakeSession:
    def __init__(self) -> None:
        self.info: dict[str, object] = {}


async def test_after_commit_callbacks_run_in_order_and_isolate_failures() -> None:
    session = FakeSession()
    calls: list[str] = []

    async def first() -> None:
        calls.append("first")

    async def failing() -> None:
        calls.append("failing")
        message = "boom"
        raise RuntimeError(message)

    async def last() -> None:
        calls.append("last")

    for callback in (first, failing, last):
        after_commit(session, callback)  # type: ignore[arg-type]
    await run_after_commit(session)  # type: ignore[arg-type]

    assert calls == ["first", "failing", "last"]
    assert AFTER_COMMIT_KEY not in session.info


def test_redis_key_builder_requires_namespace_and_parts() -> None:
    keys = RedisKeyBuilder("mo")

    assert keys.key("ratelimit.auth", "abc", 1) == "mo:ratelimit.auth:abc:1"
    with pytest.raises(ValueError, match="namespace"):
        keys.key("Bad Namespace", "x")
    with pytest.raises(ValueError, match="at least one part"):
        keys.key("otp")
    with pytest.raises(ValueError, match="part"):
        keys.key("otp", "has space")


class RecordingRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    async def set(self, *args: object, **kwargs: object) -> bool:
        self.calls.append(("set", args, kwargs))
        return True


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(seconds=-1)])
async def test_redis_store_rejects_writes_without_ttl(ttl: timedelta) -> None:
    store = RedisStore(RecordingRedis(), RedisKeyBuilder("mo"))  # type: ignore[arg-type]

    with pytest.raises(MissingTTLError):
        await store.set("mo:x:y", "v", ttl=ttl)
    with pytest.raises(MissingTTLError):
        await store.set_if_absent("mo:x:y", "v", ttl=ttl)
    with pytest.raises(MissingTTLError):
        await store.increment("mo:x:y", ttl=ttl)


async def test_redis_store_passes_ttl_in_milliseconds() -> None:
    redis = RecordingRedis()
    store = RedisStore(redis, RedisKeyBuilder("mo"))  # type: ignore[arg-type]

    await store.set("mo:x:y", "v", ttl=timedelta(seconds=2))
    assert await store.set_if_absent("mo:x:y", "v", ttl=timedelta(milliseconds=1500))

    assert redis.calls[0][2] == {"px": 2000}
    assert redis.calls[1][2] == {"px": 1500, "nx": True}


def test_create_redis_client_parses_url() -> None:
    client = create_redis_client(RedisSettings(url="rediss://user:p%40ss@cache.internal:6380/2"))
    options = client.connection_pool.connection_kwargs

    assert options["host"] == "cache.internal"
    assert options["port"] == 6380
    assert options["db"] == 2
    assert options["username"] == "user"
    assert options["password"] == "p@ss"  # noqa: S105
