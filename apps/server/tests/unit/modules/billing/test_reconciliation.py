from dataclasses import replace
from datetime import timedelta

import pytest
from tests.unit.modules.billing.conftest import PACK_CREDITS, PACK_PRICE, BillingHarness

from motionile.core.pagination import Cursor
from motionile.modules.billing.razorpay.fake_simulator import PaymentOutcome
from motionile.modules.billing.razorpay.fake_store import FaultKind, FaultOperation
from motionile.modules.billing.records import OrderRecord, RunOutcome
from motionile.modules.billing.services.decisions import SettlementSource
from motionile.modules.billing.services.reconciliation import OrderReconciliation, ReconciliationDependencies
from motionile.modules.billing.states import OrderStatus, RunStatus

STALE_AFTER = timedelta(minutes=31)
PAST_EXPIRY = timedelta(hours=2, minutes=1)


def reconciliation_for(harness: BillingHarness, *, batch_size: int = 100) -> OrderReconciliation:
    return OrderReconciliation(
        ReconciliationDependencies(
            harness.world.transaction, harness.razorpay, harness.settlement, harness.clock, harness.settings
        ),
        store_factory=harness.billing,
        batch_size=batch_size,
    )


def only_run(harness: BillingHarness) -> RunOutcome:
    [outcome] = harness.billing.runs.values()
    assert outcome is not None
    return outcome


async def test_an_order_whose_payment_was_never_settled_is_repaired(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    await billing_harness.pay(order)
    billing_harness.clock.advance(STALE_AFTER)

    counts = await reconciliation_for(billing_harness).reconcile_pending_orders()

    assert (counts.checked, counts.repaired, counts.mismatch, counts.errors) == (1, 1, 0, 0)
    assert billing_harness.billing.orders[order.id].status is OrderStatus.PAID
    assert billing_harness.balance() == PACK_CREDITS
    outcome = only_run(billing_harness)
    assert outcome.status is RunStatus.COMPLETED
    assert (outcome.counts.checked, outcome.counts.repaired, outcome.counts.mismatch) == (1, 1, 0)
    assert outcome.summary == {"settled": 1, "expired": 0, "errors": 0}
    assert outcome.finished_at == billing_harness.clock.now()
    assert set(billing_harness.billing.run_types.values()) == {"pending_orders"}


async def test_orders_younger_than_the_threshold_are_left_alone(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    await billing_harness.pay(order)
    billing_harness.clock.advance(timedelta(minutes=29))

    counts = await reconciliation_for(billing_harness).reconcile_pending_orders()

    assert counts.checked == 0
    assert billing_harness.billing.orders[order.id].status is OrderStatus.PENDING


async def test_an_overdue_unpaid_order_expires(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    billing_harness.clock.advance(PAST_EXPIRY)

    counts = await reconciliation_for(billing_harness).reconcile_pending_orders()

    assert (counts.checked, counts.repaired) == (1, 1)
    assert billing_harness.billing.orders[order.id].status is OrderStatus.EXPIRED
    assert only_run(billing_harness).summary["expired"] == 1


async def test_an_unpaid_order_that_is_not_overdue_stays_pending(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    billing_harness.clock.advance(STALE_AFTER)

    counts = await reconciliation_for(billing_harness).reconcile_pending_orders()

    assert (counts.checked, counts.repaired) == (1, 0)
    assert billing_harness.billing.orders[order.id].status is OrderStatus.PENDING


async def test_an_overdue_order_with_only_failed_attempts_expires(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    await billing_harness.pay(order, PaymentOutcome.FAILURE)
    billing_harness.clock.advance(PAST_EXPIRY)

    await reconciliation_for(billing_harness).reconcile_pending_orders()

    assert billing_harness.billing.orders[order.id].status is OrderStatus.EXPIRED


async def test_a_payment_landing_after_expiry_still_settles_the_expired_order(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    billing_harness.clock.advance(PAST_EXPIRY)
    await reconciliation_for(billing_harness).reconcile_pending_orders()
    assert billing_harness.billing.orders[order.id].status is OrderStatus.EXPIRED
    payment = await billing_harness.pay(order)

    async with billing_harness.world.transaction() as session:
        await billing_harness.settlement.settle(session, payment, SettlementSource.WEBHOOK)

    assert billing_harness.billing.orders[order.id].status is OrderStatus.PAID
    assert "billing.order.settled_late" in billing_harness.audit_actions()


async def test_finished_and_flagged_orders_are_not_reconciled(billing_harness: BillingHarness) -> None:
    paid = await billing_harness.open_order(status=OrderStatus.PAID)
    flagged = await billing_harness.open_order()
    billing_harness.billing.orders[flagged.id] = replace(
        flagged, flagged_at=billing_harness.clock.now(), flag_reason="amount_mismatch"
    )
    failed = await billing_harness.open_order(status=OrderStatus.FAILED)
    billing_harness.clock.advance(PAST_EXPIRY)

    counts = await reconciliation_for(billing_harness).reconcile_pending_orders()

    assert counts.checked == 0
    assert billing_harness.billing.orders[paid.id].status is OrderStatus.PAID
    assert billing_harness.billing.orders[flagged.id].status is OrderStatus.PENDING
    assert billing_harness.billing.orders[failed.id].status is OrderStatus.FAILED


async def test_a_mismatched_payment_is_counted_not_repaired(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    await billing_harness.pay(order, amount=PACK_PRICE + 1)
    billing_harness.clock.advance(STALE_AFTER)

    counts = await reconciliation_for(billing_harness).reconcile_pending_orders()

    assert (counts.checked, counts.repaired, counts.mismatch) == (1, 0, 1)
    assert billing_harness.billing.orders[order.id].flag_reason == "amount_mismatch"
    assert billing_harness.balance() == 0


async def test_a_failure_on_one_order_does_not_abort_the_batch(billing_harness: BillingHarness) -> None:
    first = await billing_harness.open_order()
    second = await billing_harness.open_order(user_id=billing_harness.user_id)
    await billing_harness.pay(first)
    await billing_harness.pay(second)
    billing_harness.clock.advance(STALE_AFTER)
    await billing_harness.razorpay_store.add_fault(FaultOperation.ORDER_PAYMENTS, FaultKind.SERVER_ERROR, 1)

    counts = await reconciliation_for(billing_harness).reconcile_pending_orders()

    assert (counts.checked, counts.repaired, counts.errors) == (2, 1, 1)
    statuses = sorted(order.status.value for order in billing_harness.billing.orders.values())
    assert statuses == ["paid", "pending"]
    outcome = only_run(billing_harness)
    assert outcome.status is RunStatus.COMPLETED
    assert outcome.summary["errors"] == 1


async def test_every_batch_is_walked(billing_harness: BillingHarness) -> None:
    orders: list[OrderRecord] = []
    for _ in range(5):
        order = await billing_harness.open_order()
        await billing_harness.pay(order)
        orders.append(order)
        billing_harness.clock.advance(timedelta(seconds=1))
    billing_harness.clock.advance(STALE_AFTER)

    counts = await reconciliation_for(billing_harness, batch_size=2).reconcile_pending_orders()

    assert (counts.checked, counts.repaired) == (5, 5)
    assert all(billing_harness.billing.orders[order.id].status is OrderStatus.PAID for order in orders)
    assert billing_harness.balance() == 5 * PACK_CREDITS


async def test_a_created_order_with_a_provider_order_is_attached_and_settled(billing_harness: BillingHarness) -> None:
    order = await billing_harness.local_order()
    remote = await billing_harness.razorpay.create_order(
        amount=order.amount_paise, currency=order.currency, receipt=order.receipt
    )
    billing_harness.billing.orders[order.id] = replace(order, razorpay_order_id=None)
    await billing_harness.simulator.pay_order(remote.id, PaymentOutcome.SUCCESS)
    billing_harness.clock.advance(STALE_AFTER)

    counts = await reconciliation_for(billing_harness).reconcile_pending_orders()

    assert (counts.checked, counts.repaired) == (1, 1)
    settled = billing_harness.billing.orders[order.id]
    assert (settled.status, settled.razorpay_order_id) == (OrderStatus.PAID, remote.id)


async def test_a_created_order_without_a_provider_order_expires_only_when_overdue(
    billing_harness: BillingHarness,
) -> None:
    order = await billing_harness.local_order()
    billing_harness.clock.advance(STALE_AFTER)
    reconciliation = reconciliation_for(billing_harness)

    await reconciliation.reconcile_pending_orders()
    assert billing_harness.billing.orders[order.id].status is OrderStatus.CREATED

    billing_harness.clock.advance(PAST_EXPIRY)
    await reconciliation.reconcile_pending_orders()
    assert billing_harness.billing.orders[order.id].status is OrderStatus.EXPIRED


async def test_a_sweep_failure_is_recorded_on_the_run_and_raised(
    billing_harness: BillingHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(before: object, after: Cursor | None, limit: int) -> list[OrderRecord]:
        del before, after, limit
        message = "database unavailable"
        raise ConnectionError(message)

    monkeypatch.setattr(billing_harness.billing, "reconcilable_orders", broken)

    with pytest.raises(ConnectionError):
        await reconciliation_for(billing_harness).reconcile_pending_orders()

    outcome = only_run(billing_harness)
    assert outcome.status is RunStatus.FAILED
    assert outcome.error == "ConnectionError: database unavailable"
