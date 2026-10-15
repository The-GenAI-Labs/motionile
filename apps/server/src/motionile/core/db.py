import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

import structlog
from sqlalchemy import DateTime, LargeBinary, MetaData, Text, func, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from motionile.core.config import DatabaseSettings
from motionile.core.ids import new_id

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
AFTER_COMMIT_KEY = "motionile.after_commit"

type AfterCommitCallback = Callable[[], Awaitable[None]]

logger = structlog.get_logger(__name__)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        datetime: DateTime(timezone=True),
        str: Text(),
        bytes: LargeBinary(),
    }


class UUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(default=None)


def create_engine(settings: DatabaseSettings, *, application_name: str, direct: bool = False) -> AsyncEngine:
    return create_async_engine(
        settings.direct_async_url if direct else settings.async_url,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_timeout=settings.pool_timeout_seconds,
        pool_recycle=settings.pool_recycle_seconds,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={
            "timeout": settings.connect_timeout_seconds,
            "statement_cache_size": settings.statement_cache_size,
            "server_settings": {"application_name": application_name, "timezone": "UTC"},
        },
    )


def after_commit(session: AsyncSession, callback: AfterCommitCallback) -> None:
    callbacks: list[AfterCommitCallback] = session.info.setdefault(AFTER_COMMIT_KEY, [])
    callbacks.append(callback)


async def run_after_commit(session: AsyncSession) -> None:
    callbacks: list[AfterCommitCallback] = session.info.pop(AFTER_COMMIT_KEY, [])
    for callback in callbacks:
        try:
            await callback()
        except Exception:
            logger.exception("db.after_commit_failed")


class Database:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)

    def session(self) -> AsyncSession:
        return self._sessions()

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        async with self._sessions() as session:
            async with session.begin():
                yield session
            await run_after_commit(session)

    async def ping(self, timeout_seconds: float) -> None:
        async with asyncio.timeout(timeout_seconds), self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()
