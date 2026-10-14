import hashlib
import math
import re
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import orjson
from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import CheckConstraint, Index, SmallInteger, UniqueConstraint, delete, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from motionile.core.clock import Clock
from motionile.core.db import Base, Database, TimestampMixin, UUIDPrimaryKeyMixin
from motionile.core.errors import BadRequestError, ConflictError
from motionile.core.ids import new_id
from motionile.core.security.rbac import principal_of

IDEMPOTENCY_HEADER = "Idempotency-Key"
REPLAYED_HEADER = "Idempotent-Replayed"
KEY_PATTERN = re.compile(r"^[\x21-\x7E]{1,255}$")
REPLAYABLE_HEADERS = frozenset({"location", "content-location", "etag"})
UNIQUE_CONSTRAINT = "uq_idempotency_records_scope_user_id_key"


class IdempotencyRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("scope", "user_id", "key", name=UNIQUE_CONSTRAINT, postgresql_nulls_not_distinct=True),
        CheckConstraint("status IN ('in_progress', 'completed')", name="status"),
        CheckConstraint("char_length(scope) BETWEEN 1 AND 100", name="scope_length"),
        CheckConstraint("key ~ '^[\\x21-\\x7E]{1,255}$'", name="key_format"),
        CheckConstraint("octet_length(request_hash) = 32", name="request_hash_length"),
        CheckConstraint("response_status IS NULL OR response_status BETWEEN 100 AND 599", name="response_status_range"),
        CheckConstraint("status <> 'completed' OR response_status IS NOT NULL", name="completed_has_response"),
        CheckConstraint("status <> 'in_progress' OR locked_until IS NOT NULL", name="in_progress_has_lock"),
        Index("ix_idempotency_records_user_id", "user_id"),
        Index("ix_idempotency_records_expires_at", "expires_at"),
    )

    scope: Mapped[str]
    user_id: Mapped[UUID | None]
    key: Mapped[str]
    request_hash: Mapped[bytes]
    status: Mapped[str] = mapped_column(server_default="in_progress")
    response_status: Mapped[int | None] = mapped_column(SmallInteger)
    response_body: Mapped[Any | None] = mapped_column(JSONB)
    response_headers: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    locked_until: Mapped[datetime | None]
    expires_at: Mapped[datetime]


@dataclass(frozen=True)
class IdempotencyScope:
    scope: str
    user_id: UUID | None
    key: str


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    body: Any
    headers: dict[str, str]


class IdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim(
        self,
        target: IdempotencyScope,
        *,
        request_hash: bytes,
        now: datetime,
        locked_until: datetime,
        expires_at: datetime,
    ) -> UUID | None:
        table = IdempotencyRecord.__table__
        statement = (
            insert(IdempotencyRecord)
            .values(
                id=new_id(),
                scope=target.scope,
                user_id=target.user_id,
                key=target.key,
                request_hash=request_hash,
                status="in_progress",
                locked_until=locked_until,
                expires_at=expires_at,
            )
            .on_conflict_do_update(
                constraint=UNIQUE_CONSTRAINT,
                set_={
                    "request_hash": request_hash,
                    "status": "in_progress",
                    "response_status": None,
                    "response_body": None,
                    "response_headers": None,
                    "locked_until": locked_until,
                    "expires_at": expires_at,
                    "updated_at": now,
                },
                where=(table.c.expires_at <= now)
                | (
                    (table.c.status == "in_progress")
                    & (table.c.locked_until <= now)
                    & (table.c.request_hash == request_hash)
                ),
            )
            .returning(IdempotencyRecord.id)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def find(self, target: IdempotencyScope) -> IdempotencyRecord | None:
        statement = select(IdempotencyRecord).where(
            IdempotencyRecord.scope == target.scope,
            IdempotencyRecord.user_id.is_not_distinct_from(target.user_id),
            IdempotencyRecord.key == target.key,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def complete(self, record_id: UUID, response: StoredResponse, *, now: datetime) -> None:
        await self.session.execute(
            update(IdempotencyRecord)
            .where(IdempotencyRecord.id == record_id, IdempotencyRecord.status == "in_progress")
            .values(
                status="completed",
                response_status=response.status_code,
                response_body=response.body,
                response_headers=response.headers,
                locked_until=None,
                updated_at=now,
            )
        )

    async def release(self, record_id: UUID) -> None:
        await self.session.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.id == record_id, IdempotencyRecord.status == "in_progress"
            )
        )


class IdempotencyKeyRequiredError(BadRequestError):
    default_code = "idempotency_key_required"
    title = "Idempotency key required"


class IdempotencyKeyInvalidError(BadRequestError):
    default_code = "idempotency_key_invalid"
    title = "Invalid idempotency key"


class IdempotencyKeyReusedError(ConflictError):
    default_code = "idempotency_key_reused"
    title = "Idempotency key reused"


class IdempotencyInProgressError(ConflictError):
    default_code = "idempotency_request_in_progress"
    title = "Request already in progress"


class IdempotentReplay(Exception):  # noqa: N818
    def __init__(self, response: StoredResponse) -> None:
        super().__init__("idempotent replay")
        self.response = response


@dataclass(frozen=True)
class Claimed:
    record_id: UUID


@dataclass(frozen=True)
class Replay:
    response: StoredResponse


type BeginOutcome = Claimed | Replay


def canonical_body(body: bytes) -> bytes:
    if not body:
        return b""
    try:
        parsed: object = orjson.loads(body)
    except orjson.JSONDecodeError:
        return body
    return orjson.dumps(parsed, option=orjson.OPT_SORT_KEYS)


def request_fingerprint(method: str, path: str, body: bytes) -> bytes:
    digest = hashlib.sha256()
    digest.update(method.upper().encode())
    digest.update(b"\n")
    digest.update(path.encode())
    digest.update(b"\n")
    digest.update(canonical_body(body))
    return digest.digest()


@dataclass
class IdempotencyService:
    database: Database
    clock: Clock
    ttl: timedelta
    lock_duration: timedelta

    async def begin(self, target: IdempotencyScope, request_hash: bytes) -> BeginOutcome:
        now = self.clock.now()
        async with self.database.transaction() as session:
            repository = IdempotencyRepository(session)
            record_id = await repository.claim(
                target,
                request_hash=request_hash,
                now=now,
                locked_until=now + self.lock_duration,
                expires_at=now + self.ttl,
            )
            if record_id is not None:
                return Claimed(record_id)
            existing = await repository.find(target)
        if existing is None:
            message = "idempotency record vanished during claim"
            raise IdempotencyInProgressError(message, headers={"Retry-After": "1"})
        if existing.request_hash != request_hash:
            message = "This Idempotency-Key was already used with a different request."
            raise IdempotencyKeyReusedError(message)
        if existing.status == "completed" and existing.response_status is not None:
            return Replay(
                StoredResponse(existing.response_status, existing.response_body, dict(existing.response_headers or {}))
            )
        locked_until = existing.locked_until or now
        retry_after = max(1, math.ceil((locked_until - now).total_seconds()))
        message = "A request with this Idempotency-Key is still being processed."
        raise IdempotencyInProgressError(message, headers={"Retry-After": str(retry_after)})

    async def complete(self, record_id: UUID, response: StoredResponse) -> None:
        async with self.database.transaction() as session:
            await IdempotencyRepository(session).complete(record_id, response, now=self.clock.now())

    async def release(self, record_id: UUID) -> None:
        async with self.database.transaction() as session:
            await IdempotencyRepository(session).release(record_id)


@dataclass
class IdempotencyGuard:
    service: IdempotencyService
    record_id: UUID
    completed: bool = field(default=False)

    async def respond(
        self,
        content: object,
        *,
        status_code: int = 200,
        headers: Mapping[str, str] | None = None,
    ) -> JSONResponse:
        body = jsonable_encoder(content, by_alias=True)
        replayable = {name: value for name, value in (headers or {}).items() if name.lower() in REPLAYABLE_HEADERS}
        await self.service.complete(self.record_id, StoredResponse(status_code, body, replayable))
        self.completed = True
        return JSONResponse(body, status_code=status_code, headers=dict(headers or {}))


def replay_response(response: StoredResponse) -> JSONResponse:
    return JSONResponse(
        response.body,
        status_code=response.status_code,
        headers={**response.headers, REPLAYED_HEADER: "true"},
    )


async def handle_idempotent_replay(_: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, IdempotentReplay):
        raise error
    return replay_response(error.response)


def idempotency_service_of(request: Request) -> IdempotencyService:
    resources: object = getattr(request.app.state, "resources", None)
    service: object = getattr(resources, "idempotency", None)
    if not isinstance(service, IdempotencyService):
        message = "the idempotency service is not configured on the application"
        raise TypeError(message)
    return service


def read_key(request: Request) -> str:
    key = request.headers.get(IDEMPOTENCY_HEADER)
    if key is None:
        message = f"Send an {IDEMPOTENCY_HEADER} header with a unique value for this operation."
        raise IdempotencyKeyRequiredError(message)
    if not KEY_PATTERN.match(key):
        message = f"{IDEMPOTENCY_HEADER} must be 1 to 255 visible ASCII characters."
        raise IdempotencyKeyInvalidError(message)
    return key


def idempotent(scope: str) -> Callable[[Request], AsyncIterator[IdempotencyGuard]]:
    async def guard_request(request: Request) -> AsyncIterator[IdempotencyGuard]:
        key = read_key(request)
        principal = principal_of(request)
        target = IdempotencyScope(scope=scope, user_id=principal.user_id if principal else None, key=key)
        fingerprint = request_fingerprint(request.method, request.url.path, await request.body())
        service = idempotency_service_of(request)
        outcome = await service.begin(target, fingerprint)
        if isinstance(outcome, Replay):
            raise IdempotentReplay(outcome.response)
        guard = IdempotencyGuard(service=service, record_id=outcome.record_id)
        try:
            yield guard
        except BaseException:
            if not guard.completed:
                await service.release(outcome.record_id)
            raise
        if not guard.completed:
            await service.release(outcome.record_id)

    return guard_request
