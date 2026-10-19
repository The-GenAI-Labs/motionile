from collections.abc import Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.pagination import CursorCodec
from motionile.modules.audit import ActorType, AuditEvent
from motionile.modules.billing.admin_activity_repository import BillingActivityStore, SqlBillingActivityRepository
from motionile.modules.billing.admin_records import EventDetail, EventFilter, EventSummary, RecordPage
from motionile.modules.billing.exceptions import WebhookEventNotFoundError
from motionile.modules.billing.ports import AuditRecorder, EventDispatcher, Transaction
from motionile.modules.billing.services.admin_paging import decode_cursor, record_page
from motionile.modules.billing.services.webhook_recovery import reprocess_event_with

type ActivityStoreOf = Callable[[AsyncSession], BillingActivityStore]


class WebhookAdminService:
    def __init__(
        self,
        transaction: Transaction,
        codec: CursorCodec,
        dispatch: EventDispatcher,
        audit: AuditRecorder,
        *,
        store_factory: ActivityStoreOf = SqlBillingActivityRepository,
    ) -> None:
        self._transaction = transaction
        self._codec = codec
        self._dispatch = dispatch
        self._audit = audit
        self._store_factory = store_factory

    async def list(self, query: EventFilter, cursor: str | None, limit: int) -> RecordPage[EventSummary]:
        position = decode_cursor(self._codec, cursor)
        async with self._transaction() as session:
            rows = await self._store_factory(session).list_events(query, position, limit)
        return record_page(rows, limit, self._codec, lambda row: (row.created_at, row.id))

    async def get(self, event_row_id: UUID) -> EventDetail:
        async with self._transaction() as session:
            detail = await self._store_factory(session).event_detail(event_row_id)
        if detail is None:
            raise WebhookEventNotFoundError
        return detail

    async def reprocess(self, admin_id: UUID | None, event_row_id: UUID) -> EventSummary:
        async with self._transaction() as session:
            event = await reprocess_event_with(session, event_row_id, self._dispatch)
            await self._audit(
                session,
                AuditEvent(
                    action="billing.webhook.reprocess_requested",
                    actor_type=ActorType.ADMIN,
                    actor_user_id=admin_id,
                    target_type="webhook_event",
                    target_id=str(event.id),
                    metadata={"eventId": event.event_id, "eventType": event.event_type, "status": event.status.value},
                ),
            )
            summary = await self._store_factory(session).event_detail(event.id)
        if summary is None:
            raise WebhookEventNotFoundError
        return summary.summary
