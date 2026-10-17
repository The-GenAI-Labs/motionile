from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class OrderStatus(StrEnum):
    CREATED = "created"
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class PaymentRecordStatus(StrEnum):
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class WebhookEventStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    IGNORED = "ignored"


class RunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class InvalidTransitionError(Exception):
    def __init__(self, machine: str, current: str, target: str) -> None:
        super().__init__(f"{machine} cannot move from {current} to {target}")
        self.machine = machine
        self.current = current
        self.target = target


@dataclass(frozen=True)
class StateMachine[StateT: StrEnum]:
    name: str
    transitions: Mapping[StateT, frozenset[StateT]]
    initial: frozenset[StateT]

    def allows(self, current: StateT, target: StateT) -> bool:
        return target in self.transitions.get(current, frozenset())

    def allows_initial(self, target: StateT) -> bool:
        return target in self.initial

    def require(self, current: StateT, target: StateT) -> None:
        if not self.allows(current, target):
            raise InvalidTransitionError(self.name, current.value, target.value)

    def require_initial(self, target: StateT) -> None:
        if not self.allows_initial(target):
            raise InvalidTransitionError(self.name, "none", target.value)

    def terminal(self, state: StateT) -> bool:
        return not self.transitions.get(state)


LATE_PAYMENT_ORIGINS = frozenset({OrderStatus.EXPIRED, OrderStatus.FAILED, OrderStatus.CANCELLED})
PAYABLE_ORDER_STATUSES = frozenset({OrderStatus.CREATED, OrderStatus.PENDING, *LATE_PAYMENT_ORIGINS})

ORDER_MACHINE = StateMachine[OrderStatus](
    name="orders.status",
    transitions={
        OrderStatus.CREATED: frozenset(
            {OrderStatus.PENDING, OrderStatus.FAILED, OrderStatus.EXPIRED, OrderStatus.PAID}
        ),
        OrderStatus.PENDING: frozenset(
            {OrderStatus.PAID, OrderStatus.FAILED, OrderStatus.EXPIRED, OrderStatus.CANCELLED}
        ),
        OrderStatus.EXPIRED: frozenset({OrderStatus.PAID}),
        OrderStatus.FAILED: frozenset({OrderStatus.PAID}),
        OrderStatus.CANCELLED: frozenset({OrderStatus.PAID}),
        OrderStatus.PAID: frozenset(),
    },
    initial=frozenset({OrderStatus.CREATED}),
)

PAYMENT_MACHINE = StateMachine[PaymentRecordStatus](
    name="payments.status",
    transitions={
        PaymentRecordStatus.AUTHORIZED: frozenset({PaymentRecordStatus.CAPTURED, PaymentRecordStatus.FAILED}),
        PaymentRecordStatus.CAPTURED: frozenset({PaymentRecordStatus.PARTIALLY_REFUNDED, PaymentRecordStatus.REFUNDED}),
        PaymentRecordStatus.PARTIALLY_REFUNDED: frozenset(
            {PaymentRecordStatus.PARTIALLY_REFUNDED, PaymentRecordStatus.REFUNDED}
        ),
        PaymentRecordStatus.FAILED: frozenset(),
        PaymentRecordStatus.REFUNDED: frozenset(),
    },
    initial=frozenset({PaymentRecordStatus.AUTHORIZED, PaymentRecordStatus.CAPTURED, PaymentRecordStatus.FAILED}),
)

WEBHOOK_MACHINE = StateMachine[WebhookEventStatus](
    name="webhook_events.status",
    transitions={
        WebhookEventStatus.RECEIVED: frozenset({WebhookEventStatus.PROCESSING}),
        WebhookEventStatus.PROCESSING: frozenset(
            {WebhookEventStatus.PROCESSED, WebhookEventStatus.IGNORED, WebhookEventStatus.FAILED}
        ),
        WebhookEventStatus.FAILED: frozenset({WebhookEventStatus.PROCESSING}),
        WebhookEventStatus.PROCESSED: frozenset({WebhookEventStatus.PROCESSING}),
        WebhookEventStatus.IGNORED: frozenset({WebhookEventStatus.PROCESSING}),
    },
    initial=frozenset({WebhookEventStatus.RECEIVED}),
)

RUN_MACHINE = StateMachine[RunStatus](
    name="billing_reconciliation_runs.status",
    transitions={
        RunStatus.RUNNING: frozenset({RunStatus.COMPLETED, RunStatus.FAILED}),
        RunStatus.COMPLETED: frozenset(),
        RunStatus.FAILED: frozenset(),
    },
    initial=frozenset({RunStatus.RUNNING}),
)

REPROCESSABLE_EVENT_STATUSES = frozenset(
    {WebhookEventStatus.FAILED, WebhookEventStatus.PROCESSED, WebhookEventStatus.IGNORED}
)
