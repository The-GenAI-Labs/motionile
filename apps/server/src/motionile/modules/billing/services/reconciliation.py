from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import structlog

from motionile.core.clock import Clock
from motionile.core.config import BillingSettings
from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.modules.billing.ports import StoreFactory, Transaction
from motionile.modules.billing.razorpay.api import RazorpayApi
from motionile.modules.billing.records import JsonObject, OrderRecord, RunCounts, RunOutcome
from motionile.modules.billing.repository import SqlBillingRepository
from motionile.modules.billing.services.decisions import SettlementOutcome, SettlementSource
from motionile.modules.billing.services.settlement import SettlementService
from motionile.modules.billing.services.webhook_processor import describe_failure
from motionile.modules.billing.states import OrderStatus, RunStatus
from motionile.modules.billing.transitions import transition_order

RUN_TYPE = "pending_orders"
BATCH_SIZE = 100
MAX_BATCHES = 20
EXPIRABLE_STATUSES = frozenset({OrderStatus.CREATED, OrderStatus.PENDING})

logger = structlog.get_logger(__name__)


@dataclass
class Tally:
    checked: int = 0
    settled: int = 0
    expired: int = 0
    mismatch: int = 0
    errors: int = 0

    def counts(self) -> RunCounts:
        return RunCounts(
            checked=self.checked,
            repaired=self.settled + self.expired,
            mismatch=self.mismatch,
            errors=self.errors,
        )

    def summary(self) -> JsonObject:
        return {"settled": self.settled, "expired": self.expired, "errors": self.errors}


@dataclass(frozen=True)
class ReconciliationDependencies:
    transaction: Transaction
    razorpay: RazorpayApi
    settlement: SettlementService
    clock: Clock
    settings: BillingSettings


class OrderReconciliation:
    def __init__(
        self,
        deps: ReconciliationDependencies,
        *,
        store_factory: StoreFactory = SqlBillingRepository,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        self._transaction = deps.transaction
        self._razorpay = deps.razorpay
        self._settlement = deps.settlement
        self._clock = deps.clock
        self._settings = deps.settings
        self._store_factory = store_factory
        self._batch_size = batch_size

    async def reconcile_pending_orders(self) -> RunCounts:
        run_id = new_id()
        async with self._transaction() as session:
            await self._store_factory(session).start_run(run_id, RUN_TYPE, self._clock.now())
        tally = Tally()
        try:
            await self._sweep(tally)
        except Exception as error:
            await self._finish(run_id, RunStatus.FAILED, tally, describe_failure(error))
            raise
        await self._finish(run_id, RunStatus.COMPLETED, tally, None)
        return tally.counts()

    async def _finish(self, run_id: UUID, status: RunStatus, tally: Tally, error: str | None) -> None:
        async with self._transaction() as session:
            await self._store_factory(session).finish_run(
                run_id,
                RunOutcome(
                    status=status,
                    counts=tally.counts(),
                    finished_at=self._clock.now(),
                    summary=tally.summary(),
                    error=error,
                ),
            )

    async def _sweep(self, tally: Tally) -> None:
        before = self._clock.now() - timedelta(seconds=self._settings.reconciliation_pending_after_seconds)
        cursor: Cursor | None = None
        for _ in range(MAX_BATCHES):
            async with self._transaction() as session:
                orders = await self._store_factory(session).reconcilable_orders(before, cursor, self._batch_size)
            for order in orders:
                await self._check(order, tally)
            if len(orders) < self._batch_size:
                return
            cursor = Cursor(orders[-1].created_at, orders[-1].id)

    async def _check(self, order: OrderRecord, tally: Tally) -> None:
        tally.checked += 1
        try:
            await self._reconcile(order, tally)
        except Exception:
            logger.exception("billing.reconciliation_order_failed", order_id=str(order.id))
            tally.errors += 1

    async def _reconcile(self, order: OrderRecord, tally: Tally) -> None:
        razorpay_order_id = order.razorpay_order_id
        if razorpay_order_id is None:
            remote = await self._razorpay.find_order_by_receipt(order.receipt)
            if remote is None:
                await self._expire_if_due(order, tally)
                return
            await self._attach(order, remote.id)
            razorpay_order_id = remote.id
        payments = await self._razorpay.order_payments(razorpay_order_id)
        captured = sorted((payment for payment in payments if payment.is_captured), key=lambda item: item.created_at)
        for payment in captured:
            async with self._transaction() as session:
                result = await self._settlement.settle(session, payment, SettlementSource.RECONCILIATION)
            if result.outcome is SettlementOutcome.SETTLED:
                tally.settled += 1
            elif result.needs_attention:
                tally.mismatch += 1
        if not captured:
            await self._expire_if_due(order, tally)

    async def _attach(self, order: OrderRecord, razorpay_order_id: str) -> None:
        async with self._transaction() as session:
            await transition_order(
                self._store_factory(session),
                order.id,
                OrderStatus.CREATED,
                OrderStatus.PENDING,
                {"razorpay_order_id": razorpay_order_id},
            )

    async def _expire_if_due(self, order: OrderRecord, tally: Tally) -> None:
        if self._clock.now() < order.expires_at:
            return
        async with self._transaction() as session:
            store = self._store_factory(session)
            current = await store.lock_order(order.id)
            if current is None or current.status not in EXPIRABLE_STATUSES or current.flagged_at is not None:
                return
            if await transition_order(store, current.id, current.status, OrderStatus.EXPIRED):
                tally.expired += 1
