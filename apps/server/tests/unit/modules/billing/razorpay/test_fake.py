from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from tests.fakes.razorpay import InMemoryFakeRazorpayStore

from motionile.core.clock import FrozenClock
from motionile.modules.billing import (
    RazorpayBadRequestError,
    RazorpayNotFoundError,
    RazorpayServerError,
    RazorpayTimeoutError,
)
from motionile.modules.billing.razorpay.api import PlanParams, PlanPeriod, ScheduleChangeAt
from motionile.modules.billing.razorpay.fake import FakeRazorpay
from motionile.modules.billing.razorpay.fake_entities import add_period, epoch
from motionile.modules.billing.razorpay.fake_simulator import (
    FakeRazorpaySimulator,
    FakeRazorpayStateError,
    PaymentOutcome,
    RefundOutcome,
    SubscriptionEvent,
)
from motionile.modules.billing.razorpay.fake_store import EntityKind, FaultKind, FaultOperation
from motionile.modules.billing.razorpay.models import RazorpayPlan, RazorpaySubscription, RefundStatus

START = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
PLAN = PlanParams(period=PlanPeriod.MONTHLY, interval=1, name="Pro", amount=99_900, currency="INR")


@dataclass
class World:
    fake: FakeRazorpay
    simulator: FakeRazorpaySimulator
    store: InMemoryFakeRazorpayStore
    clock: FrozenClock

    async def subscription(self, total_count: int = 3) -> tuple[RazorpayPlan, RazorpaySubscription]:
        plan = await self.fake.create_plan(PLAN)
        return plan, await self.fake.create_subscription(plan_id=plan.id, total_count=total_count)

    async def active_subscription(self, total_count: int = 3) -> RazorpaySubscription:
        _, created = await self.subscription(total_count)
        await self.simulator.authorize_subscription(created.id)
        await self.simulator.transition_subscription(created.id, SubscriptionEvent.ACTIVATED)
        return await self.fake.fetch_subscription(created.id)

    async def charge(self, subscription_id: str) -> RazorpaySubscription:
        self.clock.advance(timedelta(days=30))
        await self.simulator.transition_subscription(subscription_id, SubscriptionEvent.CHARGED)
        return await self.fake.fetch_subscription(subscription_id)

    async def captured_payment(self, amount: int = 50_000) -> str:
        order = await self.fake.create_order(amount=amount, currency="INR", receipt="rcpt")
        paid = await self.simulator.pay_order(order.id, PaymentOutcome.SUCCESS)
        payment_id: str = paid.payment["id"]
        return payment_id


@pytest.fixture
def world() -> World:
    store = InMemoryFakeRazorpayStore()
    clock = FrozenClock(START)
    return World(FakeRazorpay(store, clock), FakeRazorpaySimulator(store, clock), store, clock)


async def test_ids_have_razorpay_shapes_and_are_unique(world: World) -> None:
    order = await world.fake.create_order(amount=500, currency="INR", receipt="a")
    other = await world.fake.create_order(amount=500, currency="INR", receipt="b")
    customer = await world.fake.create_customer(name="Asha", email="asha@example.com")
    plan, subscription = await world.subscription()
    paid = await world.simulator.pay_order(order.id, PaymentOutcome.SUCCESS)
    refund = await world.fake.create_refund(paid.payment["id"], amount=100)

    prefixes = {
        order.id: "order_",
        customer.id: "cust_",
        plan.id: "plan_",
        subscription.id: "sub_",
        paid.payment["id"]: "pay_",
        refund.id: "rfnd_",
    }
    for identifier, prefix in prefixes.items():
        assert identifier.startswith(prefix)
        assert identifier.removeprefix(prefix).isalnum()
        assert len(identifier) == len(prefix) + 14
    assert order.id != other.id


async def test_order_creation_validates_and_supports_receipt_lookup(world: World) -> None:
    order = await world.fake.create_order(amount=49_900, currency="INR", receipt="rcpt-1", notes={"orderId": "o-1"})

    found = await world.fake.find_order_by_receipt("rcpt-1")
    fetched = await world.fake.fetch_order(order.id)

    assert found == order == fetched
    assert (order.amount, order.amount_due, order.amount_paid, order.status) == (49_900, 49_900, 0, "created")
    assert order.notes == {"orderId": "o-1"}
    assert order.created_at == epoch(START)
    assert await world.fake.find_order_by_receipt("unknown") is None
    with pytest.raises(RazorpayBadRequestError):
        await world.fake.create_order(amount=99, currency="INR", receipt="r")
    with pytest.raises(RazorpayBadRequestError):
        await world.fake.create_order(amount=500, currency="inr", receipt="r")
    with pytest.raises(RazorpayBadRequestError):
        await world.fake.create_order(amount=500, currency="INR", receipt="r" * 41)


async def test_unknown_ids_raise_not_found(world: World) -> None:
    for call in (
        world.fake.fetch_order("order_missing"),
        world.fake.fetch_payment("pay_missing"),
        world.fake.fetch_subscription("sub_missing"),
        world.fake.fetch_refund("rfnd_missing"),
        world.fake.order_payments("order_missing"),
        world.fake.list_payment_refunds("pay_missing"),
        world.fake.cancel_subscription("sub_missing", at_cycle_end=False),
        world.fake.create_refund("pay_missing", amount=100),
    ):
        with pytest.raises(RazorpayNotFoundError):
            await call


async def test_successful_payment_marks_the_order_paid(world: World) -> None:
    order = await world.fake.create_order(amount=50_000, currency="INR", receipt="r")

    paid = await world.simulator.pay_order(order.id, PaymentOutcome.SUCCESS)

    payment = await world.fake.fetch_payment(paid.payment["id"])
    refreshed = await world.fake.fetch_order(order.id)
    assert (payment.status, payment.captured, payment.amount, payment.order_id) == ("captured", True, 50_000, order.id)
    assert payment.is_captured
    assert (refreshed.status, refreshed.amount_paid, refreshed.amount_due, refreshed.attempts) == ("paid", 50_000, 0, 1)
    assert [item.id for item in await world.fake.order_payments(order.id)] == [payment.id]
    with pytest.raises(FakeRazorpayStateError):
        await world.simulator.pay_order(order.id, PaymentOutcome.SUCCESS)


async def test_failed_payment_leaves_the_order_attempted_and_can_be_retried(world: World) -> None:
    order = await world.fake.create_order(amount=50_000, currency="INR", receipt="r")

    failed = await world.simulator.pay_order(order.id, PaymentOutcome.FAILURE)
    retry = await world.simulator.pay_order(order.id, PaymentOutcome.SUCCESS)

    payment = await world.fake.fetch_payment(failed.payment["id"])
    assert (payment.status, payment.captured, payment.error_code) == ("failed", False, "BAD_REQUEST_ERROR")
    assert not payment.is_captured
    assert failed.order["status"] == "attempted"
    assert retry.order["status"] == "paid"
    assert len(await world.fake.order_payments(order.id)) == 2


async def test_authorized_payments_are_not_captured(world: World) -> None:
    order = await world.fake.create_order(amount=50_000, currency="INR", receipt="r")

    authorized = await world.simulator.pay_order(order.id, PaymentOutcome.AUTHORIZED)

    payment = await world.fake.fetch_payment(authorized.payment["id"])
    assert (payment.status, payment.captured) == ("authorized", False)
    assert authorized.order["status"] == "attempted"
    with pytest.raises(RazorpayBadRequestError):
        await world.fake.create_refund(payment.id, amount=100)


async def test_amount_mismatch_can_be_simulated(world: World) -> None:
    order = await world.fake.create_order(amount=50_000, currency="INR", receipt="r")

    paid = await world.simulator.pay_order(order.id, PaymentOutcome.SUCCESS, amount=40_000, currency="USD")

    payment = await world.fake.fetch_payment(paid.payment["id"])
    assert (payment.amount, payment.currency) == (40_000, "USD")
    assert paid.order["status"] == "attempted"
    assert (paid.order["amount_paid"], paid.order["amount_due"]) == (40_000, 10_000)


async def test_customer_creation_is_idempotent_by_email(world: World) -> None:
    first = await world.fake.create_customer(name="Asha", email="Asha@Example.com", contact="+919999999999")
    again = await world.fake.create_customer(name="Asha K", email="asha@example.com")
    other = await world.fake.create_customer(name="Ravi", email="ravi@example.com")
    anonymous_one = await world.fake.create_customer(name="X")
    anonymous_two = await world.fake.create_customer(name="X")

    assert again.id == first.id
    assert len({first.id, other.id, anonymous_one.id, anonymous_two.id}) == 4


async def test_plan_creation_enforces_razorpay_minimums(world: World) -> None:
    plan = await world.fake.create_plan(PLAN)

    assert (plan.period, plan.interval, plan.amount, plan.currency) == ("monthly", 1, 99_900, "INR")
    for params in (
        PlanParams(PlanPeriod.DAILY, 1, "x", 500, "INR"),
        PlanParams(PlanPeriod.MONTHLY, 0, "x", 500, "INR"),
        PlanParams(PlanPeriod.MONTHLY, 1, "x", 99, "INR"),
    ):
        with pytest.raises(RazorpayBadRequestError):
            await world.fake.create_plan(params)
    assert (await world.fake.create_plan(PlanParams(PlanPeriod.DAILY, 7, "x", 500, "INR"))).interval == 7


async def test_subscription_creation_requires_an_existing_plan(world: World) -> None:
    with pytest.raises(RazorpayBadRequestError):
        await world.fake.create_subscription(plan_id="plan_missing", total_count=3)

    _, subscription = await world.subscription(total_count=3)

    assert subscription.status == "created"
    assert (subscription.total_count, subscription.paid_count, subscription.remaining_count) == (3, 0, 3)
    assert subscription.current_start is None
    assert subscription.has_scheduled_changes is False


async def test_authorization_then_activation_opens_the_first_period(world: World) -> None:
    _, created = await world.subscription(total_count=3)

    authorization = await world.simulator.authorize_subscription(created.id)

    assert authorization.subscription["status"] == "authenticated"
    assert authorization.payment["status"] == "captured"
    assert authorization.payment["amount"] == 99_900
    with pytest.raises(FakeRazorpayStateError):
        await world.simulator.authorize_subscription(created.id)

    await world.simulator.transition_subscription(created.id, SubscriptionEvent.ACTIVATED)
    active = await world.fake.fetch_subscription(created.id)

    assert active.status == "active"
    assert active.current_start == epoch(START)
    assert active.current_end == epoch(datetime(2026, 11, 13, 12, 0, tzinfo=UTC))
    assert active.charge_at == active.current_end
    assert (active.paid_count, active.remaining_count, active.total_count) == (1, 2, 3)
    assert active.ended_at is None


async def test_charge_creates_a_payment_for_the_next_contiguous_period(world: World) -> None:
    active = await world.active_subscription(total_count=3)

    charged = await world.charge(active.id)

    assert charged.current_start == active.current_end
    assert charged.current_end == epoch(datetime(2026, 12, 13, 12, 0, tzinfo=UTC))
    assert charged.charge_at == charged.current_end
    assert (charged.paid_count, charged.remaining_count, charged.status) == (2, 1, "active")
    payments = await world.store.members("subscription_payments", active.id)
    assert len(payments) == 2
    assert len(set(payments)) == 2


async def test_final_charge_then_completion(world: World) -> None:
    active = await world.active_subscription(total_count=2)

    with pytest.raises(FakeRazorpayStateError):
        await world.simulator.transition_subscription(active.id, SubscriptionEvent.COMPLETED)
    await world.charge(active.id)
    with pytest.raises(FakeRazorpayStateError):
        await world.simulator.transition_subscription(active.id, SubscriptionEvent.CHARGED)
    completed = await world.simulator.transition_subscription(active.id, SubscriptionEvent.COMPLETED)

    assert completed.subscription["status"] == "completed"
    assert completed.subscription["remaining_count"] == 0
    assert completed.subscription["ended_at"] == epoch(world.clock.now())


async def test_first_charge_from_authenticated_counts_the_authorization_payment(world: World) -> None:
    _, created = await world.subscription()
    authorization = await world.simulator.authorize_subscription(created.id)

    result = await world.simulator.transition_subscription(created.id, SubscriptionEvent.CHARGED)

    assert result.payment is not None
    assert result.payment["id"] == authorization.payment["id"]
    assert (result.subscription["status"], result.subscription["paid_count"]) == ("active", 1)
    assert len(await world.store.members("subscription_payments", created.id)) == 1


async def test_pending_halted_and_recovery(world: World) -> None:
    active = await world.active_subscription()

    pending = await world.simulator.transition_subscription(active.id, SubscriptionEvent.PENDING)
    recovered = await world.charge(active.id)
    await world.simulator.transition_subscription(active.id, SubscriptionEvent.PENDING)
    halted = await world.simulator.transition_subscription(active.id, SubscriptionEvent.HALTED)

    assert pending.subscription["status"] == "pending"
    assert (recovered.status, recovered.paid_count) == ("active", 2)
    assert halted.subscription["status"] == "halted"
    with pytest.raises(FakeRazorpayStateError):
        await world.simulator.transition_subscription(active.id, SubscriptionEvent.CHARGED)
    with pytest.raises(FakeRazorpayStateError):
        await world.simulator.transition_subscription(active.id, SubscriptionEvent.PAUSED)


async def test_pause_and_resume(world: World) -> None:
    active = await world.active_subscription()

    paused = await world.simulator.transition_subscription(active.id, SubscriptionEvent.PAUSED)
    resumed = await world.simulator.transition_subscription(active.id, SubscriptionEvent.RESUMED)

    assert paused.subscription["status"] == "paused"
    assert resumed.subscription["status"] == "active"
    with pytest.raises(FakeRazorpayStateError):
        await world.simulator.transition_subscription(active.id, SubscriptionEvent.RESUMED)


async def test_immediate_cancellation_is_terminal(world: World) -> None:
    active = await world.active_subscription()

    cancelled = await world.fake.cancel_subscription(active.id, at_cycle_end=False)

    assert cancelled.status == "cancelled"
    assert cancelled.ended_at == epoch(START)
    with pytest.raises(RazorpayBadRequestError):
        await world.fake.cancel_subscription(active.id, at_cycle_end=False)
    with pytest.raises(FakeRazorpayStateError):
        await world.simulator.transition_subscription(active.id, SubscriptionEvent.CANCELLED)


async def test_cycle_end_cancellation_keeps_the_subscription_active_until_the_cycle_ends(world: World) -> None:
    active = await world.active_subscription()

    scheduled = await world.fake.cancel_subscription(active.id, at_cycle_end=True)

    assert scheduled.status == "active"
    assert scheduled.has_scheduled_changes
    assert scheduled.change_scheduled_at == active.current_end
    with pytest.raises(FakeRazorpayStateError):
        await world.simulator.transition_subscription(active.id, SubscriptionEvent.CHARGED)
    ended = await world.simulator.transition_subscription(active.id, SubscriptionEvent.CANCELLED)
    assert ended.subscription["status"] == "cancelled"
    assert ended.subscription["has_scheduled_changes"] is False


async def test_cycle_end_cancellation_needs_an_active_subscription(world: World) -> None:
    _, created = await world.subscription()

    with pytest.raises(RazorpayBadRequestError):
        await world.fake.cancel_subscription(created.id, at_cycle_end=True)
    assert (await world.fake.cancel_subscription(created.id, at_cycle_end=False)).status == "cancelled"


async def test_plan_change_at_cycle_end_applies_on_the_next_charge(world: World) -> None:
    active = await world.active_subscription()
    bigger = await world.fake.create_plan(PlanParams(PlanPeriod.MONTHLY, 1, "Max", 199_900, "INR"))

    scheduled = await world.fake.update_subscription(active.id, plan_id=bigger.id)

    assert scheduled.plan_id == active.plan_id
    assert scheduled.has_scheduled_changes
    assert scheduled.change_scheduled_at == active.current_end
    charged = await world.charge(active.id)
    assert charged.plan_id == bigger.id
    assert charged.has_scheduled_changes is False
    assert charged.change_scheduled_at is None
    last_payment_id = (await world.store.members("subscription_payments", active.id))[-1]
    assert (await world.fake.fetch_payment(last_payment_id)).amount == 199_900


async def test_plan_change_now_and_update_restrictions(world: World) -> None:
    active = await world.active_subscription()
    bigger = await world.fake.create_plan(PlanParams(PlanPeriod.MONTHLY, 1, "Max", 199_900, "INR"))

    now = await world.fake.update_subscription(active.id, plan_id=bigger.id, schedule_change_at=ScheduleChangeAt.NOW)

    assert now.plan_id == bigger.id
    assert now.has_scheduled_changes is False
    with pytest.raises(RazorpayBadRequestError):
        await world.fake.update_subscription(active.id, plan_id="plan_missing")
    await world.fake.cancel_subscription(active.id, at_cycle_end=False)
    with pytest.raises(RazorpayBadRequestError):
        await world.fake.update_subscription(active.id, plan_id=bigger.id)


async def test_updated_transition_keeps_state(world: World) -> None:
    active = await world.active_subscription()

    updated = await world.simulator.transition_subscription(active.id, SubscriptionEvent.UPDATED)

    assert updated.subscription == await world.store.get(EntityKind.SUBSCRIPTION, active.id)
    assert (await world.fake.fetch_subscription(active.id)).status == "active"


async def test_refunds_start_pending_and_update_the_payment(world: World) -> None:
    payment_id = await world.captured_payment(50_000)

    partial = await world.fake.create_refund(payment_id, amount=20_000, notes={"refundId": "r-1"}, receipt="r-1")
    after_partial = await world.fake.fetch_payment(payment_id)
    rest = await world.fake.create_refund(payment_id, amount=30_000)
    after_full = await world.fake.fetch_payment(payment_id)

    assert (partial.status, partial.amount, partial.payment_id, partial.notes) == (
        "pending",
        20_000,
        payment_id,
        {"refundId": "r-1"},
    )
    assert (after_partial.status, after_partial.amount_refunded, after_partial.refund_status) == (
        "partially_refunded",
        20_000,
        "partial",
    )
    assert (after_full.status, after_full.amount_refunded, after_full.refund_status) == ("refunded", 50_000, "full")
    refunds = await world.fake.list_payment_refunds(payment_id)
    assert [refund.id for refund in refunds] == [partial.id, rest.id]
    assert next(refund for refund in refunds if refund.notes.get("refundId") == "r-1").id == partial.id
    assert await world.fake.fetch_refund(partial.id) == partial
    with pytest.raises(RazorpayBadRequestError):
        await world.fake.create_refund(payment_id, amount=1)


async def test_refund_amount_is_bounded(world: World) -> None:
    payment_id = await world.captured_payment(50_000)

    for amount in (0, -5, 50_001):
        with pytest.raises(RazorpayBadRequestError):
            await world.fake.create_refund(payment_id, amount=amount)
    await world.fake.create_refund(payment_id, amount=40_000)
    with pytest.raises(RazorpayBadRequestError):
        await world.fake.create_refund(payment_id, amount=10_001)


async def test_settling_refunds(world: World) -> None:
    payment_id = await world.captured_payment(50_000)
    first = await world.fake.create_refund(payment_id, amount=20_000)
    second = await world.fake.create_refund(payment_id, amount=10_000)

    processed = await world.simulator.settle_refund(first.id, RefundOutcome.PROCESSED)
    failed = await world.simulator.settle_refund(second.id, RefundOutcome.FAILED)

    payment = await world.fake.fetch_payment(payment_id)
    assert processed.refund["status"] == "processed"
    assert failed.refund["status"] == "failed"
    assert (payment.status, payment.amount_refunded, payment.refund_status) == ("partially_refunded", 20_000, "partial")
    assert (await world.fake.fetch_refund(second.id)).status == "failed"
    with pytest.raises(FakeRazorpayStateError):
        await world.simulator.settle_refund(first.id, RefundOutcome.PROCESSED)


async def test_failed_only_refund_restores_the_captured_payment(world: World) -> None:
    payment_id = await world.captured_payment(50_000)
    refund = await world.fake.create_refund(payment_id, amount=50_000)

    await world.simulator.settle_refund(refund.id, RefundOutcome.FAILED)

    payment = await world.fake.fetch_payment(payment_id)
    assert (payment.status, payment.amount_refunded, payment.refund_status) == ("captured", 0, None)
    await world.fake.create_refund(payment_id, amount=50_000)


async def test_refunds_can_start_processed() -> None:
    store = InMemoryFakeRazorpayStore()
    clock = FrozenClock(START)
    fake = FakeRazorpay(store, clock, refund_initial_status=RefundStatus.PROCESSED)
    order = await fake.create_order(amount=1_000, currency="INR", receipt="r")
    paid = await FakeRazorpaySimulator(store, clock).pay_order(order.id, PaymentOutcome.SUCCESS)

    refund = await fake.create_refund(paid.payment["id"], amount=500)

    assert refund.status == "processed"


async def test_payment_listing_filters_by_window_orders_newest_first_and_pages(world: World) -> None:
    ids: list[str] = []
    for index in range(5):
        ids.append(await world.captured_payment(10_000 + index))
        world.clock.advance(timedelta(hours=1))
    window_start = START + timedelta(hours=1)
    window_end = START + timedelta(hours=3)

    in_window = await world.fake.list_payments(from_ts=window_start, to_ts=window_end)
    first_page = await world.fake.list_payments(from_ts=START, to_ts=START + timedelta(days=1), count=2)
    second_page = await world.fake.list_payments(from_ts=START, to_ts=START + timedelta(days=1), count=2, skip=2)

    assert [payment.id for payment in in_window] == [ids[3], ids[2], ids[1]]
    assert [payment.id for payment in first_page] == [ids[4], ids[3]]
    assert [payment.id for payment in second_page] == [ids[2], ids[1]]
    for count, skip in ((0, 0), (101, 0), (10, -1)):
        with pytest.raises(RazorpayBadRequestError):
            await world.fake.list_payments(from_ts=START, to_ts=START, count=count, skip=skip)


async def test_timeout_after_create_leaves_the_object_behind(world: World) -> None:
    await world.store.add_fault(FaultOperation.CREATE_ORDER, FaultKind.TIMEOUT_AFTER_CREATE, 1)

    with pytest.raises(RazorpayTimeoutError) as caught:
        await world.fake.create_order(amount=500, currency="INR", receipt="lost")

    assert caught.value.ambiguous
    found = await world.fake.find_order_by_receipt("lost")
    assert found is not None
    assert found.amount == 500
    await world.fake.create_order(amount=500, currency="INR", receipt="fine")


async def test_timeout_before_create_creates_nothing(world: World) -> None:
    await world.store.add_fault(FaultOperation.CREATE_ORDER, FaultKind.TIMEOUT_BEFORE_CREATE, 1)

    with pytest.raises(RazorpayTimeoutError):
        await world.fake.create_order(amount=500, currency="INR", receipt="never")

    assert await world.fake.find_order_by_receipt("never") is None


async def test_server_error_fault_creates_nothing(world: World) -> None:
    await world.store.add_fault(FaultOperation.CREATE_REFUND, FaultKind.SERVER_ERROR, 1)
    payment_id = await world.captured_payment()

    with pytest.raises(RazorpayServerError) as caught:
        await world.fake.create_refund(payment_id, amount=100)

    assert caught.value.status_code == 500
    assert await world.fake.list_payment_refunds(payment_id) == []


async def test_faults_apply_for_a_count_and_only_to_the_chosen_operation(world: World) -> None:
    await world.store.add_fault(FaultOperation.CREATE_ORDER, FaultKind.SERVER_ERROR, 2)

    for receipt in ("a", "b"):
        with pytest.raises(RazorpayServerError):
            await world.fake.create_order(amount=500, currency="INR", receipt=receipt)
    created = await world.fake.create_order(amount=500, currency="INR", receipt="c")

    assert created.receipt == "c"
    assert await world.fake.find_order_by_receipt("a") is None


async def test_fault_on_one_operation_does_not_touch_another(world: World) -> None:
    await world.store.add_fault(FaultOperation.CREATE_PLAN, FaultKind.SERVER_ERROR, 1)

    order = await world.fake.create_order(amount=500, currency="INR", receipt="r")

    assert order.receipt == "r"
    with pytest.raises(RazorpayServerError):
        await world.fake.create_plan(PLAN)


async def test_reset_erases_entities_and_faults(world: World) -> None:
    await world.fake.create_order(amount=500, currency="INR", receipt="r")
    await world.store.add_fault(FaultOperation.CREATE_ORDER, FaultKind.SERVER_ERROR, 5)

    await world.store.reset()

    assert await world.fake.find_order_by_receipt("r") is None
    assert (await world.fake.create_order(amount=500, currency="INR", receipt="r")).receipt == "r"


@pytest.mark.parametrize(
    ("period", "interval", "start", "expected"),
    [
        (PlanPeriod.DAILY, 7, datetime(2026, 10, 13, tzinfo=UTC), datetime(2026, 10, 20, tzinfo=UTC)),
        (PlanPeriod.WEEKLY, 2, datetime(2026, 10, 13, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)),
        (PlanPeriod.MONTHLY, 1, datetime(2026, 1, 31, tzinfo=UTC), datetime(2026, 2, 28, tzinfo=UTC)),
        (PlanPeriod.MONTHLY, 3, datetime(2026, 11, 30, tzinfo=UTC), datetime(2027, 2, 28, tzinfo=UTC)),
        (PlanPeriod.YEARLY, 1, datetime(2028, 2, 29, tzinfo=UTC), datetime(2029, 2, 28, tzinfo=UTC)),
    ],
)
def test_period_arithmetic(period: PlanPeriod, interval: int, start: datetime, expected: datetime) -> None:
    assert add_period(start, period.value, interval) == expected
