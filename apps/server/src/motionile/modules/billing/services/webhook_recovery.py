from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.modules.billing.exceptions import WebhookEventNotFoundError, WebhookEventNotReprocessableError
from motionile.modules.billing.ports import EventDispatcher, StoreFactory, Transaction
from motionile.modules.billing.records import RequeueQuery, WebhookEventRecord
from motionile.modules.billing.repository import SqlBillingRepository
from motionile.modules.billing.services.webhook_processor import MaxAttempts
from motionile.modules.billing.services.webhooks import PROVIDER
from motionile.modules.billing.states import REPROCESSABLE_EVENT_STATUSES

STUCK_AFTER = timedelta(minutes=2)
REQUEUE_BATCH_SIZE = 200


async def reprocess_event_with(
    session: AsyncSession,
    event_row_id: UUID,
    dispatch: EventDispatcher,
    *,
    store_factory: StoreFactory = SqlBillingRepository,
) -> WebhookEventRecord:
    event = await store_factory(session).lock_event(event_row_id)
    if event is None:
        raise WebhookEventNotFoundError
    if event.status not in REPROCESSABLE_EVENT_STATUSES:
        raise WebhookEventNotReprocessableError(f"A {event.status.value} event cannot be reprocessed.")
    dispatch(session, event.id, True)
    return event


@dataclass(frozen=True)
class RequeuePolicy:
    max_attempts: MaxAttempts
    task_name: str


class WebhookRequeuer:
    def __init__(
        self,
        transaction: Transaction,
        clock: Clock,
        dispatch: EventDispatcher,
        policy: RequeuePolicy,
        *,
        store_factory: StoreFactory = SqlBillingRepository,
    ) -> None:
        self._transaction = transaction
        self._clock = clock
        self._dispatch = dispatch
        self._policy = policy
        self._store_factory = store_factory

    async def requeue_stuck(self) -> int:
        async with self._transaction() as session:
            candidates = await self._store_factory(session).requeue_candidates(
                RequeueQuery(
                    provider=PROVIDER,
                    stale_before=self._clock.now() - STUCK_AFTER,
                    max_attempts=self._policy.max_attempts(),
                    task_name=self._policy.task_name,
                    limit=REQUEUE_BATCH_SIZE,
                )
            )
            for event_row_id in candidates:
                self._dispatch(session, event_row_id, False)
        return len(candidates)
