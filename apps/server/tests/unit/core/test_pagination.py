import base64
import hashlib
import hmac
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import Column, DateTime, MetaData, Table, Uuid, select
from sqlalchemy.dialects import postgresql

from motionile.core.pagination import Cursor, CursorCodec, InvalidCursorError, build_page, keyset_page

SECRET = b"x" * 32
CURSOR = Cursor(created_at=datetime(2026, 10, 13, 12, 30, tzinfo=UTC), id=UUID("01920000-0000-7000-8000-000000000001"))
id_column: Column[UUID] = Column("id", Uuid[UUID]())
created_at_column: Column[datetime] = Column("created_at", DateTime(timezone=True))
things = Table("things", MetaData(), id_column, created_at_column)


def flip_signature(token: str) -> str:
    return token[:-2] + ("AA" if not token.endswith("AA") else "BB")


def change_first_character(token: str) -> str:
    return "A" + token[1:]


def drop_separator(token: str) -> str:
    return token.replace(".", "")


def add_extra_segment(token: str) -> str:
    return token + ".extra"


def corrupt_payload(token: str) -> str:
    return "!!!." + token.split(".")[1]


def make_too_long(token: str) -> str:
    return token * 20


def encode_segment(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_round_trips_a_cursor() -> None:
    codec = CursorCodec(SECRET)

    assert codec.decode(codec.encode(CURSOR)) == CURSOR


def test_cursor_is_url_safe_and_opaque() -> None:
    token = CursorCodec(SECRET).encode(CURSOR)

    assert "=" not in token
    assert "+" not in token
    assert "/" not in token
    assert "2026" not in token


@pytest.mark.parametrize(
    "mutate",
    [flip_signature, change_first_character, drop_separator, add_extra_segment, corrupt_payload, make_too_long],
)
def test_rejects_tampered_cursors(mutate: Callable[[str], str]) -> None:
    codec = CursorCodec(SECRET)
    token = codec.encode(CURSOR)

    with pytest.raises(InvalidCursorError):
        codec.decode(mutate(token))


def test_rejects_cursor_signed_with_another_secret() -> None:
    token = CursorCodec(b"y" * 32).encode(CURSOR)

    with pytest.raises(InvalidCursorError):
        CursorCodec(SECRET).decode(token)


def test_rejects_validly_signed_garbage() -> None:
    codec = CursorCodec(SECRET)
    payload = b'{"t": "not-a-date", "i": "nope"}'
    signature = hmac.new(SECRET, payload, hashlib.sha256).digest()[:16]
    token = f"{encode_segment(payload)}.{encode_segment(signature)}"

    with pytest.raises(InvalidCursorError):
        codec.decode(token)


def test_requires_a_secret() -> None:
    with pytest.raises(ValueError, match="empty"):
        CursorCodec(b"")


def test_keyset_page_orders_newest_first_and_fetches_one_extra() -> None:
    statement = keyset_page(select(id_column), created_at=created_at_column, id_=id_column, cursor=CURSOR, limit=20)
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "(things.created_at, things.id) < (" in sql
    assert "ORDER BY things.created_at DESC, things.id DESC" in sql
    assert "LIMIT" in sql


def test_keyset_page_without_cursor_has_no_filter() -> None:
    statement = keyset_page(select(id_column), created_at=created_at_column, id_=id_column, cursor=None, limit=5)

    assert "WHERE" not in str(statement.compile(dialect=postgresql.dialect()))


def test_build_page_returns_cursor_only_when_more_rows_exist() -> None:
    codec = CursorCodec(SECRET)
    rows = [CURSOR, CURSOR, CURSOR]

    items, next_cursor = build_page(rows, limit=2, codec=codec, key=lambda row: row)
    last_items, last_cursor = build_page(rows[:2], limit=2, codec=codec, key=lambda row: row)

    assert len(items) == 2
    assert next_cursor is not None
    assert codec.decode(next_cursor) == CURSOR
    assert len(last_items) == 2
    assert last_cursor is None
