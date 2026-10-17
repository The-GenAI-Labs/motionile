from uuid import UUID

from motionile.core.pagination import Cursor, CursorCodec, build_page
from motionile.modules.billing.ports import StoreFactory, Transaction
from motionile.modules.billing.records import HistoryRow
from motionile.modules.billing.repository import SqlBillingRepository
from motionile.modules.billing.schemas import HistoryItemResponse, HistoryPageResponse


def history_item(row: HistoryRow) -> HistoryItemResponse:
    return HistoryItemResponse(
        type=row.kind,
        id=row.id,
        status=row.status,
        amount_paise=row.amount_paise,
        currency=row.currency,
        title=row.title,
        credits_granted=row.credits_granted,
        created_at=row.created_at,
        order_id=row.order_id,
        payment_id=row.payment_id,
    )


class HistoryService:
    def __init__(
        self, transaction: Transaction, codec: CursorCodec, *, store_factory: StoreFactory = SqlBillingRepository
    ) -> None:
        self._transaction = transaction
        self._codec = codec
        self._store_factory = store_factory

    async def page(self, user_id: UUID, cursor_token: str | None, limit: int) -> HistoryPageResponse:
        cursor = self._codec.decode(cursor_token) if cursor_token else None
        async with self._transaction() as session:
            rows = await self._store_factory(session).history(user_id, cursor, limit)
        items, next_cursor = build_page(
            rows, limit=limit, codec=self._codec, key=lambda row: Cursor(row.created_at, row.id)
        )
        return HistoryPageResponse(items=[history_item(row) for row in items], next_cursor=next_cursor)
