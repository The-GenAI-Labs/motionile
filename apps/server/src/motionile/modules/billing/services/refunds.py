from dataclasses import dataclass
from uuid import UUID

import structlog

from motionile.core.ids import new_id
from motionile.modules.audit import ActorType, AuditEvent
from motionile.modules.billing.exceptions import (
    PaymentNotFoundError,
    PaymentNotRefundableError,
    PaymentProviderUnavailableError,
    RefundRejectedError,
)
from motionile.modules.billing.ports import Alert, AuditRecorder, StoreFactory, Transaction
from motionile.modules.billing.razorpay.api import RazorpayApi
from motionile.modules.billing.razorpay.exceptions import RazorpayBadRequestError, RazorpayError
from motionile.modules.billing.razorpay.models import RazorpayRefund
from motionile.modules.billing.razorpay.models import RefundStatus as RemoteRefundStatus
from motionile.modules.billing.records import NewRefund, PaymentRecord, RefundRecord
from motionile.modules.billing.services.orders import rejection_reason
from motionile.modules.billing.services.provider import is_ambiguous, provider_error
from motionile.modules.billing.services.refund_rules import (
    REFUNDABLE_PAYMENT_STATUSES,
    refundable_paise,
    resolve_refund_amount,
)
from motionile.modules.billing.services.refund_settlement import RefundSettlement
from motionile.modules.billing.states import RefundStatus
from motionile.modules.billing.transitions import transition_refund

REFUND_ID_NOTE = "refundId"
PAYMENT_ID_NOTE = "paymentId"
UNAVAILABLE_REASON = "The payment provider could not be reached."

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CreateRefundCommand:
    admin_id: UUID | None
    payment_id: UUID
    amount_paise: int | None
    reason: str


@dataclass(frozen=True)
class RefundPlan:
    refund: RefundRecord
    payment: PaymentRecord


@dataclass(frozen=True)
class RefundDependencies:
    transaction: Transaction
    razorpay: RazorpayApi
    settlement: RefundSettlement
    store_factory: StoreFactory
    audit: AuditRecorder
    alert: Alert


class RefundService:
    def __init__(self, deps: RefundDependencies) -> None:
        self._transaction = deps.transaction
        self._razorpay = deps.razorpay
        self._settlement = deps.settlement
        self._store_factory = deps.store_factory
        self._audit = deps.audit
        self._alert = deps.alert

    async def create(self, command: CreateRefundCommand) -> RefundRecord:
        plan = await self._reserve(command)
        remote = await self._submit(plan)
        return await self._link(plan, remote)

    async def _reserve(self, command: CreateRefundCommand) -> RefundPlan:
        async with self._transaction() as session:
            store = self._store_factory(session)
            payment = await store.lock_payment(command.payment_id)
            if payment is None:
                raise PaymentNotFoundError
            if payment.status not in REFUNDABLE_PAYMENT_STATUSES:
                raise PaymentNotRefundableError("Only a captured payment can be refunded.")
            pending = (await store.pending_refund_totals([payment.id])).get(payment.id, 0)
            refundable = refundable_paise(
                amount_paise=payment.amount_paise, refunded_paise=payment.refunded_paise, pending_paise=pending
            )
            amount = resolve_refund_amount(command.amount_paise, refundable)
            refund = await store.insert_refund(
                NewRefund(
                    id=new_id(),
                    payment_id=payment.id,
                    amount_paise=amount,
                    reason=command.reason,
                    initiated_by=command.admin_id,
                )
            )
            await self._audit(
                session,
                AuditEvent(
                    action="billing.refund.requested",
                    actor_type=ActorType.ADMIN,
                    actor_user_id=command.admin_id,
                    target_type="refund",
                    target_id=str(refund.id),
                    metadata={
                        "paymentId": str(payment.id),
                        "userId": str(payment.user_id),
                        "amountPaise": amount,
                        "reason": command.reason,
                    },
                ),
            )
            return RefundPlan(refund, payment)

    async def _submit(self, plan: RefundPlan) -> RazorpayRefund:
        notes = {REFUND_ID_NOTE: str(plan.refund.id), PAYMENT_ID_NOTE: str(plan.payment.id)}
        try:
            return await self._razorpay.create_refund(
                plan.payment.razorpay_payment_id,
                amount=plan.refund.amount_paise,
                notes=notes,
                receipt=str(plan.refund.id),
            )
        except RazorpayBadRequestError as error:
            await self._fail(plan, rejection_reason(error))
            raise RefundRejectedError("The payment provider rejected the refund.") from error
        except RazorpayError as error:
            if not is_ambiguous(error):
                await self._fail(plan, UNAVAILABLE_REASON)
                raise provider_error(error) from error
            found = await self._find(plan, error)
            if found is None:
                self._alert(
                    "billing.refund_unconfirmed",
                    refund_id=str(plan.refund.id),
                    payment_id=str(plan.payment.id),
                    error_type=type(error).__name__,
                )
                raise PaymentProviderUnavailableError from error
            return found

    async def _find(self, plan: RefundPlan, cause: RazorpayError) -> RazorpayRefund | None:
        try:
            remote_refunds = await self._razorpay.list_payment_refunds(plan.payment.razorpay_payment_id)
        except RazorpayError as error:
            logger.warning("billing.refund_lookup_failed", refund_id=str(plan.refund.id), error=type(error).__name__)
            self._alert(
                "billing.refund_unconfirmed",
                refund_id=str(plan.refund.id),
                payment_id=str(plan.payment.id),
                error_type=type(cause).__name__,
            )
            raise PaymentProviderUnavailableError from error
        return next(
            (item for item in remote_refunds if item.notes.get(REFUND_ID_NOTE) == str(plan.refund.id)),
            None,
        )

    async def _fail(self, plan: RefundPlan, reason: str) -> None:
        async with self._transaction() as session:
            store = self._store_factory(session)
            await store.lock_payment(plan.payment.id)
            moved = await transition_refund(
                store, plan.refund.id, RefundStatus.PENDING, RefundStatus.FAILED, {"failure_reason": reason[:500]}
            )
            if moved:
                await self._audit(
                    session,
                    AuditEvent(
                        action="billing.refund.rejected",
                        actor_type=ActorType.SYSTEM,
                        target_type="refund",
                        target_id=str(plan.refund.id),
                        metadata={"paymentId": str(plan.payment.id), "reason": reason[:200]},
                    ),
                )
        self._alert(
            "billing.refund_rejected",
            refund_id=str(plan.refund.id),
            payment_id=str(plan.payment.id),
            reason=reason[:200],
        )

    async def _link(self, plan: RefundPlan, remote: RazorpayRefund) -> RefundRecord:
        async with self._transaction() as session:
            store = self._store_factory(session)
            await store.lock_payment(plan.payment.id)
            current = await store.lock_refund(plan.refund.id)
            if current is not None and current.razorpay_refund_id is None:
                await store.update_refund(current.id, {"razorpay_refund_id": remote.id})
            if remote.status == RemoteRefundStatus.PROCESSED:
                await self._settlement.apply_processed(session, plan.refund.id)
            elif remote.status == RemoteRefundStatus.FAILED:
                await self._settlement.apply_failed(session, plan.refund.id)
            refreshed = await store.refund_by_id(plan.refund.id)
        if refreshed is None:
            raise PaymentNotFoundError
        return refreshed
