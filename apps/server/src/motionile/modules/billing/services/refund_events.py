from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.billing.ports import Alert, StoreFactory
from motionile.modules.billing.razorpay.models import RazorpayRefund
from motionile.modules.billing.records import JsonObject, RefundRecord, WebhookEventRecord
from motionile.modules.billing.repository import BillingStore
from motionile.modules.billing.services.refund_settlement import RefundSettlement
from motionile.modules.billing.services.subscription_logic import INVALID_TRANSITION
from motionile.modules.billing.services.webhook_registry import (
    PROCESSED,
    UNKNOWN_ENTITY,
    HandlerRegistry,
    Outcome,
    ignored,
)
from motionile.modules.billing.states import RefundStatus

REFUND_ID_NOTE = "refundId"


class RefundContainer(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    entity: RazorpayRefund


class RefundContents(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    refund: RefundContainer | None = None


class RefundEventBody(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    payload: RefundContents = Field(default_factory=RefundContents)


def refund_entity(payload: JsonObject) -> RazorpayRefund | None:
    container = RefundEventBody.model_validate(payload).payload.refund
    return container.entity if container is not None else None


def parse_refund_id(value: str | None) -> UUID | None:
    if value is None:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


class RefundEventHandlers:
    def __init__(self, settlement: RefundSettlement, store_factory: StoreFactory, alert: Alert) -> None:
        self._settlement = settlement
        self._store_factory = store_factory
        self._alert = alert

    def register(self, registry: HandlerRegistry) -> None:
        registry.register_handler("refund.created", self.created)
        registry.register_handler("refund.processed", self.processed)
        registry.register_handler("refund.failed", self.failed)

    async def created(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        located = await self._link(session, event)
        return ignored(UNKNOWN_ENTITY) if located is None else PROCESSED

    async def processed(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        located = await self._link(session, event)
        if located is None:
            return ignored(UNKNOWN_ENTITY)
        settled = await self._settlement.apply_processed(session, located.id)
        return (
            PROCESSED
            if settled is not None and settled.status is RefundStatus.PROCESSED
            else ignored(INVALID_TRANSITION)
        )

    async def failed(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        located = await self._link(session, event)
        if located is None:
            return ignored(UNKNOWN_ENTITY)
        settled = await self._settlement.apply_failed(session, located.id)
        return (
            PROCESSED if settled is not None and settled.status is RefundStatus.FAILED else ignored(INVALID_TRANSITION)
        )

    async def _link(self, session: AsyncSession, event: WebhookEventRecord) -> RefundRecord | None:
        remote = refund_entity(event.payload)
        if remote is None:
            return None
        store = self._store_factory(session)
        refund = await self._locate(store, remote)
        if refund is None:
            self._alert("billing.unknown_refund", razorpay_refund_id=remote.id, razorpay_payment_id=remote.payment_id)
            return None
        payment = await store.lock_payment(refund.payment_id)
        current = await store.lock_refund(refund.id)
        if payment is None or current is None:
            return None
        if payment.razorpay_payment_id != remote.payment_id:
            self._alert(
                "billing.refund_payment_mismatch",
                refund_id=str(refund.id),
                razorpay_refund_id=remote.id,
                razorpay_payment_id=remote.payment_id,
            )
            return None
        if current.razorpay_refund_id is None:
            await store.update_refund(current.id, {"razorpay_refund_id": remote.id})
        return current

    async def _locate(self, store: BillingStore, remote: RazorpayRefund) -> RefundRecord | None:
        by_remote_id = await store.refund_by_razorpay_id(remote.id)
        if by_remote_id is not None:
            return by_remote_id
        local_id = parse_refund_id(remote.notes.get(REFUND_ID_NOTE))
        return await store.refund_by_id(local_id) if local_id is not None else None
