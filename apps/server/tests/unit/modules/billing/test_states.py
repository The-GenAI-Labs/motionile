import re
from dataclasses import replace
from itertools import product
from pathlib import Path
from uuid import UUID

import pytest
from tests.fakes.billing import FakeBillingStore
from tests.unit.modules.billing.conftest import BillingHarness

from motionile.core.ids import new_id
from motionile.modules.billing.records import NewPayment, NewWebhookEvent
from motionile.modules.billing.states import (
    ORDER_MACHINE,
    PAYMENT_MACHINE,
    RUN_MACHINE,
    WEBHOOK_MACHINE,
    InvalidTransitionError,
    OrderStatus,
    PaymentRecordStatus,
    RefundStatus,
    RunStatus,
    StateMachine,
    SubscriptionStatus,
    WebhookEventStatus,
)
from motionile.modules.billing.transitions import transition_event, transition_order, transition_payment

STATE_MACHINES_DOC = Path(__file__).resolve().parents[6] / "docs" / "db" / "state-machines.md"
EDGE = re.compile(r"^\s*(\[\*\]|\w+) --> (\[\*\]|\w+)")

type Edges = set[tuple[str, str]]


def diagram(section: str) -> tuple[Edges, set[str]]:
    text = STATE_MACHINES_DOC.read_text(encoding="utf-8")
    block = re.search(r"```mermaid\n(.*?)```", text[text.index(f"## `{section}`") :], re.DOTALL)
    assert block is not None
    edges: Edges = set()
    initial: set[str] = set()
    for line in block.group(1).splitlines():
        match = EDGE.match(line)
        if match is None:
            continue
        source, target = match.groups()
        if source == "[*]":
            initial.add(target)
        elif target != "[*]":
            edges.add((source, target))
    return edges, initial


def machine_edges[
    StateT: (OrderStatus, PaymentRecordStatus, WebhookEventStatus, RunStatus, SubscriptionStatus, RefundStatus)
](
    machine: StateMachine[StateT],
) -> Edges:
    return {(source.value, target.value) for source, targets in machine.transitions.items() for target in targets}


@pytest.mark.parametrize(
    ("section", "machine"),
    [
        ("orders.status", ORDER_MACHINE),
        ("payments.status", PAYMENT_MACHINE),
        ("webhook_events.status", WEBHOOK_MACHINE),
        ("billing_reconciliation_runs.status", RUN_MACHINE),
    ],
)
def test_machines_match_the_documented_diagrams(section: str, machine: StateMachine[OrderStatus]) -> None:
    edges, initial = diagram(section)

    assert machine_edges(machine) == edges
    assert {state.value for state in machine.initial} == initial


@pytest.mark.parametrize(("current", "target"), list(product(OrderStatus, OrderStatus)))
def test_every_order_transition_is_allowed_or_rejected_as_documented(current: OrderStatus, target: OrderStatus) -> None:
    edges, _ = diagram("orders.status")

    assert ORDER_MACHINE.allows(current, target) is ((current.value, target.value) in edges)


@pytest.mark.parametrize(("current", "target"), list(product(PaymentRecordStatus, PaymentRecordStatus)))
def test_every_payment_transition_is_allowed_or_rejected_as_documented(
    current: PaymentRecordStatus, target: PaymentRecordStatus
) -> None:
    edges, _ = diagram("payments.status")

    assert PAYMENT_MACHINE.allows(current, target) is ((current.value, target.value) in edges)


@pytest.mark.parametrize(("current", "target"), list(product(WebhookEventStatus, WebhookEventStatus)))
def test_every_webhook_event_transition_is_allowed_or_rejected_as_documented(
    current: WebhookEventStatus, target: WebhookEventStatus
) -> None:
    edges, _ = diagram("webhook_events.status")

    assert WEBHOOK_MACHINE.allows(current, target) is ((current.value, target.value) in edges)


def test_only_paid_orders_are_terminal_among_the_settleable_ones() -> None:
    assert ORDER_MACHINE.terminal(OrderStatus.PAID)
    assert not any(ORDER_MACHINE.terminal(state) for state in OrderStatus if state is not OrderStatus.PAID)


def test_rejected_transitions_name_the_machine_and_both_states() -> None:
    with pytest.raises(InvalidTransitionError, match=r"orders\.status cannot move from paid to pending"):
        ORDER_MACHINE.require(OrderStatus.PAID, OrderStatus.PENDING)


def test_initial_states_are_enforced() -> None:
    ORDER_MACHINE.require_initial(OrderStatus.CREATED)
    PAYMENT_MACHINE.require_initial(PaymentRecordStatus.AUTHORIZED)
    with pytest.raises(InvalidTransitionError):
        ORDER_MACHINE.require_initial(OrderStatus.PAID)
    with pytest.raises(InvalidTransitionError):
        PAYMENT_MACHINE.require_initial(PaymentRecordStatus.REFUNDED)


@pytest.mark.parametrize(("current", "target"), list(product(OrderStatus, OrderStatus)))
async def test_order_transition_function_applies_only_allowed_moves(
    billing_harness: BillingHarness, current: OrderStatus, target: OrderStatus
) -> None:
    order = await billing_harness.local_order()
    billing_harness.billing.orders[order.id] = replace(order, status=current)

    if ORDER_MACHINE.allows(current, target):
        assert await transition_order(billing_harness.billing, order.id, current, target)
        assert billing_harness.billing.orders[order.id].status is target
    else:
        with pytest.raises(InvalidTransitionError):
            await transition_order(billing_harness.billing, order.id, current, target)
        assert billing_harness.billing.orders[order.id].status is current


async def test_order_transition_loses_when_the_expected_status_is_stale(billing_harness: BillingHarness) -> None:
    order = await billing_harness.local_order()
    billing_harness.billing.orders[order.id] = replace(order, status=OrderStatus.PENDING)

    moved = await transition_order(billing_harness.billing, order.id, OrderStatus.CREATED, OrderStatus.FAILED)

    assert moved is False
    assert billing_harness.billing.orders[order.id].status is OrderStatus.PENDING


async def test_order_transition_writes_the_extra_columns(billing_harness: BillingHarness) -> None:
    order = await billing_harness.local_order()

    await transition_order(
        billing_harness.billing,
        order.id,
        OrderStatus.CREATED,
        OrderStatus.FAILED,
        {"failure_reason": "BAD_REQUEST_ERROR"},
    )

    assert billing_harness.billing.orders[order.id].failure_reason == "BAD_REQUEST_ERROR"


async def new_payment(store: FakeBillingStore, order_id: UUID, user_id: UUID, status: PaymentRecordStatus) -> UUID:
    created = await store.insert_payment(
        NewPayment(
            id=new_id(),
            order_id=order_id,
            user_id=user_id,
            razorpay_payment_id=f"pay_{new_id().hex}",
            amount_paise=100,
            currency="INR",
            status=status,
        )
    )
    return created.id


@pytest.mark.parametrize(("current", "target"), list(product(PaymentRecordStatus, PaymentRecordStatus)))
async def test_payment_transition_function_applies_only_allowed_moves(
    billing_harness: BillingHarness, current: PaymentRecordStatus, target: PaymentRecordStatus
) -> None:
    order = await billing_harness.local_order()
    store = billing_harness.billing
    payment_id = await new_payment(store, order.id, order.user_id, current)

    if PAYMENT_MACHINE.allows(current, target):
        assert await transition_payment(store, payment_id, current, target)
        assert store.payments[payment_id].status is target
    else:
        with pytest.raises(InvalidTransitionError):
            await transition_payment(store, payment_id, current, target)
        assert store.payments[payment_id].status is current


@pytest.mark.parametrize(("current", "target"), list(product(WebhookEventStatus, WebhookEventStatus)))
async def test_event_transition_function_applies_only_allowed_moves(
    billing_harness: BillingHarness, current: WebhookEventStatus, target: WebhookEventStatus
) -> None:
    store = billing_harness.billing
    event = NewWebhookEvent(
        id=new_id(),
        provider="razorpay",
        event_id=f"evt_{new_id().hex}",
        event_type="payment.captured",
        event_created_at=None,
        payload={},
        received_at=billing_harness.clock.now(),
    )
    await store.insert_event(event)
    store.events[event.id] = replace(store.events[event.id], status=current)

    if WEBHOOK_MACHINE.allows(current, target):
        assert await transition_event(store, event.id, current, target)
        assert store.events[event.id].status is target
    else:
        with pytest.raises(InvalidTransitionError):
            await transition_event(store, event.id, current, target)
        assert store.events[event.id].status is current
