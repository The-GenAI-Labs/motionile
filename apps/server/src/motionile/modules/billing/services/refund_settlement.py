from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.modules.audit import ActorType, AuditEvent
from motionile.modules.billing.ports import Alert, AuditRecorder, StoreFactory
from motionile.modules.billing.records import PaymentRecord, RefundRecord
from motionile.modules.billing.repository import BillingStore
from motionile.modules.billing.services.notices import NoticeSender, RefundSummary, refund_notice
from motionile.modules.billing.services.refund_rules import clawback_amount, refund_payment_status
from motionile.modules.billing.states import PAYMENT_MACHINE, RefundStatus
from motionile.modules.billing.transitions import transition_payment, transition_refund
from motionile.modules.credits import ClawbackCommand, CreditRef, CreditsService, LotRecord, lot_for_reference

FAILURE_FALLBACK = "The payment provider reported that the refund failed."
CLAWBACK_REASON_PREFIX = "Refund"


type LotLookup = Callable[[AsyncSession, CreditRef], Awaitable[LotRecord | None]]


@dataclass(frozen=True)
class RefundPorts:
    store_factory: StoreFactory
    audit: AuditRecorder
    alert: Alert
    notices: NoticeSender
    lot_lookup: LotLookup = lot_for_reference


class RefundSettlement:
    def __init__(self, clock: Clock, credit_service: CreditsService, ports: RefundPorts) -> None:
        self._clock = clock
        self._credits = credit_service
        self._store_factory = ports.store_factory
        self._audit = ports.audit
        self._alert = ports.alert
        self._notices = ports.notices
        self._lot_lookup = ports.lot_lookup

    async def apply_processed(self, session: AsyncSession, refund_id: UUID) -> RefundRecord | None:
        store = self._store_factory(session)
        located = await store.refund_by_id(refund_id)
        if located is None:
            return None
        payment = await store.lock_payment(located.payment_id)
        refund = await store.lock_refund(refund_id)
        if payment is None or refund is None:
            return None
        if refund.status is not RefundStatus.PENDING:
            return refund
        clawed_back = await self._claw_back(session, store, payment, refund)
        await transition_refund(
            store,
            refund.id,
            RefundStatus.PENDING,
            RefundStatus.PROCESSED,
            {"processed_at": self._clock.now(), "credits_clawed_back": clawed_back},
        )
        await self._record_refunded(store, payment, refund)
        await self._announce_processed(session, payment, refund, clawed_back)
        return await store.refund_by_id(refund.id)

    async def apply_failed(
        self, session: AsyncSession, refund_id: UUID, reason: str | None = None
    ) -> RefundRecord | None:
        store = self._store_factory(session)
        located = await store.refund_by_id(refund_id)
        if located is None:
            return None
        payment = await store.lock_payment(located.payment_id)
        refund = await store.lock_refund(refund_id)
        if payment is None or refund is None:
            return None
        if refund.status is not RefundStatus.PENDING:
            return refund
        failure = reason or FAILURE_FALLBACK
        await transition_refund(
            store, refund.id, RefundStatus.PENDING, RefundStatus.FAILED, {"failure_reason": failure[:500]}
        )
        self._alert(
            "billing.refund_failed",
            refund_id=str(refund.id),
            payment_id=str(payment.id),
            amount_paise=refund.amount_paise,
            reason=failure[:200],
        )
        await self._record(session, "billing.refund.failed", refund, {"reason": failure[:200]})
        return await store.refund_by_id(refund.id)

    async def _claw_back(
        self, session: AsyncSession, store: BillingStore, payment: PaymentRecord, refund: RefundRecord
    ) -> int:
        if payment.credits_granted <= 0:
            return 0
        lot = await self._lot_lookup(session, CreditRef("payment", payment.id))
        if lot is None:
            return 0
        requested = clawback_amount(
            credits_granted=payment.credits_granted,
            payment_amount_paise=payment.amount_paise,
            refund_amount_paise=refund.amount_paise,
            already_clawed_back=await store.clawed_back_total(payment.id),
            lot_remaining=lot.remaining,
        )
        if requested <= 0:
            return 0
        result = await self._credits.clawback(
            session,
            ClawbackCommand(
                lot_id=lot.id,
                amount=requested,
                reason=f"{CLAWBACK_REASON_PREFIX} {refund.id}",
                ref=CreditRef("refund", refund.id),
                key=f"refund:{refund.id}",
            ),
        )
        return result.clawed_back

    async def _record_refunded(self, store: BillingStore, payment: PaymentRecord, refund: RefundRecord) -> None:
        refunded = min(payment.refunded_paise + refund.amount_paise, payment.amount_paise)
        target = refund_payment_status(amount_paise=payment.amount_paise, refunded_paise=refunded)
        if PAYMENT_MACHINE.allows(payment.status, target):
            await transition_payment(store, payment.id, payment.status, target, {"refunded_paise": refunded})
        else:
            self._alert(
                "billing.refund_after_full_refund",
                refund_id=str(refund.id),
                payment_id=str(payment.id),
                payment_status=payment.status.value,
            )

    async def _announce_processed(
        self, session: AsyncSession, payment: PaymentRecord, refund: RefundRecord, clawed_back: int
    ) -> None:
        await self._record(
            session,
            "billing.refund.processed",
            refund,
            {
                "paymentId": str(payment.id),
                "amountPaise": refund.amount_paise,
                "creditsClawedBack": clawed_back,
            },
        )
        await self._notices(
            session,
            refund_notice(
                payment.user_id,
                RefundSummary(
                    amount_paise=refund.amount_paise,
                    currency=payment.currency,
                    credits_recovered=clawed_back,
                    reference=str(refund.id),
                ),
            ),
        )

    async def _record(
        self, session: AsyncSession, action: str, refund: RefundRecord, metadata: dict[str, object]
    ) -> None:
        await self._audit(
            session,
            AuditEvent(
                action=action,
                actor_type=ActorType.SYSTEM,
                target_type="refund",
                target_id=str(refund.id),
                metadata={"paymentId": str(refund.payment_id), **metadata},
            ),
        )
