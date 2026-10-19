from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.billing.razorpay.models import RazorpayPayment
from motionile.modules.billing.records import JsonObject, WebhookEventRecord
from motionile.modules.billing.services.decisions import SettlementOutcome, SettlementSource
from motionile.modules.billing.services.settlement import SettlementService
from motionile.modules.billing.services.webhook_registry import (
    PROCESSED,
    UNKNOWN_ENTITY,
    HandlerRegistry,
    Outcome,
    ignored,
)


class PaymentContainer(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    entity: RazorpayPayment


class EventContents(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    payment: PaymentContainer | None = None


class EventBody(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    payload: EventContents = Field(default_factory=EventContents)


def payment_entity(payload: JsonObject) -> RazorpayPayment | None:
    container = EventBody.model_validate(payload).payload.payment
    return container.entity if container is not None else None


class PaymentEventHandlers:
    def __init__(self, settlement: SettlementService) -> None:
        self._settlement = settlement

    def register(self, registry: HandlerRegistry) -> None:
        registry.register_handler("payment.captured", self.captured)
        registry.register_handler("order.paid", self.order_paid)
        registry.register_handler("payment.failed", self.failed)

    async def captured(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        return await self._settle(session, event)

    async def order_paid(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        return await self._settle(session, event)

    async def failed(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        payment = payment_entity(event.payload)
        if payment is None:
            return ignored(UNKNOWN_ENTITY)
        result = await self._settlement.record_attempt(session, payment)
        return ignored(UNKNOWN_ENTITY) if result.outcome is SettlementOutcome.UNKNOWN_ORDER else PROCESSED

    async def _settle(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        payment = payment_entity(event.payload)
        if payment is None:
            return ignored(UNKNOWN_ENTITY)
        result = await self._settlement.settle(session, payment, SettlementSource.WEBHOOK)
        return ignored(UNKNOWN_ENTITY) if result.outcome is SettlementOutcome.UNKNOWN_ORDER else PROCESSED
