from collections.abc import Mapping
from uuid import UUID

from motionile.modules.billing.repository import BillingStore
from motionile.modules.billing.states import (
    ORDER_MACHINE,
    PAYMENT_MACHINE,
    WEBHOOK_MACHINE,
    OrderStatus,
    PaymentRecordStatus,
    WebhookEventStatus,
)

NO_VALUES: Mapping[str, object] = {}


async def transition_order(
    store: BillingStore,
    order_id: UUID,
    expected: OrderStatus,
    target: OrderStatus,
    values: Mapping[str, object] = NO_VALUES,
) -> bool:
    ORDER_MACHINE.require(expected, target)
    return await store.transition_order(order_id, expected, target, values)


async def transition_payment(
    store: BillingStore,
    payment_id: UUID,
    expected: PaymentRecordStatus,
    target: PaymentRecordStatus,
    values: Mapping[str, object] = NO_VALUES,
) -> bool:
    PAYMENT_MACHINE.require(expected, target)
    return await store.transition_payment(payment_id, expected, target, values)


async def transition_event(
    store: BillingStore,
    event_row_id: UUID,
    expected: WebhookEventStatus,
    target: WebhookEventStatus,
    values: Mapping[str, object] = NO_VALUES,
) -> bool:
    WEBHOOK_MACHINE.require(expected, target)
    return await store.transition_event(event_row_id, expected, target, values)
