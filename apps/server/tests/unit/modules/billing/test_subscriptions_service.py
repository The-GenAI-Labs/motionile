from dataclasses import replace
from datetime import timedelta

import pytest
from tests.unit.modules.billing.conftest import BillingHarness
from tests.unit.modules.billing.subscription_support import (
    KEY_ID,
    PLAN_CREDITS,
    PLAN_PRICE,
    SubscriptionHarness,
)

from motionile.core.idempotency import IdempotencyKeyReusedError
from motionile.core.ids import new_id
from motionile.modules.billing.exceptions import (
    InvalidPaymentSignatureError,
    OrderNotPayableError,
    PaymentProviderRejectedError,
    PaymentProviderUnavailableError,
    ProductNotFoundError,
    ProductNotPurchasableError,
    SubscriptionExistsError,
    SubscriptionNotChangeableError,
    SubscriptionNotFoundError,
)
from motionile.modules.billing.razorpay.fake_simulator import SubscriptionEvent
from motionile.modules.billing.razorpay.fake_store import EntityKind, FaultKind, FaultOperation
from motionile.modules.billing.records import NewOrder
from motionile.modules.billing.states import OrderStatus, SubscriptionStatus


@pytest.fixture
def subscription_harness(billing_harness: BillingHarness) -> SubscriptionHarness:
    return SubscriptionHarness(billing_harness)


def remote_subscriptions(harness: SubscriptionHarness) -> list[str]:
    return [entity_id for kind, entity_id in harness.base.razorpay_store.entities if kind is EntityKind.SUBSCRIPTION]


async def test_creating_a_subscription_returns_checkout_data_without_a_client_amount(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()

    checkout = await harness.subscribe(plan)

    subscription = harness.local(checkout)
    order = harness.base.billing.orders[checkout.order_id]
    assert subscription.status is SubscriptionStatus.CREATED
    assert subscription.razorpay_subscription_id == checkout.razorpay_subscription_id
    assert subscription.product_id == plan.id
    assert subscription.total_count == harness.base.settings.subscription_total_count
    assert (order.kind, order.status, order.subscription_id) == ("subscription", OrderStatus.PENDING, subscription.id)
    assert (order.amount_paise, order.credits_granted, order.currency) == (PLAN_PRICE, PLAN_CREDITS, "INR")
    assert order.razorpay_order_id is None
    assert checkout.key_id == KEY_ID
    assert (checkout.name, checkout.description) == ("Motionile", "Pro")
    assert checkout.customer_id == harness.base.billing.customers[harness.base.user_id].razorpay_customer_id
    assert checkout.prefill.email == "asha@example.com"
    remote = await harness.remote(checkout.razorpay_subscription_id)
    assert remote.plan_id == plan.razorpay_plan_id
    assert remote.total_count == subscription.total_count
    assert remote.customer_notify is False
    assert remote.notes == {
        "userId": str(harness.base.user_id),
        "orderId": str(order.id),
        "subscriptionId": str(subscription.id),
    }
    assert "billing.subscription.created" in harness.base.audit_actions()


async def test_repeating_the_request_returns_the_same_checkout_without_a_second_remote_subscription(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    first = await harness.checkout.create(harness.base.user_id, plan.code, "key-1")

    second = await harness.checkout.create(harness.base.user_id, plan.code, "key-1")

    assert second == first
    assert len(remote_subscriptions(harness)) == 1
    assert len(harness.base.billing.subscriptions) == 1


async def test_reusing_a_key_for_another_product_or_a_credit_pack_order_is_refused(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    other = await harness.add_plan(name="Max")
    await harness.checkout.create(harness.base.user_id, plan.code, "key-1")

    with pytest.raises(IdempotencyKeyReusedError):
        await harness.checkout.create(harness.base.user_id, other.code, "key-1")

    order = await harness.base.billing.insert_order(
        NewOrder(
            new_id(),
            harness.base.user_id,
            harness.base.product,
            "pack-key",
            harness.base.clock.now() + timedelta(hours=1),
        )
    )
    assert order is not None
    with pytest.raises(IdempotencyKeyReusedError):
        await harness.checkout.create(harness.base.user_id, plan.code, "pack-key")


async def test_only_active_subscription_plans_can_be_bought_this_way(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    inactive = harness.base.billing.add_product(replace(await harness.add_plan(name="Old"), is_active=False))
    without_plan = harness.base.billing.add_product(replace(await harness.add_plan(name="Odd"), razorpay_plan_id=None))

    with pytest.raises(ProductNotFoundError):
        await harness.checkout.create(harness.base.user_id, "missing", "key-1")
    with pytest.raises(ProductNotFoundError):
        await harness.checkout.create(harness.base.user_id, inactive.code, "key-2")
    with pytest.raises(ProductNotPurchasableError):
        await harness.checkout.create(harness.base.user_id, harness.base.product.code, "key-3")
    with pytest.raises(ProductNotPurchasableError):
        await harness.checkout.create(harness.base.user_id, without_plan.code, "key-4")
    assert not harness.base.billing.subscriptions
    assert not remote_subscriptions(harness)
    assert plan.is_active


@pytest.mark.parametrize(
    "status",
    [
        SubscriptionStatus.AUTHENTICATED,
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.PENDING,
        SubscriptionStatus.HALTED,
        SubscriptionStatus.PAUSED,
    ],
)
async def test_a_user_with_a_live_subscription_cannot_start_another(
    subscription_harness: SubscriptionHarness, status: SubscriptionStatus
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    first = await harness.subscribe(plan)
    harness.set_status(first.subscription_id, status)

    with pytest.raises(SubscriptionExistsError) as raised:
        await harness.subscribe(plan)

    assert raised.value.code == "subscription_exists"
    assert len(harness.base.billing.subscriptions) == 1


@pytest.mark.parametrize(
    "status", [SubscriptionStatus.CANCELLED, SubscriptionStatus.COMPLETED, SubscriptionStatus.EXPIRED]
)
async def test_a_user_can_subscribe_again_once_the_previous_subscription_ended(
    subscription_harness: SubscriptionHarness, status: SubscriptionStatus
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    first = await harness.subscribe(plan)
    harness.set_status(first.subscription_id, status, ended_at=harness.base.clock.now())

    second = await harness.subscribe(plan)

    assert second.subscription_id != first.subscription_id


async def test_an_abandoned_checkout_does_not_block_a_new_attempt(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    await harness.subscribe(plan)

    second = await harness.subscribe(plan)

    assert second.razorpay_subscription_id
    assert len(harness.base.billing.subscriptions) == 2


async def test_a_timeout_after_the_remote_creation_is_recovered_by_the_notes_lookup(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    await harness.base.razorpay_store.add_fault(FaultOperation.CREATE_SUBSCRIPTION, FaultKind.TIMEOUT_AFTER_CREATE, 1)

    checkout = await harness.subscribe(plan)

    assert len(remote_subscriptions(harness)) == 1
    assert harness.local(checkout).razorpay_subscription_id == checkout.razorpay_subscription_id
    assert harness.base.billing.orders[checkout.order_id].status is OrderStatus.PENDING


async def test_a_timeout_before_the_remote_creation_fails_then_the_retry_creates_exactly_one(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    await harness.base.razorpay_store.add_fault(FaultOperation.CREATE_SUBSCRIPTION, FaultKind.TIMEOUT_BEFORE_CREATE, 1)

    with pytest.raises(PaymentProviderUnavailableError):
        await harness.checkout.create(harness.base.user_id, plan.code, "key-1")
    [pending] = harness.base.billing.subscriptions.values()
    assert pending.razorpay_subscription_id is None

    checkout = await harness.checkout.create(harness.base.user_id, plan.code, "key-1")

    assert checkout.subscription_id == pending.id
    assert len(remote_subscriptions(harness)) == 1
    assert len(harness.base.billing.subscriptions) == 1


async def test_a_listing_failure_during_recovery_is_a_provider_error_not_a_duplicate(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    await harness.base.razorpay_store.add_fault(FaultOperation.CREATE_SUBSCRIPTION, FaultKind.TIMEOUT_AFTER_CREATE, 1)
    await harness.base.razorpay_store.add_fault(FaultOperation.LIST_SUBSCRIPTIONS, FaultKind.SERVER_ERROR, 1)

    with pytest.raises(PaymentProviderUnavailableError):
        await harness.checkout.create(harness.base.user_id, plan.code, "key-1")

    checkout = await harness.checkout.create(harness.base.user_id, plan.code, "key-1")

    assert len(remote_subscriptions(harness)) == 1
    assert checkout.razorpay_subscription_id == remote_subscriptions(harness)[0]


async def test_a_rejected_remote_creation_fails_the_order_and_expires_the_subscription(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    harness.base.billing.products[plan.id] = replace(plan, razorpay_plan_id="plan_does_not_exist")

    with pytest.raises(PaymentProviderRejectedError):
        await harness.checkout.create(harness.base.user_id, plan.code, "key-1")

    [subscription] = harness.base.billing.subscriptions.values()
    [order] = harness.base.billing.orders.values()
    assert subscription.status is SubscriptionStatus.EXPIRED
    assert subscription.ended_at is not None
    assert order.status is OrderStatus.FAILED
    assert order.failure_reason
    with pytest.raises(OrderNotPayableError):
        await harness.checkout.create(harness.base.user_id, plan.code, "key-1")


async def test_verifying_authenticates_the_callers_subscription_and_grants_nothing(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    authorization, signature = await harness.authorize(checkout.razorpay_subscription_id)

    status = await harness.verify(
        harness.base.user_id, checkout.razorpay_subscription_id, authorization.payment["id"], signature
    )
    again = await harness.verify(
        harness.base.user_id, checkout.razorpay_subscription_id, authorization.payment["id"], signature
    )

    assert status is again is SubscriptionStatus.AUTHENTICATED
    assert harness.base.balance() == 0
    assert not harness.base.billing.payments
    assert harness.base.audit_actions().count("billing.subscription.authenticated") == 1


async def test_a_tampered_signature_is_refused(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    authorization, _ = await harness.authorize(checkout.razorpay_subscription_id)

    with pytest.raises(InvalidPaymentSignatureError):
        await harness.verify(
            harness.base.user_id,
            checkout.razorpay_subscription_id,
            authorization.payment["id"],
            "0" * 64,
        )

    assert harness.local(checkout).status is SubscriptionStatus.CREATED


async def test_another_user_cannot_verify_a_subscription_they_do_not_own(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    authorization, signature = await harness.authorize(checkout.razorpay_subscription_id)

    with pytest.raises(SubscriptionNotFoundError):
        await harness.verify(new_id(), checkout.razorpay_subscription_id, authorization.payment["id"], signature)

    assert harness.local(checkout).status is SubscriptionStatus.CREATED


async def test_verifying_an_unauthorized_subscription_leaves_it_created(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)

    status = await harness.verify(harness.base.user_id, checkout.razorpay_subscription_id, "pay_never")

    assert status is SubscriptionStatus.CREATED


async def test_no_current_subscription_until_the_mandate_is_authenticated(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    assert await harness.management.current(harness.base.user_id) is None

    await harness.activate(checkout)
    view = await harness.management.current(harness.base.user_id)

    assert view is not None
    assert view.subscription.status is SubscriptionStatus.ACTIVE
    assert view.product.code == plan.code
    assert view.pending_product is None
    assert await harness.management.current(new_id()) is None


async def test_cancelling_an_unpaid_authenticated_subscription_ends_it_immediately(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    authorization, _ = await harness.authorize(checkout.razorpay_subscription_id)
    await harness.verify(harness.base.user_id, checkout.razorpay_subscription_id, authorization.payment["id"])

    view = await harness.management.cancel(harness.base.user_id)

    subscription = harness.local(checkout)
    assert subscription.status is SubscriptionStatus.CANCELLED
    assert subscription.cancel_at_period_end is True
    assert subscription.ended_at == harness.base.clock.now()
    assert view.subscription.status is SubscriptionStatus.CANCELLED
    assert (await harness.remote(checkout.razorpay_subscription_id)).status == "cancelled"
    assert harness.base.world.notices[-1].template == "subscription_ended"
    assert "billing.subscription.cancel_requested" in harness.base.audit_actions()


async def test_cancelling_an_active_subscription_waits_for_the_period_end_and_is_idempotent(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)
    notices_before = len(harness.base.world.notices)

    first = await harness.management.cancel(harness.base.user_id)
    second = await harness.management.cancel(harness.base.user_id)

    subscription = harness.local(checkout)
    assert subscription.status is SubscriptionStatus.ACTIVE
    assert subscription.cancel_at_period_end is True
    assert subscription.cancelled_at == harness.base.clock.now()
    assert first.subscription.cancel_at_period_end
    assert second.subscription.cancel_at_period_end
    remote = await harness.remote(checkout.razorpay_subscription_id)
    assert remote.status == "active"
    assert remote.has_scheduled_changes is True
    assert len(harness.base.world.notices) == notices_before + 1
    assert harness.base.world.notices[-1].template == "cancellation_scheduled"
    assert harness.base.audit_actions().count("billing.subscription.cancel_requested") == 1


async def test_cancelling_needs_a_live_subscription_and_never_touches_someone_elses(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)

    with pytest.raises(SubscriptionNotFoundError):
        await harness.management.cancel(new_id())

    assert harness.local(checkout).cancel_at_period_end is False
    assert (await harness.remote(checkout.razorpay_subscription_id)).has_scheduled_changes is False


async def test_a_provider_outage_leaves_the_subscription_unchanged_and_retryable(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)
    await harness.base.razorpay_store.add_fault(FaultOperation.CANCEL_SUBSCRIPTION, FaultKind.TIMEOUT_BEFORE_CREATE, 1)

    with pytest.raises(PaymentProviderUnavailableError):
        await harness.management.cancel(harness.base.user_id)

    assert harness.local(checkout).cancel_at_period_end is False
    await harness.management.cancel(harness.base.user_id)
    assert harness.local(checkout).cancel_at_period_end is True


async def test_a_cancellation_the_provider_already_applied_is_accepted(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    authorization, _ = await harness.authorize(checkout.razorpay_subscription_id)
    await harness.verify(harness.base.user_id, checkout.razorpay_subscription_id, authorization.payment["id"])
    await harness.advance(checkout.razorpay_subscription_id, SubscriptionEvent.CANCELLED)

    view = await harness.management.cancel(harness.base.user_id)

    assert view.subscription.status is SubscriptionStatus.CANCELLED


async def test_a_plan_change_is_scheduled_for_the_next_cycle(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    bigger = await harness.add_plan(price=199_900, credit_amount=1_500, name="Max")
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)

    view = await harness.management.change(harness.base.user_id, bigger.code)

    subscription = harness.local(checkout)
    assert subscription.product_id == plan.id
    assert subscription.pending_product_id == bigger.id
    assert view.pending_product is not None
    assert view.pending_product.code == bigger.code
    remote = await harness.remote(checkout.razorpay_subscription_id)
    assert remote.plan_id == plan.razorpay_plan_id
    assert remote.has_scheduled_changes is True
    assert "billing.subscription.change_scheduled" in harness.base.audit_actions()
    again = await harness.management.change(harness.base.user_id, bigger.code)
    assert again.pending_product is not None


@pytest.mark.parametrize(
    "status",
    [
        SubscriptionStatus.AUTHENTICATED,
        SubscriptionStatus.PENDING,
        SubscriptionStatus.HALTED,
        SubscriptionStatus.PAUSED,
    ],
)
async def test_only_an_active_subscription_can_change_plan(
    subscription_harness: SubscriptionHarness, status: SubscriptionStatus
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    bigger = await harness.add_plan(price=199_900, credit_amount=1_500, name="Max")
    checkout = await harness.subscribe(plan)
    harness.set_status(checkout.subscription_id, status)

    with pytest.raises(SubscriptionNotChangeableError) as raised:
        await harness.management.change(harness.base.user_id, bigger.code)

    assert raised.value.code == "subscription_not_changeable"


async def test_a_subscription_that_is_ending_cannot_change_plan(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    bigger = await harness.add_plan(price=199_900, credit_amount=1_500, name="Max")
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)
    await harness.management.cancel(harness.base.user_id)

    with pytest.raises(SubscriptionNotChangeableError):
        await harness.management.change(harness.base.user_id, bigger.code)


async def test_the_target_plan_must_be_a_different_active_plan_in_the_same_currency(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    dollars = harness.base.billing.add_product(replace(await harness.add_plan(name="Usd"), currency="USD"))
    retired = harness.base.billing.add_product(replace(await harness.add_plan(name="Old"), is_active=False))
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)

    with pytest.raises(SubscriptionNotChangeableError):
        await harness.management.change(harness.base.user_id, plan.code)
    with pytest.raises(SubscriptionNotChangeableError):
        await harness.management.change(harness.base.user_id, dollars.code)
    with pytest.raises(ProductNotFoundError):
        await harness.management.change(harness.base.user_id, retired.code)
    with pytest.raises(ProductNotFoundError):
        await harness.management.change(harness.base.user_id, "missing")
    with pytest.raises(ProductNotPurchasableError):
        await harness.management.change(harness.base.user_id, harness.base.product.code)
    assert harness.local(checkout).pending_product_id is None


async def test_another_user_cannot_change_a_plan_they_do_not_have(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    bigger = await harness.add_plan(price=199_900, credit_amount=1_500, name="Max")
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)

    with pytest.raises(SubscriptionNotFoundError):
        await harness.management.change(new_id(), bigger.code)

    assert harness.local(checkout).pending_product_id is None
    assert (await harness.remote(checkout.razorpay_subscription_id)).has_scheduled_changes is False


async def test_a_rejected_plan_change_is_reported_and_not_stored(subscription_harness: SubscriptionHarness) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    bigger = await harness.add_plan(price=199_900, credit_amount=1_500, name="Max")
    harness.base.billing.products[bigger.id] = replace(bigger, razorpay_plan_id="plan_does_not_exist")
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)

    with pytest.raises(PaymentProviderRejectedError):
        await harness.management.change(harness.base.user_id, bigger.code)

    assert harness.local(checkout).pending_product_id is None


async def test_the_whole_flow_from_checkout_to_renewal_and_back_to_a_clean_state(
    subscription_harness: SubscriptionHarness,
) -> None:
    harness = subscription_harness
    plan = await harness.add_plan()
    checkout = await harness.subscribe(plan)
    await harness.activate(checkout)
    await harness.renew(checkout)
    await harness.management.cancel(harness.base.user_id)

    harness.base.clock.advance(timedelta(days=40))
    counts = await harness.finalizer.finalize()

    assert counts.cancelled == 1
    assert harness.local(checkout).status is SubscriptionStatus.CANCELLED
    assert await harness.management.current(harness.base.user_id) is None
    assert harness.base.balance() == 2 * PLAN_CREDITS
