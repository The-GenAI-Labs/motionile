import base64
import hashlib
import hmac
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, ValidationError
from sqlalchemy import ColumnElement, Select, tuple_

from motionile.core.errors import ValidationAppError

SIGNATURE_BYTES = 16
MAX_CURSOR_LENGTH = 512


@dataclass(frozen=True)
class Cursor:
    created_at: datetime
    id: UUID


class CursorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    t: AwareDatetime
    i: UUID


class InvalidCursorError(ValidationAppError):
    default_code = "invalid_cursor"
    title = "Invalid cursor"


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


class CursorCodec:
    def __init__(self, secret: bytes) -> None:
        if not secret:
            message = "cursor secret must not be empty"
            raise ValueError(message)
        self._secret = secret

    def _sign(self, payload: bytes) -> bytes:
        return hmac.new(self._secret, payload, hashlib.sha256).digest()[:SIGNATURE_BYTES]

    def encode(self, cursor: Cursor) -> str:
        payload = CursorPayload(t=cursor.created_at, i=cursor.id).model_dump_json().encode()
        return f"{_b64encode(payload)}.{_b64encode(self._sign(payload))}"

    def decode(self, token: str) -> Cursor:
        if len(token) > MAX_CURSOR_LENGTH or token.count(".") != 1:
            raise InvalidCursorError
        encoded_payload, encoded_signature = token.split(".")
        try:
            payload = _b64decode(encoded_payload)
            signature = _b64decode(encoded_signature)
        except ValueError as error:
            raise InvalidCursorError from error
        if not hmac.compare_digest(signature, self._sign(payload)):
            raise InvalidCursorError
        try:
            parsed = CursorPayload.model_validate_json(payload)
        except ValidationError as error:
            raise InvalidCursorError from error
        return Cursor(created_at=parsed.t, id=parsed.i)


def keyset_page[RowT](
    statement: Select[RowT],
    *,
    created_at: ColumnElement[datetime],
    id_: ColumnElement[UUID],
    cursor: Cursor | None,
    limit: int,
) -> Select[RowT]:
    if cursor is not None:
        statement = statement.where(tuple_(created_at, id_) < tuple_(cursor.created_at, cursor.id))
    return statement.order_by(created_at.desc(), id_.desc()).limit(limit + 1)


def build_page[ItemT](
    rows: Sequence[ItemT],
    *,
    limit: int,
    codec: CursorCodec,
    key: Callable[[ItemT], Cursor],
) -> tuple[list[ItemT], str | None]:
    items = list(rows[:limit])
    if len(rows) <= limit or not items:
        return items, None
    return items, codec.encode(key(items[-1]))
