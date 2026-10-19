from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.modules.audit import ActorType, AuditEvent
from motionile.modules.billing.ports import Alert, AuditRecorder, StoreFactory
from motionile.modules.billing.razorpay.models import RazorpayRefund
from motionile.modules.billing.razorpay.models import RefundStatus as RemoteRefundStatus
from motionile.modules.billing.records import JsonObject, NewRefund, PaymentRecord, RefundRecord, WebhookEventRecord
from motionile.modules.billing.repository import BillingStore
from motionile.modules.billing.services.refund_rules import (
    EXTERNAL_KEY_PREFIX,
    EXTERNAL_REASON,
    refundable_paise,
)
from motionile.modules.billing.services.refund_settlement import RefundSettlement
from motionile.modules.billing.services.subscription_logic import INVALID_TRANSITION
from motionile.modules.billing.services.webhook_registry import (
    PROCESSED,
    UNKNOWN_ENTITY,
    HandlerRegistry,
    Outcome,
    ignored,
)
from motionile.modules.billing.states import PaymentRecordStatus, RefundStatus

REFUND_ID_NOTE = "refundId"
ADOPTABLE_PAYMENT_STATUSES = frozenset(
    {PaymentRecordStatus.CAPTURED, PaymentRecordStatus.PARTIALLY_REFUNDED, PaymentRecordStatus.REFUNDED}
)


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
    def __init__(
        self, settlement: RefundSettlement, store_factory: StoreFactory, alert: Alert, audit: AuditRecorder
    ) -> None:
        self._settlement = settlement
        self._audit = audit
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
            refund = await self._adopt(session, store, remote)
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

    async def _adopt(self, session: AsyncSession, store: BillingStore, remote: RazorpayRefund) -> RefundRecord | None:
        if parse_refund_id(remote.notes.get(REFUND_ID_NOTE)) is not None:
            return None
        known = await store.payment_by_razorpay_id(remote.payment_id)
        if known is None:
            return None
        payment = await store.lock_payment(known.id)
        concurrent = await self._locate(store, remote)
        if concurrent is not None or payment is None:
            return concurrent
        if payment.status not in ADOPTABLE_PAYMENT_STATUSES:
            return None
        if remote.status != RemoteRefundStatus.FAILED and not await self._fits(store, payment, remote):
            self._alert(
                "billing.external_refund_exceeds_payment",
                razorpay_refund_id=remote.id,
                payment_id=str(payment.id),
                amount_paise=remote.amount,
            )
            return None
        adopted = await store.insert_refund(
            NewRefund(
                id=new_id(),
                payment_id=payment.id,
                amount_paise=remote.amount,
                reason=EXTERNAL_REASON,
                initiated_by=None,
                idempotency_key=f"{EXTERNAL_KEY_PREFIX}{remote.id}",
                razorpay_refund_id=remote.id,
            )
        )
        await self._audit(
            session,
            AuditEvent(
                action="billing.refund.adopted",
                actor_type=ActorType.SYSTEM,
                target_type="refund",
                target_id=str(adopted.id),
                metadata={
                    "paymentId": str(payment.id),
                    "razorpayRefundId": remote.id,
                    "amountPaise": remote.amount,
                    "remoteStatus": remote.status,
                },
            ),
        )
        return adopted

    async def _fits(self, store: BillingStore, payment: PaymentRecord, remote: RazorpayRefund) -> bool:
        pending = (await store.pending_refund_totals([payment.id])).get(payment.id, 0)
        baseline = max(payment.refunded_paise - await store.processed_refund_total(payment.id), 0)
        refundable = refundable_paise(
            amount_paise=payment.amount_paise, refunded_paise=payment.refunded_paise, pending_paise=pending
        )
        return remote.amount - min(baseline, remote.amount) <= refundable

    async def _locate(self, store: BillingStore, remote: RazorpayRefund) -> RefundRecord | None:
        by_remote_id = await store.refund_by_razorpay_id(remote.id)
        if by_remote_id is not None:
            return by_remote_id
        local_id = parse_refund_id(remote.notes.get(REFUND_ID_NOTE))
        return await store.refund_by_id(local_id) if local_id is not None else None
