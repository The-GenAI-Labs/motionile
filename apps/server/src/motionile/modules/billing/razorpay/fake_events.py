import secrets
from dataclasses import dataclass
from enum import StrEnum

import orjson
from pydantic import SecretStr

from motionile.modules.billing.razorpay.fake_entities import ALPHABET, FAKE_ACCOUNT_ID, require
from motionile.modules.billing.razorpay.fake_store import Entity, EntityKind, FakeRazorpayStore
from motionile.modules.billing.razorpay.signatures import sign_webhook

SIGNATURE_HEADER = "X-Razorpay-Signature"
EVENT_ID_HEADER = "X-Razorpay-Event-Id"
EVENT_ID_RANDOM_LENGTH = 16


class WebhookEventName(StrEnum):
    PAYMENT_CAPTURED = "payment.captured"
    PAYMENT_FAILED = "payment.failed"
    ORDER_PAID = "order.paid"
    REFUND_CREATED = "refund.created"
    REFUND_PROCESSED = "refund.processed"
    REFUND_FAILED = "refund.failed"
    SUBSCRIPTION_ACTIVATED = "subscription.activated"
    SUBSCRIPTION_CHARGED = "subscription.charged"
    SUBSCRIPTION_PENDING = "subscription.pending"
    SUBSCRIPTION_HALTED = "subscription.halted"
    SUBSCRIPTION_CANCELLED = "subscription.cancelled"
    SUBSCRIPTION_COMPLETED = "subscription.completed"
    SUBSCRIPTION_PAUSED = "subscription.paused"
    SUBSCRIPTION_RESUMED = "subscription.resumed"
    SUBSCRIPTION_UPDATED = "subscription.updated"


CONTAINS_BY_EVENT: dict[WebhookEventName, tuple[str, ...]] = {
    WebhookEventName.PAYMENT_CAPTURED: ("payment",),
    WebhookEventName.PAYMENT_FAILED: ("payment",),
    WebhookEventName.ORDER_PAID: ("payment", "order"),
    WebhookEventName.REFUND_CREATED: ("refund", "payment"),
    WebhookEventName.REFUND_PROCESSED: ("refund", "payment"),
    WebhookEventName.REFUND_FAILED: ("refund", "payment"),
    WebhookEventName.SUBSCRIPTION_ACTIVATED: ("subscription",),
    WebhookEventName.SUBSCRIPTION_CHARGED: ("subscription", "payment"),
    WebhookEventName.SUBSCRIPTION_PENDING: ("subscription",),
    WebhookEventName.SUBSCRIPTION_HALTED: ("subscription",),
    WebhookEventName.SUBSCRIPTION_CANCELLED: ("subscription",),
    WebhookEventName.SUBSCRIPTION_COMPLETED: ("subscription",),
    WebhookEventName.SUBSCRIPTION_PAUSED: ("subscription",),
    WebhookEventName.SUBSCRIPTION_RESUMED: ("subscription",),
    WebhookEventName.SUBSCRIPTION_UPDATED: ("subscription",),
}


class MissingWebhookEntityError(ValueError):
    def __init__(self, event: WebhookEventName, entity: str) -> None:
        super().__init__(f"{event.value} needs a {entity}")


@dataclass(frozen=True)
class WebhookEntities:
    payment: Entity | None = None
    order: Entity | None = None
    refund: Entity | None = None
    subscription: Entity | None = None

    def named(self, name: str) -> Entity | None:
        return {
            "payment": self.payment,
            "order": self.order,
            "refund": self.refund,
            "subscription": self.subscription,
        }[name]


@dataclass(frozen=True)
class BuiltWebhook:
    event_id: str
    event: WebhookEventName
    body: bytes
    headers: dict[str, str]


def new_event_id() -> str:
    return "evt_" + "".join(secrets.choice(ALPHABET) for _ in range(EVENT_ID_RANDOM_LENGTH))


def build_envelope(event: WebhookEventName, entities: WebhookEntities, *, created_at: int) -> Entity:
    contains = CONTAINS_BY_EVENT[event]
    payload: Entity = {}
    for name in contains:
        entity = entities.named(name)
        if entity is None:
            raise MissingWebhookEntityError(event, name)
        payload[name] = {"entity": entity}
    return {
        "entity": "event",
        "account_id": FAKE_ACCOUNT_ID,
        "event": event.value,
        "contains": list(contains),
        "payload": payload,
        "created_at": created_at,
    }


def build_webhook(
    event: WebhookEventName,
    entities: WebhookEntities,
    *,
    secret: SecretStr,
    created_at: int,
    event_id: str | None = None,
) -> BuiltWebhook:
    body = orjson.dumps(build_envelope(event, entities, created_at=created_at))
    resolved_id = event_id or new_event_id()
    headers = {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: sign_webhook(body, secret),
        EVENT_ID_HEADER: resolved_id,
    }
    return BuiltWebhook(event_id=resolved_id, event=event, body=body, headers=headers)


@dataclass(frozen=True)
class WebhookReferences:
    order_id: str | None = None
    payment_id: str | None = None
    refund_id: str | None = None
    subscription_id: str | None = None


async def load_entities(
    store: FakeRazorpayStore, event: WebhookEventName, references: WebhookReferences
) -> WebhookEntities:
    contains = CONTAINS_BY_EVENT[event]
    refund = await require(store, EntityKind.REFUND, references.refund_id) if references.refund_id else None
    subscription_id = references.subscription_id
    subscription = await require(store, EntityKind.SUBSCRIPTION, subscription_id) if subscription_id else None
    payment_id = references.payment_id or (refund["payment_id"] if refund else None)
    if payment_id is None and subscription_id and "payment" in contains:
        members = await store.members("subscription_payments", subscription_id)
        payment_id = members[-1] if members else None
    payment = await require(store, EntityKind.PAYMENT, payment_id) if payment_id else None
    order_id = references.order_id or (payment["order_id"] if payment else None)
    order = await require(store, EntityKind.ORDER, order_id) if order_id else None
    return WebhookEntities(payment=payment, order=order, refund=refund, subscription=subscription)
