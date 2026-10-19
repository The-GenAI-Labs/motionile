from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

import structlog

from motionile.core.alerts import raise_alert
from motionile.core.clock import Clock
from motionile.core.ids import new_id
from motionile.modules.audit import ActorType, AuditEvent
from motionile.modules.billing.exceptions import SweepFailedError
from motionile.modules.billing.ports import Alert, AuditRecorder, StoreFactory, Transaction
from motionile.modules.billing.razorpay.api import RazorpayApi
from motionile.modules.billing.razorpay.exceptions import RazorpayError, RazorpayNotFoundError
from motionile.modules.billing.razorpay.models import SubscriptionStatus as RemoteSubscriptionStatus
from motionile.modules.billing.records import RunCounts, RunOutcome, SubscriptionRecord
from motionile.modules.billing.repository import BillingStore, SqlBillingRepository
from motionile.modules.billing.services.notices import NoticeSender, ended_notice
from motionile.modules.billing.services.subscription_logic import SyncPlan, plan_sync
from motionile.modules.billing.services.webhook_processor import describe_failure
from motionile.modules.billing.states import LIVE_SUBSCRIPTION_STATUSES, OrderStatus, RunStatus, SubscriptionStatus
from motionile.modules.billing.transitions import transition_order, transition_subscription

SYNC_RUN_TYPE = "subscriptions"
BATCH_SIZE = 100
SUBSCRIPTION_KIND = "subscription"
FALLBACK_PLAN_NAME = "Subscription"
EXPIRABLE_ORDER_STATUSES = frozenset({OrderStatus.CREATED, OrderStatus.PENDING})
CLOSED_REMOTE_STATUSES = frozenset({RemoteSubscriptionStatus.CANCELLED, RemoteSubscriptionStatus.EXPIRED})
SYNCED_STATUSES = LIVE_SUBSCRIPTION_STATUSES | {SubscriptionStatus.CREATED}

logger = structlog.get_logger(__name__)


def is_abandoned(subscription: SubscriptionRecord) -> bool:
    return subscription.status is SubscriptionStatus.CREATED and subscription.last_event_at is None


@dataclass(frozen=True)
class MaintenanceDependencies:
    transaction: Transaction
    razorpay: RazorpayApi
    clock: Clock
    audit: AuditRecorder
    notices: NoticeSender
    store_factory: StoreFactory = SqlBillingRepository
    alert: Alert = raise_alert


@dataclass(frozen=True)
class FinalizeCounts:
    cancelled: int
    expired: int


@dataclass
class SyncTally:
    checked: int = 0
    repaired: int = 0
    mismatch: int = 0
    errors: int = 0

    def counts(self) -> RunCounts:
        return RunCounts(checked=self.checked, repaired=self.repaired, mismatch=self.mismatch, errors=self.errors)


class SubscriptionSync:
    def __init__(self, deps: MaintenanceDependencies) -> None:
        self._transaction = deps.transaction
        self._razorpay = deps.razorpay
        self._clock = deps.clock
        self._audit = deps.audit
        self._store_factory = deps.store_factory
        self._alert = deps.alert

    async def run(self) -> RunCounts:
        run_id = new_id()
        async with self._transaction() as session:
            await self._store_factory(session).start_run(run_id, SYNC_RUN_TYPE, self._clock.now())
        tally = SyncTally()
        try:
            await self._sweep(tally)
        except Exception as error:
            await self._finish(run_id, RunStatus.FAILED, tally, describe_failure(error))
            raise
        await self._finish(run_id, RunStatus.COMPLETED, tally, None)
        if tally.mismatch:
            self._alert("billing.subscription_sync_mismatch", run_id=str(run_id), mismatch=tally.mismatch)
        return tally.counts()

    async def _finish(self, run_id: UUID, status: RunStatus, tally: SyncTally, error: str | None) -> None:
        outcome = RunOutcome(
            status=status,
            counts=tally.counts(),
            finished_at=self._clock.now(),
            summary={"errors": tally.errors},
            error=error,
        )
        async with self._transaction() as session:
            await self._store_factory(session).finish_run(run_id, outcome)

    async def _sweep(self, tally: SyncTally) -> None:
        await self._sweep_pages(tally, lambda store, after: store.live_subscriptions(after, BATCH_SIZE))
        await self._sweep_pages(tally, lambda store, after: store.unactivated_subscriptions(after, BATCH_SIZE))

    async def _sweep_pages(
        self,
        tally: SyncTally,
        fetch: Callable[[BillingStore, UUID | None], Awaitable[list[SubscriptionRecord]]],
    ) -> None:
        after: UUID | None = None
        while True:
            async with self._transaction() as session:
                page = await fetch(self._store_factory(session), after)
            for subscription in page:
                await self._check(subscription, tally)
            if len(page) < BATCH_SIZE:
                return
            after = page[-1].id

    async def _check(self, subscription: SubscriptionRecord, tally: SyncTally) -> None:
        tally.checked += 1
        try:
            await self.sync_one(subscription, tally)
        except Exception:
            logger.exception("billing.subscription_sync_failed", subscription_id=str(subscription.id))
            tally.errors += 1

    async def sync_one(self, subscription: SubscriptionRecord, tally: SyncTally) -> None:
        if subscription.razorpay_subscription_id is None:
            return
        remote = await self._razorpay.fetch_subscription(subscription.razorpay_subscription_id)
        async with self._transaction() as session:
            store = self._store_factory(session)
            current = await store.lock_subscription(subscription.id)
            if current is None or current.status not in SYNCED_STATUSES:
                return
            plan_product = await store.product_by_plan_id(remote.plan_id)
            usable = plan_product if plan_product is not None and plan_product.kind == SUBSCRIPTION_KIND else None
            plan = plan_sync(current, remote, usable, self._clock.now())
            if plan.unresolved:
                tally.mismatch += 1
            if not plan.changes_anything:
                return
            await self._apply(store, current, plan)
            tally.repaired += 1
            await self._audit(
                session,
                AuditEvent(
                    action="billing.subscription.synced",
                    actor_type=ActorType.SYSTEM,
                    target_type="subscription",
                    target_id=str(current.id),
                    metadata={
                        "userId": str(current.user_id),
                        "from": current.status.value,
                        "path": [step.value for step in plan.path],
                        "fields": sorted(plan.values),
                    },
                ),
            )

    async def _apply(self, store: BillingStore, current: SubscriptionRecord, plan: SyncPlan) -> None:
        status = current.status
        for index, target in enumerate(plan.path):
            values = plan.values if index == len(plan.path) - 1 else {}
            await transition_subscription(store, current.id, status, target, values)
            status = target
        if not plan.path:
            await store.update_subscription(current.id, plan.values)


class SubscriptionFinalizer:
    def __init__(self, deps: MaintenanceDependencies) -> None:
        self._transaction = deps.transaction
        self._razorpay = deps.razorpay
        self._clock = deps.clock
        self._audit = deps.audit
        self._notices = deps.notices
        self._store_factory = deps.store_factory
        self._sync = SubscriptionSync(deps)

    async def finalize(self) -> FinalizeCounts:
        failures = 0
        cancelled = 0
        expired = 0
        after: UUID | None = None
        while True:
            async with self._transaction() as session:
                due = await self._store_factory(session).due_cancellations(self._clock.now(), after, BATCH_SIZE)
            for subscription in due:
                try:
                    cancelled += await self._end_cancelled(subscription.id)
                except Exception:
                    logger.exception("billing.finalize_failed", subscription_id=str(subscription.id))
                    failures += 1
            if len(due) < BATCH_SIZE:
                break
            after = due[-1].id
        after = None
        while True:
            async with self._transaction() as session:
                abandoned = await self._store_factory(session).abandoned_subscriptions(
                    self._clock.now(), after, BATCH_SIZE
                )
            for subscription in abandoned:
                try:
                    expired += await self.expire(subscription)
                except Exception:
                    logger.exception("billing.expire_failed", subscription_id=str(subscription.id))
                    failures += 1
            if len(abandoned) < BATCH_SIZE:
                break
            after = abandoned[-1].id
        if failures:
            raise SweepFailedError("billing.finalize_subscriptions", failures)
        return FinalizeCounts(cancelled, expired)

    async def _end_cancelled(self, subscription_id: UUID) -> int:
        now = self._clock.now()
        async with self._transaction() as session:
            store = self._store_factory(session)
            current = await store.lock_subscription(subscription_id)
            if (
                current is None
                or current.status not in LIVE_SUBSCRIPTION_STATUSES
                or not current.cancel_at_period_end
                or current.current_period_end is None
                or current.current_period_end > now
            ):
                return 0
            await transition_subscription(
                store, current.id, current.status, SubscriptionStatus.CANCELLED, {"ended_at": now}
            )
            product = await store.product_by_id(current.product_id)
            await self._audit(
                session,
                AuditEvent(
                    action="billing.subscription.ended",
                    actor_type=ActorType.SYSTEM,
                    target_type="subscription",
                    target_id=str(current.id),
                    metadata={"userId": str(current.user_id), "from": current.status.value, "reason": "period_end"},
                ),
            )
            await self._notices(
                session,
                ended_notice(current.user_id, product.name if product is not None else FALLBACK_PLAN_NAME),
            )
        return 1

    async def expire(self, subscription: SubscriptionRecord) -> int:
        async with self._transaction() as session:
            current = await self._store_factory(session).lock_subscription(subscription.id)
        if current is None or not is_abandoned(current):
            return 0
        if current.razorpay_subscription_id is not None and not await self._remote_is_closed(
            current, current.razorpay_subscription_id
        ):
            return 0
        now = self._clock.now()
        async with self._transaction() as session:
            store = self._store_factory(session)
            locked = await store.lock_subscription(subscription.id)
            if locked is None or not is_abandoned(locked):
                return 0
            order = await store.lock_subscription_order(locked.id)
            if order is not None and order.status in EXPIRABLE_ORDER_STATUSES:
                await transition_order(store, order.id, order.status, OrderStatus.EXPIRED)
            await transition_subscription(
                store, locked.id, SubscriptionStatus.CREATED, SubscriptionStatus.EXPIRED, {"ended_at": now}
            )
            await self._audit(
                session,
                AuditEvent(
                    action="billing.subscription.expired",
                    actor_type=ActorType.SYSTEM,
                    target_type="subscription",
                    target_id=str(locked.id),
                    metadata={"userId": str(locked.user_id)},
                ),
            )
        return 1

    async def _remote_is_closed(self, subscription: SubscriptionRecord, razorpay_subscription_id: str) -> bool:
        try:
            remote = await self._razorpay.fetch_subscription(razorpay_subscription_id)
        except RazorpayNotFoundError:
            return True
        except RazorpayError:
            logger.warning("billing.expire_remote_fetch_failed", razorpay_subscription_id=razorpay_subscription_id)
            return False
        if remote.status in CLOSED_REMOTE_STATUSES:
            return True
        if remote.status != RemoteSubscriptionStatus.CREATED:
            await self._sync.sync_one(subscription, SyncTally())
            return False
        return await self._cancel_remote(razorpay_subscription_id)

    async def _cancel_remote(self, razorpay_subscription_id: str) -> bool:
        try:
            await self._razorpay.cancel_subscription(razorpay_subscription_id, at_cycle_end=False)
        except RazorpayNotFoundError:
            return True
        except RazorpayError:
            logger.warning("billing.expire_remote_cancel_failed", razorpay_subscription_id=razorpay_subscription_id)
            return False
        return True
