import itertools
from datetime import timedelta

import pytest
from tests.unit.modules.billing.conftest import BillingHarness
from tests.unit.modules.billing.subscription_support import PLAN_CREDITS, PLAN_PRICE, SubscriptionHarness

from motionile.modules.billing.exceptions import WebhookProcessingError
from motionile.modules.billing.razorpay.fake_events import WebhookEventName
from motionile.modules.billing.razorpay.fake_simulator import SubscriptionEvent
from motionile.modules.billing.razorpay.fake_store import EntityKind
from motionile.modules.billing.records import ProductRecord
from motionile.modules.billing.schemas import SubscriptionCheckoutResponse
from motionile.modules.billing.services.webhook_processor import ProcessingState
from motionile.modules.billing.states import OrderStatus, SubscriptionStatus, WebhookEventStatus


@pytest.fixture
def subscription_harness(billing_harness: BillingHarness) -> SubscriptionHarness:
    return SubscriptionHarness(billing_harness)


def test_every_subscription_and_refund_event_has_a_handler(subscription_harness: SubscriptionHarness) -> None:
    assert subscription_harness.registry.event_types() == {
        "subscription.authenticated",
        "subscription.activated",
        "subscription.charged",
        "subscription.pending",
        "subscription.halted",
        "subscription.cancelled",
        "subscription.completed",
        "subscription.paused",
        "subscription.resumed",
        "subscription.updated",
        "refund.created",
        "refund.processed",
        "refund.failed",
    }


async def started(harness: SubscriptionHarness) -> tuple[ProductRecord, SubscriptionCheckoutResponse]:
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    return plan, checkout


async def test_activation_and_first_charge_activate_grant_and_pay_the_order(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan, checkout = await started(harness)

    payment_id = await harness.activate(checkout)

    subscription = harness.refresh(checkout.subscription_id)
    remote = await harness.remote(checkout.razorpay_subscription_id)
    assert subscription.status is SubscriptionStatus.ACTIVE
    assert subscription.paid_count == 1
    assert subscription.current_period_end == remote.current_end_utc
    assert subscription.current_period_start == remote.current_start_utc
    assert subscription.next_charge_at == remote.charge_at_utc
    assert subscription.last_event_at == harness.base.clock.now()
    [payment] = harness.base.billing.payments.values()
    assert payment.razorpay_payment_id == payment_id
    assert (payment.subscription_id, payment.order_id) == (subscription.id, checkout.order_id)
    assert (payment.amount_paise, payment.credits_granted, payment.status.value) == (
        PLAN_PRICE,
        PLAN_CREDITS,
        "captured",
    )
    order = harness.base.billing.orders[checkout.order_id]
    assert order.status is OrderStatus.PAID
    assert order.paid_at == harness.base.clock.now()
    [lot] = harness.lots()
    assert (lot.source, lot.amount, lot.expires_at, lot.ref_type, lot.ref_id) == (
        "subscription",
        PLAN_CREDITS,
        subscription.current_period_end,
        "payment",
        payment.id,
    )
    assert harness.ledger_keys() == [f"payment:{payment.id}"]
    assert harness.base.balance() == PLAN_CREDITS
    [notice] = harness.base.world.notices
    assert notice.template == "subscription_activated"
    assert notice.user_id == harness.base.user_id
    assert notice.context["plan"] == "Pro"
    assert notice.context["credits"] == str(PLAN_CREDITS)
    assert notice.context["amount"].endswith("incl. GST")
    assert "next_charge" in notice.context
    actions = harness.base.audit_actions()
    assert "billing.subscription.activated" in actions
    assert "billing.subscription.charged" in actions
    assert "billing.order.paid" in actions
    assert plan.id in harness.base.billing.products


async def test_verifying_authenticates_without_granting_and_never_regresses_an_active_subscription(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    authorization, signature = await harness.authorize(checkout.razorpay_subscription_id)
    payment_id = authorization.payment["id"]

    status = await harness.verify(harness.base.user_id, checkout.razorpay_subscription_id, payment_id, signature)

    assert status is SubscriptionStatus.AUTHENTICATED
    assert harness.base.balance() == 0
    assert not harness.lots()
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.ACTIVATED)
    await harness.emit(WebhookEventName.SUBSCRIPTION_ACTIVATED, checkout.razorpay_subscription_id)
    assert harness.refresh(checkout.subscription_id).status is SubscriptionStatus.ACTIVE

    again = await harness.verify(harness.base.user_id, checkout.razorpay_subscription_id, payment_id, signature)

    assert again is SubscriptionStatus.ACTIVE
    assert harness.base.balance() == 0


async def test_renewals_grant_one_lot_per_payment_even_when_events_repeat(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    await harness.activate(checkout)
    harness.base.clock.advance(timedelta(days=30))
    transition = await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.CHARGED)
    assert transition.payment is not None
    payment_id = transition.payment["id"]
    prepared = await harness.prepare(
        WebhookEventName.SUBSCRIPTION_CHARGED, checkout.razorpay_subscription_id, payment_id=payment_id
    )

    first = await harness.deliver(prepared, event_id="evt_renewal_1")
    same_payment_new_event = await harness.deliver(prepared, event_id="evt_renewal_2")
    reprocessed = await harness.processor.process(first.event_row_id, force=True)

    assert first.result.state is ProcessingState.PROCESSED
    assert same_payment_new_event.result.state is ProcessingState.PROCESSED
    assert reprocessed.state is ProcessingState.PROCESSED
    assert harness.base.balance() == 2 * PLAN_CREDITS
    assert len(harness.lots()) == 2
    assert len(harness.base.billing.payments) == 2
    renewal_notices = [item for item in harness.base.world.notices if item.template == "renewal_receipt"]
    assert len(renewal_notices) == 1
    subscription = harness.refresh(checkout.subscription_id)
    assert subscription.paid_count == 2
    assert subscription.status is SubscriptionStatus.ACTIVE
    assert harness.base.billing.orders[checkout.order_id].status is OrderStatus.PAID


async def test_a_charge_that_arrives_before_the_activation_activates_and_the_activation_is_a_no_op(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    authorization, _ = await harness.authorize(checkout.razorpay_subscription_id)
    payment_id = authorization.payment["id"]
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.ACTIVATED)

    charged = await harness.emit(
        WebhookEventName.SUBSCRIPTION_CHARGED, checkout.razorpay_subscription_id, payment_id=payment_id
    )
    activated = await harness.emit(WebhookEventName.SUBSCRIPTION_ACTIVATED, checkout.razorpay_subscription_id)

    assert charged.result.state is ProcessingState.PROCESSED
    assert activated.result.state is ProcessingState.PROCESSED
    assert harness.base.billing.events[activated.event_row_id].status is WebhookEventStatus.PROCESSED
    subscription = harness.refresh(checkout.subscription_id)
    assert subscription.status is SubscriptionStatus.ACTIVE
    assert harness.base.balance() == PLAN_CREDITS


async def test_stale_status_events_are_ignored_but_a_stale_charge_is_still_recorded_and_granted(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    await harness.activate(checkout)
    first_period_end = harness.refresh(checkout.subscription_id).current_period_end
    harness.base.clock.advance(timedelta(days=30))
    renewal = await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.CHARGED)
    assert renewal.payment is not None
    old_pending = await harness.prepare(
        WebhookEventName.SUBSCRIPTION_PENDING,
        checkout.razorpay_subscription_id,
        created_at=harness.base.clock.now() - timedelta(days=1),
    )
    renewal_charged = await harness.prepare(
        WebhookEventName.SUBSCRIPTION_CHARGED,
        checkout.razorpay_subscription_id,
        payment_id=renewal.payment["id"],
        created_at=harness.base.clock.now(),
    )
    paused = await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.PAUSED)
    assert paused.subscription["status"] == "paused"
    paused_event = await harness.prepare(
        WebhookEventName.SUBSCRIPTION_PAUSED,
        checkout.razorpay_subscription_id,
        created_at=harness.base.clock.now() + timedelta(seconds=5),
    )
    await harness.deliver(paused_event)
    before = harness.refresh(checkout.subscription_id)

    stale_pending = await harness.deliver(old_pending)
    stale_charge = await harness.deliver(renewal_charged)

    assert stale_pending.ignored_reason == "stale"
    assert stale_pending.result.state is ProcessingState.IGNORED
    assert stale_charge.ignored_reason == "stale"
    after = harness.refresh(checkout.subscription_id)
    assert after.status is SubscriptionStatus.PAUSED
    assert after.last_event_at == before.last_event_at
    assert after.current_period_end == before.current_period_end
    assert after.current_period_end != first_period_end
    assert harness.base.balance() == 2 * PLAN_CREDITS
    assert len(harness.base.billing.payments) == 2
    assert any(item.template == "renewal_receipt" for item in harness.base.world.notices)


async def test_last_event_time_moves_only_when_an_event_is_applied(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    await harness.activate(checkout)
    applied_at = harness.refresh(checkout.subscription_id).last_event_at
    harness.base.clock.advance(timedelta(hours=1))
    stale = await harness.prepare(
        WebhookEventName.SUBSCRIPTION_UPDATED,
        checkout.razorpay_subscription_id,
        created_at=harness.base.clock.now() - timedelta(days=1),
    )

    delivered = await harness.deliver(stale)

    assert delivered.ignored_reason == "stale"
    assert harness.refresh(checkout.subscription_id).last_event_at == applied_at
    fresh = await harness.emit(WebhookEventName.SUBSCRIPTION_UPDATED, checkout.razorpay_subscription_id)
    assert fresh.result.state is ProcessingState.PROCESSED
    assert harness.refresh(checkout.subscription_id).last_event_at == harness.base.clock.now()


async def test_a_failed_renewal_moves_to_pending_then_halted_and_recovers_on_a_later_charge(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    await harness.activate(checkout)
    harness.base.clock.advance(timedelta(days=30, seconds=1))
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.PENDING)

    pending = await harness.emit(WebhookEventName.SUBSCRIPTION_PENDING, checkout.razorpay_subscription_id)

    assert pending.result.state is ProcessingState.PROCESSED
    assert harness.refresh(checkout.subscription_id).status is SubscriptionStatus.PENDING
    assert harness.base.world.notices[-1].template == "charge_failed"
    harness.base.clock.advance(timedelta(days=1))
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.HALTED)

    halted = await harness.emit(WebhookEventName.SUBSCRIPTION_HALTED, checkout.razorpay_subscription_id)

    assert halted.result.state is ProcessingState.PROCESSED
    assert harness.refresh(checkout.subscription_id).status is SubscriptionStatus.HALTED
    assert harness.base.world.notices[-1].template == "subscription_halted"
    assert harness.base.balance() == PLAN_CREDITS
    assert len(harness.lots()) == 1
    harness.base.clock.advance(timedelta(days=1))
    recovered = await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.CHARGED)
    assert recovered.payment is not None
    await harness.emit(
        WebhookEventName.SUBSCRIPTION_CHARGED, checkout.razorpay_subscription_id, payment_id=recovered.payment["id"]
    )
    assert harness.refresh(checkout.subscription_id).status is SubscriptionStatus.ACTIVE
    assert harness.base.balance() == 2 * PLAN_CREDITS


async def test_halted_arriving_before_the_pending_event_still_halts_and_the_late_pending_is_stale(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    await harness.activate(checkout)
    harness.base.clock.advance(timedelta(days=31))
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.PENDING)
    pending = await harness.prepare(WebhookEventName.SUBSCRIPTION_PENDING, checkout.razorpay_subscription_id)
    harness.base.clock.advance(timedelta(days=1))
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.HALTED)

    await harness.emit(WebhookEventName.SUBSCRIPTION_HALTED, checkout.razorpay_subscription_id)
    late = await harness.deliver(pending)

    assert harness.refresh(checkout.subscription_id).status is SubscriptionStatus.HALTED
    assert late.ignored_reason == "stale"


async def test_pause_and_resume_follow_the_machine(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    await harness.activate(checkout)
    harness.base.clock.advance(timedelta(seconds=1))
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.PAUSED)
    await harness.emit(WebhookEventName.SUBSCRIPTION_PAUSED, checkout.razorpay_subscription_id)
    assert harness.refresh(checkout.subscription_id).status is SubscriptionStatus.PAUSED
    harness.base.clock.advance(timedelta(seconds=1))
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.RESUMED)

    await harness.emit(WebhookEventName.SUBSCRIPTION_RESUMED, checkout.razorpay_subscription_id)

    assert harness.refresh(checkout.subscription_id).status is SubscriptionStatus.ACTIVE


async def test_transitions_the_diagram_does_not_allow_are_ignored_not_forced(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    await harness.activate(checkout)
    harness.base.clock.advance(timedelta(seconds=1))
    prepared = await harness.prepare(WebhookEventName.SUBSCRIPTION_PAUSED, checkout.razorpay_subscription_id)
    harness.set_status(checkout.subscription_id, SubscriptionStatus.HALTED)

    delivered = await harness.deliver(prepared)

    assert delivered.ignored_reason == "invalid_transition"
    assert harness.refresh(checkout.subscription_id).status is SubscriptionStatus.HALTED


async def test_a_repeated_state_is_a_processed_no_op(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    await harness.activate(checkout)
    harness.base.clock.advance(timedelta(days=31))
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.PENDING)
    await harness.emit(WebhookEventName.SUBSCRIPTION_PENDING, checkout.razorpay_subscription_id)
    harness.base.clock.advance(timedelta(seconds=1))

    again = await harness.emit(WebhookEventName.SUBSCRIPTION_PENDING, checkout.razorpay_subscription_id)

    assert again.result.state is ProcessingState.PROCESSED
    assert harness.refresh(checkout.subscription_id).status is SubscriptionStatus.PENDING
    assert [item.template for item in harness.base.world.notices].count("charge_failed") == 1


async def test_cancellation_with_a_paid_period_left_waits_for_the_period_end(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    await harness.activate(checkout)
    harness.base.clock.advance(timedelta(days=1))
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.CANCELLED)

    delivered = await harness.emit(WebhookEventName.SUBSCRIPTION_CANCELLED, checkout.razorpay_subscription_id)

    assert delivered.result.state is ProcessingState.PROCESSED
    subscription = harness.refresh(checkout.subscription_id)
    assert subscription.status is SubscriptionStatus.ACTIVE
    assert subscription.cancel_at_period_end is True
    assert subscription.cancelled_at is not None
    assert subscription.ended_at is None
    assert harness.base.world.notices[-1].template == "cancellation_scheduled"
    assert "billing.subscription.cancel_scheduled" in harness.base.audit_actions()


async def test_cancellation_without_a_paid_period_ends_the_subscription_at_once(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    authorization, _ = await harness.authorize(checkout.razorpay_subscription_id)
    await harness.verify(harness.base.user_id, checkout.razorpay_subscription_id, authorization.payment["id"])
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.CANCELLED)

    delivered = await harness.emit(WebhookEventName.SUBSCRIPTION_CANCELLED, checkout.razorpay_subscription_id)

    assert delivered.result.state is ProcessingState.PROCESSED
    subscription = harness.refresh(checkout.subscription_id)
    assert subscription.status is SubscriptionStatus.CANCELLED
    assert subscription.ended_at is not None
    assert subscription.cancel_at_period_end is True
    assert harness.base.world.notices[-1].template == "subscription_ended"


async def test_cancellation_after_the_period_has_passed_ends_the_subscription_at_once(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    await harness.activate(checkout)
    harness.base.clock.advance(timedelta(days=45))
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.CANCELLED)

    await harness.emit(WebhookEventName.SUBSCRIPTION_CANCELLED, checkout.razorpay_subscription_id)

    subscription = harness.refresh(checkout.subscription_id)
    assert subscription.status is SubscriptionStatus.CANCELLED
    assert subscription.ended_at == harness.base.clock.now()


async def test_a_cancellation_already_scheduled_by_the_user_sends_no_second_email(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    await harness.activate(checkout)
    harness.set_status(
        checkout.subscription_id,
        SubscriptionStatus.ACTIVE,
        cancel_at_period_end=True,
        cancelled_at=harness.base.clock.now(),
    )
    harness.base.clock.advance(timedelta(days=1))
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.CANCELLED)
    before = len(harness.base.world.notices)

    await harness.emit(WebhookEventName.SUBSCRIPTION_CANCELLED, checkout.razorpay_subscription_id)

    assert len(harness.base.world.notices) == before


async def test_completion_ends_the_subscription(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)
    entity = await harness.stored(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id)
    entity["total_count"] = 1
    await harness.base.razorpay_store.put(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id, entity)
    harness.base.clock.advance(timedelta(seconds=1))
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.COMPLETED)

    delivered = await harness.emit(WebhookEventName.SUBSCRIPTION_COMPLETED, checkout.razorpay_subscription_id)

    assert delivered.result.state is ProcessingState.PROCESSED
    subscription = harness.refresh(checkout.subscription_id)
    assert subscription.status is SubscriptionStatus.COMPLETED
    assert subscription.ended_at is not None


async def test_a_new_subscription_can_start_after_the_previous_one_ended(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan, checkout = await started(harness)
    await harness.activate(checkout)

    harness.set_status(checkout.subscription_id, SubscriptionStatus.CANCELLED, ended_at=harness.base.clock.now())
    second = await harness.subscribe(plan)

    assert second.subscription_id != checkout.subscription_id


async def test_updated_applies_an_immediate_plan_change_and_clears_the_pending_one(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan, checkout = await started(harness)
    bigger = await harness.add_plan(price=199_900, credit_amount=1_500, name="Max")
    await harness.activate(checkout)
    harness.set_status(checkout.subscription_id, SubscriptionStatus.ACTIVE, pending_product_id=bigger.id)
    entity = await harness.stored(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id)
    entity["plan_id"] = bigger.razorpay_plan_id
    await harness.base.razorpay_store.put(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id, entity)
    harness.base.clock.advance(timedelta(seconds=1))

    delivered = await harness.emit(WebhookEventName.SUBSCRIPTION_UPDATED, checkout.razorpay_subscription_id)

    assert delivered.result.state is ProcessingState.PROCESSED
    subscription = harness.refresh(checkout.subscription_id)
    assert subscription.product_id == bigger.id
    assert subscription.pending_product_id is None
    assert subscription.status is SubscriptionStatus.ACTIVE
    assert plan.id != bigger.id


async def test_a_renewal_on_the_scheduled_plan_switches_the_product_and_grants_its_credits(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan, checkout = await started(harness)
    bigger = await harness.add_plan(price=199_900, credit_amount=1_500, name="Max")
    await harness.activate(checkout)
    harness.set_status(checkout.subscription_id, SubscriptionStatus.ACTIVE, pending_product_id=bigger.id)
    await harness.base.razorpay.update_subscription(
        checkout.razorpay_subscription_id, plan_id=bigger.razorpay_plan_id or ""
    )

    await harness.renew(checkout)

    subscription = harness.refresh(checkout.subscription_id)
    assert subscription.product_id == bigger.id
    assert subscription.pending_product_id is None
    assert harness.base.balance() == PLAN_CREDITS + 1_500
    renewal = [lot for lot in harness.lots() if lot.amount == 1_500]
    assert len(renewal) == 1
    last = harness.base.world.notices[-1]
    assert (last.template, last.context["plan"], last.context["credits"]) == ("renewal_receipt", "Max", "1500")
    assert plan.id in harness.base.billing.products


async def test_a_charge_with_the_wrong_amount_is_recorded_but_grants_nothing(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    authorization, _ = await harness.authorize(checkout.razorpay_subscription_id)
    payment = await harness.stored(EntityKind.PAYMENT, authorization.payment["id"])
    payment["amount"] = PLAN_PRICE - 1
    await harness.base.razorpay_store.put(EntityKind.PAYMENT, payment["id"], payment)
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.ACTIVATED)

    delivered = await harness.emit(
        WebhookEventName.SUBSCRIPTION_CHARGED, checkout.razorpay_subscription_id, payment_id=payment["id"]
    )

    assert delivered.result.state is ProcessingState.PROCESSED
    [recorded] = harness.base.billing.payments.values()
    assert (recorded.amount_paise, recorded.credits_granted) == (PLAN_PRICE - 1, 0)
    assert harness.base.balance() == 0
    assert not harness.lots()
    order = harness.base.billing.orders[checkout.order_id]
    assert order.flag_reason == "amount_mismatch"
    assert order.status is not OrderStatus.PAID
    assert [code for code, _ in harness.base.world.alerts] == ["billing.payment_mismatch"]
    assert "billing.payment.flagged" in harness.base.audit_actions()
    assert harness.refresh(checkout.subscription_id).status is SubscriptionStatus.ACTIVE
    assert not harness.base.world.notices


async def test_the_rollover_setting_makes_subscription_credits_non_expiring(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    harness.rollover = True
    _, checkout = await started(harness)

    await harness.activate(checkout)

    [lot] = harness.lots()
    assert lot.expires_at is None
    assert lot.source == "subscription"


async def test_events_for_unknown_subscriptions_are_ignored_and_unknown_charges_alert(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    authorization, _ = await harness.authorize(checkout.razorpay_subscription_id)
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.ACTIVATED)
    entity = await harness.stored(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id)
    entity["notes"] = {}
    await harness.base.razorpay_store.put(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id, entity)
    harness.patch(checkout.subscription_id, razorpay_subscription_id="sub_other")

    activated = await harness.emit(WebhookEventName.SUBSCRIPTION_ACTIVATED, checkout.razorpay_subscription_id)
    charged = await harness.emit(
        WebhookEventName.SUBSCRIPTION_CHARGED,
        checkout.razorpay_subscription_id,
        payment_id=authorization.payment["id"],
    )

    assert activated.ignored_reason == "unknown_entity"
    assert charged.ignored_reason == "unknown_entity"
    assert ("billing.unknown_subscription_charge", {"event_row_id": str(charged.event_row_id)}) in (
        harness.base.world.alerts
    )
    assert harness.base.balance() == 0


async def test_an_event_that_beat_the_local_attachment_finds_the_subscription_through_the_notes(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    harness.patch(checkout.subscription_id, razorpay_subscription_id=None)
    await harness.authorize(checkout.razorpay_subscription_id)
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.ACTIVATED)

    delivered = await harness.emit(WebhookEventName.SUBSCRIPTION_ACTIVATED, checkout.razorpay_subscription_id)

    assert delivered.result.state is ProcessingState.PROCESSED
    subscription = harness.refresh(checkout.subscription_id)
    assert subscription.razorpay_subscription_id == checkout.razorpay_subscription_id
    assert subscription.status is SubscriptionStatus.ACTIVE


async def test_a_charge_on_an_ended_subscription_grants_the_credits_and_raises_an_alert(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    harness.set_status(checkout.subscription_id, SubscriptionStatus.EXPIRED, ended_at=harness.base.clock.now())
    authorization, _ = await harness.authorize(checkout.razorpay_subscription_id)
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.ACTIVATED)
    harness.base.clock.advance(timedelta(seconds=1))

    delivered = await harness.emit(
        WebhookEventName.SUBSCRIPTION_CHARGED,
        checkout.razorpay_subscription_id,
        payment_id=authorization.payment["id"],
    )

    assert delivered.result.state is ProcessingState.PROCESSED
    assert harness.refresh(checkout.subscription_id).status is SubscriptionStatus.EXPIRED
    assert harness.base.balance() == PLAN_CREDITS
    assert "billing.charge_on_ended_subscription" in [code for code, _ in harness.base.world.alerts]


async def test_two_live_subscriptions_for_one_user_alert_instead_of_activating_the_second(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan, first = await started(harness)
    second = await harness.subscribe(plan)
    await harness.activate(first)
    await harness.authorize(second.razorpay_subscription_id)
    await harness.advance(second.razorpay_subscription_id, SubscriptionEvent.ACTIVATED)

    delivered = await harness.emit(WebhookEventName.SUBSCRIPTION_ACTIVATED, second.razorpay_subscription_id)

    assert delivered.ignored_reason == "duplicate_live_subscription"
    assert harness.refresh(second.subscription_id).status is SubscriptionStatus.CREATED
    assert "billing.duplicate_live_subscription" in [code for code, _ in harness.base.world.alerts]


EVENT_COUNT = 6


async def play_in_order(order: tuple[int, ...]) -> tuple[str, int, int, list[str]]:
    base = BillingHarness()
    harness = SubscriptionHarness(base)
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    remote_id = checkout.razorpay_subscription_id
    authorization, signature = await harness.authorize(remote_id)
    first_payment = authorization.payment["id"]
    base.clock.advance(timedelta(seconds=1))
    await harness.advance(remote_id, SubscriptionEvent.ACTIVATED)
    activated = await harness.prepare(WebhookEventName.SUBSCRIPTION_ACTIVATED, remote_id)
    charged_first = await harness.prepare(WebhookEventName.SUBSCRIPTION_CHARGED, remote_id, payment_id=first_payment)
    base.clock.advance(timedelta(seconds=1))
    updated = await harness.prepare(WebhookEventName.SUBSCRIPTION_UPDATED, remote_id)
    base.clock.advance(timedelta(days=30, seconds=1))
    await harness.advance(remote_id, SubscriptionEvent.PENDING)
    pending = await harness.prepare(WebhookEventName.SUBSCRIPTION_PENDING, remote_id)
    base.clock.advance(timedelta(seconds=1))
    renewal = await harness.advance(remote_id, SubscriptionEvent.CHARGED)
    assert renewal.payment is not None
    charged_renewal = await harness.prepare(
        WebhookEventName.SUBSCRIPTION_CHARGED, remote_id, payment_id=renewal.payment["id"]
    )
    base.clock.advance(timedelta(seconds=1))
    verify_payment = first_payment

    async def verify() -> None:
        await harness.verify(base.user_id, remote_id, verify_payment, signature)

    steps = [activated, charged_first, updated, pending, charged_renewal]
    for index in order:
        if index == EVENT_COUNT - 1:
            await verify()
        else:
            await harness.deliver(steps[index])
    subscription = harness.refresh(checkout.subscription_id)
    return subscription.status.value, base.balance(), len(harness.lots()), sorted(harness.ledger_keys())


@pytest.mark.parametrize("order", list(itertools.permutations(range(EVENT_COUNT)))[::7])
async def test_every_arrival_order_reaches_the_same_state_and_grants_each_payment_once(
    order: tuple[int, ...],
) -> None:
    status, balance, lot_count, keys = await play_in_order(order)

    assert status == "active"
    assert balance == 2 * PLAN_CREDITS
    assert lot_count == 2
    assert len(keys) == len(set(keys)) == 2


async def test_a_charge_without_a_known_period_is_retried_instead_of_granting_a_non_expiring_lot(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    authorization, _ = await harness.authorize(checkout.razorpay_subscription_id)
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.ACTIVATED)
    entity = await harness.stored(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id)
    entity["current_end"] = None
    await harness.base.razorpay_store.put(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id, entity)
    prepared = await harness.prepare(
        WebhookEventName.SUBSCRIPTION_CHARGED,
        checkout.razorpay_subscription_id,
        payment_id=authorization.payment["id"],
    )

    with pytest.raises(WebhookProcessingError):
        await harness.deliver(prepared)

    assert not harness.base.billing.payments
    assert not harness.lots()
    assert harness.base.billing.events[next(iter(harness.base.billing.events))].status is WebhookEventStatus.FAILED
    harness.rollover = True
    retry = await harness.processor.process(next(iter(harness.base.billing.events)))
    assert retry.state is ProcessingState.PROCESSED
    [lot] = harness.lots()
    assert lot.expires_at is None


async def test_a_charge_for_a_period_that_is_already_over_grants_nothing_records_the_payment_and_alerts(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    _, checkout = await started(harness)
    authorization, _ = await harness.authorize(checkout.razorpay_subscription_id)
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.ACTIVATED)
    now = harness.base.clock.now()
    entity = await harness.stored(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id)
    entity["current_start"] = int((now - timedelta(days=40)).timestamp())
    entity["current_end"] = int((now - timedelta(days=10)).timestamp())
    await harness.base.razorpay_store.put(EntityKind.SUBSCRIPTION, checkout.razorpay_subscription_id, entity)

    delivered = await harness.emit(
        WebhookEventName.SUBSCRIPTION_CHARGED,
        checkout.razorpay_subscription_id,
        payment_id=authorization.payment["id"],
    )

    assert delivered.result.state is ProcessingState.PROCESSED
    [payment] = harness.base.billing.payments.values()
    assert (payment.credits_granted, payment.status.value) == (0, "captured")
    assert not harness.lots()
    assert harness.base.balance() == 0
    assert "billing.subscription.charge_expired" in harness.base.audit_actions()
    assert "billing.subscription_charge_expired" in [code for code, _ in harness.base.world.alerts]
    assert harness.base.billing.orders[checkout.order_id].status is OrderStatus.PAID
    assert not harness.base.world.notices
