from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.unit.modules.billing.conftest import BillingHarness
from tests.unit.modules.billing.subscription_support import PLAN_CREDITS, SubscriptionHarness

from motionile.core.ids import new_id
from motionile.modules.audit import AuditEvent
from motionile.modules.billing.exceptions import PaymentProviderUnavailableError, SweepFailedError
from motionile.modules.billing.razorpay.fake_simulator import SubscriptionEvent
from motionile.modules.billing.razorpay.fake_store import EntityKind, FaultKind, FaultOperation
from motionile.modules.billing.records import RunOutcome
from motionile.modules.billing.services.subscription_maintenance import MaintenanceDependencies, SubscriptionFinalizer
from motionile.modules.billing.states import OrderStatus, RunStatus, SubscriptionStatus


@pytest.fixture
def subscription_harness(billing_harness: BillingHarness) -> SubscriptionHarness:
    return SubscriptionHarness(billing_harness)


def sync_runs(harness: SubscriptionHarness) -> list[RunOutcome | None]:
    billing = harness.base.billing
    return [outcome for run_id, outcome in billing.runs.items() if billing.run_types[run_id] == "subscriptions"]


async def test_a_cancelling_subscription_ends_when_its_period_is_over(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)
    await harness.management.cancel(harness.base.user_id)
    harness.base.clock.advance(timedelta(days=29))

    early = await harness.finalizer.finalize()

    assert early.cancelled == 0
    assert harness.local(checkout).status is SubscriptionStatus.ACTIVE
    harness.base.clock.advance(timedelta(days=3))

    due = await harness.finalizer.finalize()
    repeated = await harness.finalizer.finalize()

    assert (due.cancelled, repeated.cancelled) == (1, 0)
    subscription = harness.local(checkout)
    assert subscription.status is SubscriptionStatus.CANCELLED
    assert subscription.ended_at == harness.base.clock.now()
    assert harness.base.world.notices[-1].template == "subscription_ended"
    assert "billing.subscription.ended" in harness.base.audit_actions()
    assert harness.base.balance() == PLAN_CREDITS


async def test_a_subscription_that_is_not_cancelling_is_never_finalized(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)
    harness.base.clock.advance(timedelta(days=90))

    counts = await harness.finalizer.finalize()

    assert (counts.cancelled, counts.expired) == (0, 0)
    assert harness.local(checkout).status is SubscriptionStatus.ACTIVE


async def test_an_abandoned_checkout_expires_after_the_order_expiry_and_the_remote_subscription_is_cancelled(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    harness.base.clock.advance(timedelta(seconds=harness.base.settings.order_expiry_seconds - 1))

    early = await harness.finalizer.finalize()

    assert early.expired == 0
    harness.base.clock.advance(timedelta(seconds=1))
    expired = await harness.finalizer.finalize()

    assert expired.expired == 1
    subscription = harness.local(checkout)
    assert subscription.status is SubscriptionStatus.EXPIRED
    assert subscription.ended_at == harness.base.clock.now()
    assert harness.base.billing.orders[checkout.order_id].status is OrderStatus.EXPIRED
    assert (await harness.remote(checkout.razorpay_subscription_id)).status == "cancelled"
    assert "billing.subscription.expired" in harness.base.audit_actions()


async def test_a_checkout_with_activity_is_not_treated_as_abandoned(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    harness.patch(checkout.subscription_id, last_event_at=harness.base.clock.now())
    harness.base.clock.advance(timedelta(days=1))

    counts = await harness.finalizer.finalize()

    assert counts.expired == 0
    assert harness.local(checkout).status is SubscriptionStatus.CREATED


async def test_a_subscription_that_never_reached_the_provider_expires_without_a_remote_call(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    await harness.base.razorpay_store.add_fault(FaultOperation.CREATE_SUBSCRIPTION, FaultKind.TIMEOUT_BEFORE_CREATE, 1)
    with pytest.raises(PaymentProviderUnavailableError):
        await harness.checkout.create(harness.base.user_id, plan.code, "key-1")
    harness.base.clock.advance(timedelta(days=1))

    counts = await harness.finalizer.finalize()

    assert counts.expired == 1
    [subscription] = harness.base.billing.subscriptions.values()
    assert subscription.status is SubscriptionStatus.EXPIRED


async def test_expiry_waits_while_the_provider_cannot_confirm_the_cancellation(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    harness.base.clock.advance(timedelta(days=1))
    await harness.base.razorpay_store.add_fault(FaultOperation.CANCEL_SUBSCRIPTION, FaultKind.SERVER_ERROR, 1)

    first = await harness.finalizer.finalize()

    assert first.expired == 0
    assert harness.local(checkout).status is SubscriptionStatus.CREATED
    second = await harness.finalizer.finalize()
    assert second.expired == 1


async def test_a_failure_for_one_subscription_is_reported_after_the_others_were_handled(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    first = await harness.subscribe(plan)
    second = await harness.subscribe(plan, user_id=new_id())
    harness.base.clock.advance(timedelta(days=1))

    class FlakyAudit:
        calls = 0

        async def __call__(self, session: AsyncSession, event: AuditEvent) -> UUID:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            return await harness.base.audit(session, event)

    finalizer = SubscriptionFinalizer(
        MaintenanceDependencies(
            transaction=harness.base.world.transaction,
            razorpay=harness.base.razorpay,
            clock=harness.base.clock,
            audit=FlakyAudit(),
            notices=harness.base.world.send_notice,
            store_factory=harness.base.billing,
            alert=harness.base.world.alert,
        )
    )

    with pytest.raises(SweepFailedError) as raised:
        await finalizer.finalize()

    assert raised.value.failures == 1
    statuses = {harness.local(first).status, harness.local(second).status}
    assert statuses == {SubscriptionStatus.CREATED, SubscriptionStatus.EXPIRED}


async def test_the_sync_repairs_a_subscription_whose_webhooks_were_dropped(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    authorization, _ = await harness.authorize(checkout.razorpay_subscription_id)
    await harness.verify(harness.base.user_id, checkout.razorpay_subscription_id, authorization.payment["id"])
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.ACTIVATED)
    harness.base.clock.advance(timedelta(days=30))
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.CHARGED)
    remote = await harness.remote(checkout.razorpay_subscription_id)

    counts = await harness.sync.run()

    assert (counts.checked, counts.repaired, counts.mismatch, counts.errors) == (1, 1, 0, 0)
    subscription = harness.local(checkout)
    assert subscription.status is SubscriptionStatus.ACTIVE
    assert subscription.paid_count == remote.paid_count == 2
    assert subscription.current_period_end == remote.current_end_utc
    assert subscription.next_charge_at == remote.charge_at_utc
    [run] = sync_runs(harness)
    assert run is not None
    assert (run.status, run.counts.checked, run.counts.repaired) == (RunStatus.COMPLETED, 1, 1)
    assert "billing.subscription.synced" in harness.base.audit_actions()
    again = await harness.sync.run()
    assert (again.checked, again.repaired) == (1, 0)


async def test_the_sync_ends_subscriptions_that_the_provider_already_closed(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)
    harness.base.clock.advance(timedelta(days=45))
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.CANCELLED)

    counts = await harness.sync.run()

    assert counts.repaired == 1
    subscription = harness.local(checkout)
    assert subscription.status is SubscriptionStatus.CANCELLED
    assert subscription.ended_at is not None
    assert subscription.cancel_at_period_end is True


async def test_the_sync_keeps_access_until_the_period_end_for_a_cancellation_with_time_left(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)
    harness.base.clock.advance(timedelta(days=1))
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.CANCELLED)

    await harness.sync.run()

    subscription = harness.local(checkout)
    assert subscription.status is SubscriptionStatus.ACTIVE
    assert subscription.cancel_at_period_end is True


async def test_the_sync_applies_a_plan_change_the_webhook_missed(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    bigger = await harness.add_plan(price=199_900, credit_amount=1_500, name="Max")
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)
    harness.patch(checkout.subscription_id, pending_product_id=bigger.id)
    entity = await harness.stored(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id)
    entity["plan_id"] = bigger.razorpay_plan_id
    await harness.base.razorpay_store.put(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id, entity)

    await harness.sync.run()

    subscription = harness.local(checkout)
    assert (subscription.product_id, subscription.pending_product_id) == (bigger.id, None)


async def test_the_sync_never_moves_a_subscription_backwards(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)
    entity = await harness.stored(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id)
    entity["status"] = "authenticated"
    entity["paid_count"] = 0
    await harness.base.razorpay_store.put(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id, entity)

    counts = await harness.sync.run()

    assert (counts.repaired, counts.mismatch) == (0, 0)
    subscription = harness.local(checkout)
    assert subscription.status is SubscriptionStatus.ACTIVE
    assert subscription.paid_count == 1


async def test_a_state_the_machine_cannot_reach_is_counted_as_a_mismatch_and_alerted(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)
    entity = await harness.stored(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id)
    entity["status"] = "expired"
    await harness.base.razorpay_store.put(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id, entity)

    counts = await harness.sync.run()

    assert (counts.mismatch, counts.repaired) == (1, 0)
    assert harness.local(checkout).status is SubscriptionStatus.ACTIVE
    assert [code for code, _ in harness.base.world.alerts] == ["billing.subscription_sync_mismatch"]
    [run] = sync_runs(harness)
    assert run is not None
    assert run.counts.mismatch == 1


async def test_a_failure_for_one_subscription_is_counted_and_the_sync_continues(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    first = await harness.subscribe(plan)
    await harness.activate(first)
    second = await harness.subscribe(plan, user_id=new_id())
    await harness.activate(second)
    await harness.base.razorpay_store.add_fault(FaultOperation.FETCH_SUBSCRIPTION, FaultKind.SERVER_ERROR, 1)

    counts = await harness.sync.run()

    assert (counts.checked, counts.errors) == (2, 1)
    [run] = sync_runs(harness)
    assert run is not None
    assert run.status is RunStatus.COMPLETED
    assert run.summary == {"errors": 1}


async def test_a_created_subscription_that_the_provider_activated_is_repaired(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    await harness.authorize(checkout.razorpay_subscription_id)
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.ACTIVATED)

    counts = await harness.sync.run()

    assert counts.repaired == 1
    assert harness.local(checkout).status is SubscriptionStatus.ACTIVE
