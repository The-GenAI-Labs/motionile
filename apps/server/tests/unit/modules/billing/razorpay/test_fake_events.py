from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import orjson
import pytest
from pydantic import SecretStr
from tests.fakes.razorpay import InMemoryFakeRazorpayStore

from motionile.core.clock import FrozenClock
from motionile.modules.billing import verify_webhook_signature
from motionile.modules.billing.razorpay.api import PlanParams, PlanPeriod
from motionile.modules.billing.razorpay.fake import FakeRazorpay
from motionile.modules.billing.razorpay.fake_events import (
    CONTAINS_BY_EVENT,
    EVENT_ID_HEADER,
    SIGNATURE_HEADER,
    MissingWebhookEntityError,
    WebhookEventName,
    WebhookReferences,
    build_envelope,
    build_webhook,
    load_entities,
)
from motionile.modules.billing.razorpay.fake_simulator import (
    FakeRazorpaySimulator,
    PaymentOutcome,
    SubscriptionEvent,
)
from motionile.modules.billing.razorpay.models import (
    RazorpayOrder,
    RazorpayPayment,
    RazorpayRefund,
    RazorpaySubscription,
)

SECRET = SecretStr("whsec_events_secret_0123456789")
CREATED_AT = 1_790_000_000
MODEL_BY_ENTITY: dict[str, Any] = {
    "payment": RazorpayPayment,
    "order": RazorpayOrder,
    "refund": RazorpayRefund,
    "subscription": RazorpaySubscription,
}


@dataclass
class Scenario:
    store: InMemoryFakeRazorpayStore
    references: WebhookReferences


@pytest.fixture
async def scenario() -> Scenario:
    store = InMemoryFakeRazorpayStore()
    clock = FrozenClock(datetime(2026, 10, 13, 12, 0, tzinfo=UTC))
    fake = FakeRazorpay(store, clock)
    simulator = FakeRazorpaySimulator(store, clock)
    order = await fake.create_order(amount=50_000, currency="INR", receipt="r")
    paid = await simulator.pay_order(order.id, PaymentOutcome.SUCCESS)
    refund = await fake.create_refund(paid.payment["id"], amount=1_000)
    plan = await fake.create_plan(PlanParams(PlanPeriod.MONTHLY, 1, "Pro", 99_900, "INR"))
    subscription = await fake.create_subscription(plan_id=plan.id, total_count=3)
    await simulator.authorize_subscription(subscription.id)
    await simulator.transition_subscription(subscription.id, SubscriptionEvent.CHARGED)
    return Scenario(
        store,
        WebhookReferences(
            order_id=order.id,
            payment_id=paid.payment["id"],
            refund_id=refund.id,
            subscription_id=subscription.id,
        ),
    )


def references_for(event: WebhookEventName, scenario: Scenario) -> WebhookReferences:
    references = scenario.references
    if event.value.startswith("subscription."):
        return WebhookReferences(subscription_id=references.subscription_id)
    if event.value.startswith("refund."):
        return WebhookReferences(refund_id=references.refund_id)
    if event is WebhookEventName.ORDER_PAID:
        return WebhookReferences(order_id=references.order_id, payment_id=references.payment_id)
    return WebhookReferences(payment_id=references.payment_id)


@pytest.mark.parametrize("event", list(WebhookEventName))
async def test_every_event_builds_a_signed_razorpay_envelope(event: WebhookEventName, scenario: Scenario) -> None:
    entities = await load_entities(scenario.store, event, references_for(event, scenario))

    webhook = build_webhook(event, entities, secret=SECRET, created_at=CREATED_AT, event_id="evt_fixed_1")

    envelope = orjson.loads(webhook.body)
    assert list(envelope) == ["entity", "account_id", "event", "contains", "payload", "created_at"]
    assert envelope["entity"] == "event"
    assert envelope["account_id"].startswith("acc_")
    assert envelope["event"] == event.value
    assert envelope["created_at"] == CREATED_AT
    assert envelope["contains"] == list(CONTAINS_BY_EVENT[event])
    assert set(envelope["payload"]) == set(CONTAINS_BY_EVENT[event])
    for name, wrapper in envelope["payload"].items():
        assert list(wrapper) == ["entity"]
        parsed = MODEL_BY_ENTITY[name].model_validate(wrapper["entity"])
        assert parsed.id.startswith(
            {"payment": "pay_", "order": "order_", "refund": "rfnd_", "subscription": "sub_"}[name]
        )
    assert webhook.headers[EVENT_ID_HEADER] == "evt_fixed_1"
    assert webhook.headers["Content-Type"] == "application/json"
    assert verify_webhook_signature(webhook.body, webhook.headers[SIGNATURE_HEADER], SECRET)
    assert not verify_webhook_signature(webhook.body, webhook.headers[SIGNATURE_HEADER], SecretStr("other-secret"))


async def test_subscription_charged_carries_subscription_and_payment(scenario: Scenario) -> None:
    event = WebhookEventName.SUBSCRIPTION_CHARGED
    entities = await load_entities(
        scenario.store, event, WebhookReferences(subscription_id=scenario.references.subscription_id)
    )

    envelope = build_envelope(event, entities, created_at=CREATED_AT)

    assert envelope["contains"] == ["subscription", "payment"]
    assert envelope["payload"]["subscription"]["entity"]["id"] == scenario.references.subscription_id
    assert envelope["payload"]["payment"]["entity"]["status"] == "captured"
    assert envelope["payload"]["payment"]["entity"]["order_id"].startswith("order_")


async def test_refund_events_include_their_payment(scenario: Scenario) -> None:
    entities = await load_entities(
        scenario.store, WebhookEventName.REFUND_PROCESSED, WebhookReferences(refund_id=scenario.references.refund_id)
    )

    envelope = build_envelope(WebhookEventName.REFUND_PROCESSED, entities, created_at=CREATED_AT)

    assert envelope["payload"]["refund"]["entity"]["payment_id"] == envelope["payload"]["payment"]["entity"]["id"]
    assert envelope["payload"]["payment"]["entity"]["amount_refunded"] == 1_000


async def test_order_paid_resolves_the_order_from_the_payment(scenario: Scenario) -> None:
    entities = await load_entities(
        scenario.store, WebhookEventName.ORDER_PAID, WebhookReferences(payment_id=scenario.references.payment_id)
    )

    envelope = build_envelope(WebhookEventName.ORDER_PAID, entities, created_at=CREATED_AT)

    assert envelope["payload"]["order"]["entity"]["id"] == scenario.references.order_id
    assert envelope["payload"]["order"]["entity"]["status"] == "paid"


async def test_generated_event_ids_are_unique(scenario: Scenario) -> None:
    entities = await load_entities(
        scenario.store, WebhookEventName.PAYMENT_CAPTURED, references_for(WebhookEventName.PAYMENT_CAPTURED, scenario)
    )

    ids = {
        build_webhook(WebhookEventName.PAYMENT_CAPTURED, entities, secret=SECRET, created_at=CREATED_AT).event_id
        for _ in range(50)
    }

    assert len(ids) == 50
    assert all(event_id.startswith("evt_") for event_id in ids)


async def test_missing_entities_are_reported(scenario: Scenario) -> None:
    entities = await load_entities(scenario.store, WebhookEventName.PAYMENT_CAPTURED, WebhookReferences())

    with pytest.raises(MissingWebhookEntityError, match=r"payment.captured needs a payment"):
        build_envelope(WebhookEventName.PAYMENT_CAPTURED, entities, created_at=CREATED_AT)
