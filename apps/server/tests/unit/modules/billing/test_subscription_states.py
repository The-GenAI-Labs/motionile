from dataclasses import replace
from itertools import pairwise, product

import pytest
from tests.unit.modules.billing.conftest import BillingHarness
from tests.unit.modules.billing.subscription_support import SubscriptionHarness
from tests.unit.modules.billing.test_states import diagram, machine_edges

from motionile.core.ids import new_id
from motionile.modules.billing.exceptions import LiveSubscriptionConflictError
from motionile.modules.billing.records import NewRefund
from motionile.modules.billing.states import (
    ENDED_SUBSCRIPTION_STATUSES,
    LIVE_SUBSCRIPTION_STATUSES,
    REFUND_MACHINE,
    RUN_MACHINE,
    SUBSCRIPTION_MACHINE,
    InvalidTransitionError,
    RefundStatus,
    RunStatus,
    SubscriptionStatus,
)
from motionile.modules.billing.transitions import transition_refund, transition_subscription


@pytest.fixture
def subscription_harness(billing_harness: BillingHarness) -> SubscriptionHarness:
    return SubscriptionHarness(billing_harness)


def test_the_subscription_machine_matches_the_documented_diagram() -> None:
    edges, initial = diagram("subscriptions.status")

    assert machine_edges(SUBSCRIPTION_MACHINE) == edges
    assert {state.value for state in SUBSCRIPTION_MACHINE.initial} == initial


def test_the_refund_machine_matches_the_documented_diagram() -> None:
    edges, initial = diagram("refunds.status")

    assert machine_edges(REFUND_MACHINE) == edges
    assert {state.value for state in REFUND_MACHINE.initial} == initial


def test_the_run_machine_allows_a_failed_run_to_resume() -> None:
    assert RUN_MACHINE.allows(RunStatus.FAILED, RunStatus.RUNNING)
    assert not RUN_MACHINE.allows(RunStatus.COMPLETED, RunStatus.RUNNING)


@pytest.mark.parametrize(("current", "target"), list(product(SubscriptionStatus, SubscriptionStatus)))
def test_every_subscription_transition_is_allowed_or_rejected_as_documented(
    current: SubscriptionStatus, target: SubscriptionStatus
) -> None:
    edges, _ = diagram("subscriptions.status")

    assert SUBSCRIPTION_MACHINE.allows(current, target) is ((current.value, target.value) in edges)


@pytest.mark.parametrize(("current", "target"), list(product(RefundStatus, RefundStatus)))
def test_every_refund_transition_is_allowed_or_rejected_as_documented(
    current: RefundStatus, target: RefundStatus
) -> None:
    edges, _ = diagram("refunds.status")

    assert REFUND_MACHINE.allows(current, target) is ((current.value, target.value) in edges)


def test_ended_subscriptions_are_terminal_and_live_ones_are_not() -> None:
    assert all(SUBSCRIPTION_MACHINE.terminal(state) for state in ENDED_SUBSCRIPTION_STATUSES)
    assert not any(SUBSCRIPTION_MACHINE.terminal(state) for state in LIVE_SUBSCRIPTION_STATUSES)
    assert SUBSCRIPTION_MACHINE.terminal(SubscriptionStatus.EXPIRED)


def test_paths_walk_only_allowed_edges_and_never_backwards() -> None:
    assert SUBSCRIPTION_MACHINE.path(SubscriptionStatus.PENDING, SubscriptionStatus.COMPLETED) == (
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.COMPLETED,
    )
    assert SUBSCRIPTION_MACHINE.path(SubscriptionStatus.ACTIVE, SubscriptionStatus.ACTIVE) == ()
    assert SUBSCRIPTION_MACHINE.path(SubscriptionStatus.ACTIVE, SubscriptionStatus.AUTHENTICATED) is None
    assert SUBSCRIPTION_MACHINE.path(SubscriptionStatus.CANCELLED, SubscriptionStatus.ACTIVE) is None
    for current, target in product(SubscriptionStatus, SubscriptionStatus):
        route = SUBSCRIPTION_MACHINE.path(current, target)
        if route:
            hops = [current, *route]
            assert all(SUBSCRIPTION_MACHINE.allows(a, b) for a, b in pairwise(hops))


@pytest.mark.parametrize(("current", "target"), list(product(SubscriptionStatus, SubscriptionStatus)))
async def test_subscription_transition_function_applies_only_allowed_moves(
    subscription_harness: SubscriptionHarness, current: SubscriptionStatus, target: SubscriptionStatus
) -> None:
    product_record = await subscription_harness.add_plan()
    store = subscription_harness.base.billing
    checkout = await subscription_harness.subscribe(product_record)
    subscription = subscription_harness.set_status(
        checkout.subscription_id,
        current,
        ended_at=subscription_harness.base.clock.now() if current in ENDED_SUBSCRIPTION_STATUSES else None,
    )
    values = {"ended_at": subscription_harness.base.clock.now()} if target in ENDED_SUBSCRIPTION_STATUSES else {}

    if SUBSCRIPTION_MACHINE.allows(current, target):
        assert await transition_subscription(store, subscription.id, current, target, values)
        assert store.subscriptions[subscription.id].status is target
    else:
        with pytest.raises(InvalidTransitionError):
            await transition_subscription(store, subscription.id, current, target, values)
        assert store.subscriptions[subscription.id].status is current


async def test_a_second_live_subscription_for_one_user_is_refused_by_the_store(
    subscription_harness: SubscriptionHarness,
) -> None:
    plan = await subscription_harness.add_plan()
    store = subscription_harness.base.billing
    first = await subscription_harness.subscribe(plan)
    second = await subscription_harness.subscribe(plan)
    subscription_harness.set_status(first.subscription_id, SubscriptionStatus.ACTIVE)

    with pytest.raises(LiveSubscriptionConflictError):
        await transition_subscription(
            store, second.subscription_id, SubscriptionStatus.CREATED, SubscriptionStatus.AUTHENTICATED
        )


@pytest.mark.parametrize(("current", "target"), list(product(RefundStatus, RefundStatus)))
async def test_refund_transition_function_applies_only_allowed_moves(
    subscription_harness: SubscriptionHarness, current: RefundStatus, target: RefundStatus
) -> None:
    store = subscription_harness.base.billing
    refund = await store.insert_refund(NewRefund(new_id(), new_id(), 100, "reason", None, "k-state"))
    store.refunds[refund.id] = replace(refund, status=current)

    if REFUND_MACHINE.allows(current, target):
        assert await transition_refund(store, refund.id, current, target)
        assert store.refunds[refund.id].status is target
    else:
        with pytest.raises(InvalidTransitionError):
            await transition_refund(store, refund.id, current, target)
