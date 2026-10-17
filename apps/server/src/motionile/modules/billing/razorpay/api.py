from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from motionile.modules.billing.razorpay.models import (
    RazorpayCustomer,
    RazorpayOrder,
    RazorpayPayment,
    RazorpayPlan,
    RazorpayRefund,
    RazorpaySubscription,
)

MAX_LIST_COUNT = 100


class PlanPeriod(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


@dataclass(frozen=True)
class PlanParams:
    period: PlanPeriod
    interval: int
    name: str
    amount: int
    currency: str
    description: str | None = None
    notes: Mapping[str, str] | None = None


class ScheduleChangeAt(StrEnum):
    NOW = "now"
    CYCLE_END = "cycle_end"


class RazorpayApi(Protocol):
    async def create_order(
        self, *, amount: int, currency: str, receipt: str, notes: Mapping[str, str] | None = None
    ) -> RazorpayOrder: ...

    async def fetch_order(self, order_id: str) -> RazorpayOrder: ...

    async def find_order_by_receipt(self, receipt: str) -> RazorpayOrder | None: ...

    async def order_payments(self, order_id: str) -> list[RazorpayPayment]: ...

    async def fetch_payment(self, payment_id: str) -> RazorpayPayment: ...

    async def list_payments(
        self, *, from_ts: datetime, to_ts: datetime, count: int = MAX_LIST_COUNT, skip: int = 0
    ) -> list[RazorpayPayment]: ...

    async def create_customer(
        self, *, name: str, email: str | None = None, contact: str | None = None, notes: Mapping[str, str] | None = None
    ) -> RazorpayCustomer: ...

    async def create_plan(self, plan: PlanParams) -> RazorpayPlan: ...

    async def create_subscription(
        self,
        *,
        plan_id: str,
        total_count: int,
        notes: Mapping[str, str] | None = None,
        customer_notify: bool = True,
    ) -> RazorpaySubscription: ...

    async def fetch_subscription(self, subscription_id: str) -> RazorpaySubscription: ...

    async def cancel_subscription(self, subscription_id: str, *, at_cycle_end: bool) -> RazorpaySubscription: ...

    async def update_subscription(
        self, subscription_id: str, *, plan_id: str, schedule_change_at: ScheduleChangeAt = ScheduleChangeAt.CYCLE_END
    ) -> RazorpaySubscription: ...

    async def create_refund(
        self,
        payment_id: str,
        *,
        amount: int,
        notes: Mapping[str, str] | None = None,
        receipt: str | None = None,
    ) -> RazorpayRefund: ...

    async def fetch_refund(self, refund_id: str) -> RazorpayRefund: ...

    async def list_payment_refunds(self, payment_id: str) -> list[RazorpayRefund]: ...
