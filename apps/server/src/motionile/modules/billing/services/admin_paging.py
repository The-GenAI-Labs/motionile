from collections.abc import Callable, Sequence
from datetime import datetime
from uuid import UUID

from motionile.core.pagination import Cursor, CursorCodec, build_page
from motionile.modules.billing.admin_records import RecordPage


def decode_cursor(codec: CursorCodec, token: str | None) -> Cursor | None:
    return codec.decode(token) if token else None


def record_page[RowT](
    rows: Sequence[RowT], limit: int, codec: CursorCodec, position: Callable[[RowT], tuple[datetime, UUID]]
) -> RecordPage[RowT]:
    items, next_cursor = build_page(rows, limit=limit, codec=codec, key=lambda row: Cursor(*position(row)))
    return RecordPage(items, next_cursor)
