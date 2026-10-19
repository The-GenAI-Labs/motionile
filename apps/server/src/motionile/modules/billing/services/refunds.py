import hashlib
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import structlog

from motionile.core.clock import Clock
from motionile.core.idempotency import IdempotencyKeyReusedError
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
NOT_FOUND_AT_PROVIDER = "not_found_at_provider"
STALE_AFTER = timedelta(minutes=15)
RECONCILE_BATCH_SIZE = 100

logger = structlog.get_logger(__name__)


def refund_idempotency_key(admin_id: UUID | None, payment_id: UUID, request_key: str) -> str:
    material = f"{admin_id or 'system'}:{payment_id}:{request_key}"
    return hashlib.sha256(material.encode()).hexdigest()


@dataclass(frozen=True)
class CreateRefundCommand:
    admin_id: UUID | None
    payment_id: UUID
    amount_paise: int | None
    reason: str
    request_key: str


@dataclass(frozen=True)
class RefundPlan:
    refund: RefundRecord
    payment: PaymentRecord
    resumed: bool = False


@dataclass(frozen=True)
class RefundDependencies:
    transaction: Transaction
    razorpay: RazorpayApi
    settlement: RefundSettlement
    store_factory: StoreFactory
    audit: AuditRecorder
    alert: Alert
    clock: Clock


@dataclass(frozen=True)
class RefundReconciliationCounts:
    linked: int = 0
    failed: int = 0
    errors: int = 0


class RefundService:
    def __init__(self, deps: RefundDependencies) -> None:
        self._transaction = deps.transaction
        self._razorpay = deps.razorpay
        self._settlement = deps.settlement
        self._store_factory = deps.store_factory
        self._audit = deps.audit
        self._alert = deps.alert
        self._clock = deps.clock

    async def create(self, command: CreateRefundCommand) -> RefundRecord:
        plan = await self._reserve(command)
        refund = plan.refund
        if refund.status is RefundStatus.FAILED:
            raise RefundRejectedError(refund.failure_reason or "The payment provider rejected the refund.")
        if refund.status is RefundStatus.PROCESSED or refund.razorpay_refund_id is not None:
            return refund
        remote = await self._submit(plan)
        return await self._link(plan, remote)

    async def reconcile_stale(self) -> RefundReconciliationCounts:
        cutoff = self._clock.now() - STALE_AFTER
        counts = RefundReconciliationCounts()
        after: UUID | None = None
        while True:
            async with self._transaction() as session:
                page = await self._store_factory(session).stale_unlinked_refunds(cutoff, after, RECONCILE_BATCH_SIZE)
            for refund in page:
                counts = await self._reconcile_one(refund, counts)
            if len(page) < RECONCILE_BATCH_SIZE:
                return counts
            after = page[-1].id

    async def _reconcile_one(
        self, refund: RefundRecord, counts: RefundReconciliationCounts
    ) -> RefundReconciliationCounts:
        try:
            async with self._transaction() as session:
                payment = await self._store_factory(session).payment_by_id(refund.payment_id)
            if payment is None:
                return counts
            plan = RefundPlan(refund, payment, resumed=True)
            found = await self._find(plan, None)
            if found is not None:
                await self._link(plan, found)
                self._alert(
                    "billing.refund_resolved", refund_id=str(refund.id), razorpay_refund_id=found.id, outcome="linked"
                )
                return RefundReconciliationCounts(counts.linked + 1, counts.failed, counts.errors)
            await self._fail(plan, NOT_FOUND_AT_PROVIDER, alert_code="billing.refund_not_found_at_provider")
        except Exception:
            logger.exception("billing.refund_reconciliation_failed", refund_id=str(refund.id))
            return RefundReconciliationCounts(counts.linked, counts.failed, counts.errors + 1)
        return RefundReconciliationCounts(counts.linked, counts.failed + 1, counts.errors)

    async def _reserve(self, command: CreateRefundCommand) -> RefundPlan:
        key = refund_idempotency_key(command.admin_id, command.payment_id, command.request_key)
        async with self._transaction() as session:
            store = self._store_factory(session)
            payment = await store.lock_payment(command.payment_id)
            if payment is None:
                raise PaymentNotFoundError
            existing = await store.refund_by_idempotency_key(key)
            if existing is not None:
                if command.amount_paise is not None and command.amount_paise != existing.amount_paise:
                    raise IdempotencyKeyReusedError("This Idempotency-Key was already used for a different refund.")
                return RefundPlan(existing, payment, resumed=True)
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
                    idempotency_key=key,
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
        if plan.resumed:
            found = await self._find(plan, None)
            if found is not None:
                return found
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
                self._alert_unconfirmed(plan, error)
                raise PaymentProviderUnavailableError from error
            return found

    def _alert_unconfirmed(self, plan: RefundPlan, cause: RazorpayError) -> None:
        self._alert(
            "billing.refund_unconfirmed",
            refund_id=str(plan.refund.id),
            payment_id=str(plan.payment.id),
            error_type=type(cause).__name__,
        )

    async def _find(self, plan: RefundPlan, cause: RazorpayError | None) -> RazorpayRefund | None:
        try:
            remote_refunds = await self._razorpay.list_payment_refunds(plan.payment.razorpay_payment_id)
        except RazorpayError as error:
            logger.warning("billing.refund_lookup_failed", refund_id=str(plan.refund.id), error=type(error).__name__)
            self._alert_unconfirmed(plan, cause or error)
            raise PaymentProviderUnavailableError from error
        return next(
            (item for item in remote_refunds if item.notes.get(REFUND_ID_NOTE) == str(plan.refund.id)),
            None,
        )

    async def _fail(self, plan: RefundPlan, reason: str, *, alert_code: str = "billing.refund_rejected") -> None:
        async with self._transaction() as session:
            store = self._store_factory(session)
            await store.lock_payment(plan.payment.id)
            current = await store.lock_refund(plan.refund.id)
            moved = (
                current is not None
                and current.razorpay_refund_id is None
                and await transition_refund(
                    store, plan.refund.id, RefundStatus.PENDING, RefundStatus.FAILED, {"failure_reason": reason[:500]}
                )
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
            alert_code,
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
