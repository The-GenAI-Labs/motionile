from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.pagination import CursorCodec
from motionile.modules.billing.admin_activity_repository import BillingActivityStore, SqlBillingActivityRepository
from motionile.modules.billing.admin_records import (
    OrderRow,
    PaymentRow,
    RecordPage,
    SubscriptionFilter,
    SubscriptionRow,
)
from motionile.modules.billing.exceptions import SubscriptionNotFoundError
from motionile.modules.billing.ports import Transaction
from motionile.modules.billing.services.admin_paging import decode_cursor, record_page
from motionile.modules.billing.services.subscription_management import AdminCancelCommand, SubscriptionManagement

type ActivityStoreOf = Callable[[AsyncSession], BillingActivityStore]


@dataclass(frozen=True)
class SubscriptionDetail:
    row: SubscriptionRow
    payments: list[PaymentRow]
    orders: list[OrderRow]


class SubscriptionAdminService:
    def __init__(
        self,
        transaction: Transaction,
        codec: CursorCodec,
        management: SubscriptionManagement,
        *,
        store_factory: ActivityStoreOf = SqlBillingActivityRepository,
    ) -> None:
        self._transaction = transaction
        self._codec = codec
        self._management = management
        self._store_factory = store_factory

    async def list(self, query: SubscriptionFilter, cursor: str | None, limit: int) -> RecordPage[SubscriptionRow]:
        position = decode_cursor(self._codec, cursor)
        async with self._transaction() as session:
            rows = await self._store_factory(session).list_subscriptions(query, position, limit)
        return record_page(rows, limit, self._codec, lambda row: (row.subscription.created_at, row.subscription.id))

    async def get(self, subscription_id: UUID) -> SubscriptionDetail:
        async with self._transaction() as session:
            store = self._store_factory(session)
            row = await store.subscription_row(subscription_id)
            if row is None:
                raise SubscriptionNotFoundError
            return SubscriptionDetail(
                row=row,
                payments=await store.payments_for_subscription(subscription_id),
                orders=await store.orders_for_subscription(subscription_id),
            )

    async def cancel(self, command: AdminCancelCommand) -> SubscriptionDetail:
        await self._management.cancel_as_admin(command)
        return await self.get(command.subscription_id)
