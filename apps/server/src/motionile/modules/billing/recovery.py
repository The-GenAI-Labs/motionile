from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.billing.records import WebhookEventRecord
from motionile.modules.billing.services.webhook_recovery import reprocess_event_with
from motionile.modules.billing.tasks import defer_event_processing


async def reprocess_event(session: AsyncSession, event_row_id: UUID) -> WebhookEventRecord:
    return await reprocess_event_with(session, event_row_id, defer_event_processing)
