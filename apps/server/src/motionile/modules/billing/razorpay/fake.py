from collections.abc import Mapping
from datetime import datetime

from motionile.core.clock import Clock
from motionile.modules.billing.razorpay.api import MAX_LIST_COUNT, PlanParams, PlanPeriod, ScheduleChangeAt
from motionile.modules.billing.razorpay.exceptions import RazorpayServerError, RazorpayTimeoutError
from motionile.modules.billing.razorpay.fake_entities import (
    MINIMUM_ORDER_AMOUNT,
    CustomerSpec,
    OrderSpec,
    RefundSpec,
    SubscriptionSpec,
    bad_request,
    customer_entity,
    epoch,
    new_entity_id,
    order_entity,
    plan_entity,
    refund_entity,
    require,
    subscription_entity,
)
from motionile.modules.billing.razorpay.fake_store import (
    Entity,
    EntityKind,
    FakeRazorpayStore,
    FaultKind,
    FaultOperation,
)
from motionile.modules.billing.razorpay.models import (
    PaymentStatus,
    RazorpayCustomer,
    RazorpayOrder,
    RazorpayPayment,
    RazorpayPlan,
    RazorpayRefund,
    RazorpaySubscription,
    RefundStatus,
    SubscriptionStatus,
)

MAX_RECEIPT_LENGTH = 40
CURRENCY_LENGTH = 3
MINIMUM_DAILY_INTERVAL = 7
CANCELLABLE = frozenset(
    {
        SubscriptionStatus.CREATED,
        SubscriptionStatus.AUTHENTICATED,
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.PENDING,
        SubscriptionStatus.HALTED,
        SubscriptionStatus.PAUSED,
    }
)
UPDATABLE = frozenset({SubscriptionStatus.AUTHENTICATED, SubscriptionStatus.ACTIVE})
REFUNDABLE = frozenset({PaymentStatus.CAPTURED, PaymentStatus.PARTIALLY_REFUNDED})


class FakeRazorpay:
    def __init__(
        self,
        store: FakeRazorpayStore,
        clock: Clock,
        *,
        refund_initial_status: RefundStatus = RefundStatus.PENDING,
    ) -> None:
        self.store = store
        self.clock = clock
        self.refund_initial_status = refund_initial_status

    async def _begin(self, operation: FaultOperation) -> FaultKind | None:
        fault = await self.store.take_fault(operation)
        if fault is FaultKind.TIMEOUT_BEFORE_CREATE:
            raise RazorpayTimeoutError("injected timeout before the operation")
        if fault is FaultKind.SERVER_ERROR:
            raise RazorpayServerError(500, code="SERVER_ERROR", description="injected server error")
        return fault

    @staticmethod
    def _finish(fault: FaultKind | None) -> None:
        if fault is FaultKind.TIMEOUT_AFTER_CREATE:
            raise RazorpayTimeoutError("injected timeout after the operation")

    async def create_order(
        self, *, amount: int, currency: str, receipt: str, notes: Mapping[str, str] | None = None
    ) -> RazorpayOrder:
        fault = await self._begin(FaultOperation.CREATE_ORDER)
        if amount < MINIMUM_ORDER_AMOUNT:
            raise bad_request("Order amount less than minimum amount allowed", "amount")
        if len(currency) != CURRENCY_LENGTH or not currency.isupper():
            raise bad_request("Currency is invalid", "currency")
        if len(receipt) > MAX_RECEIPT_LENGTH:
            raise bad_request("receipt: the length must be no more than 40.", "receipt")
        order_id = await new_entity_id(self.store, "order")
        entity = order_entity(order_id, self.clock.now(), OrderSpec(amount, currency, receipt, notes))
        await self.store.put(EntityKind.ORDER, order_id, entity)
        await self.store.set_index("receipt", receipt, order_id)
        self._finish(fault)
        return RazorpayOrder.model_validate(entity)

    async def fetch_order(self, order_id: str) -> RazorpayOrder:
        fault = await self._begin(FaultOperation.FETCH_ORDER)
        entity = await require(self.store, EntityKind.ORDER, order_id)
        self._finish(fault)
        return RazorpayOrder.model_validate(entity)

    async def find_order_by_receipt(self, receipt: str) -> RazorpayOrder | None:
        fault = await self._begin(FaultOperation.FIND_ORDER_BY_RECEIPT)
        order_id = await self.store.lookup("receipt", receipt)
        entity = await self.store.get(EntityKind.ORDER, order_id) if order_id is not None else None
        self._finish(fault)
        return RazorpayOrder.model_validate(entity) if entity is not None else None

    async def _payments_of(self, ids: list[str]) -> list[Entity]:
        entities = [await self.store.get(EntityKind.PAYMENT, payment_id) for payment_id in ids]
        return [entity for entity in entities if entity is not None]

    async def order_payments(self, order_id: str) -> list[RazorpayPayment]:
        fault = await self._begin(FaultOperation.ORDER_PAYMENTS)
        await require(self.store, EntityKind.ORDER, order_id)
        entities = await self._payments_of(await self.store.members("order_payments", order_id))
        self._finish(fault)
        return [RazorpayPayment.model_validate(entity) for entity in entities]

    async def fetch_payment(self, payment_id: str) -> RazorpayPayment:
        fault = await self._begin(FaultOperation.FETCH_PAYMENT)
        entity = await require(self.store, EntityKind.PAYMENT, payment_id)
        self._finish(fault)
        return RazorpayPayment.model_validate(entity)

    async def list_payments(
        self, *, from_ts: datetime, to_ts: datetime, count: int = MAX_LIST_COUNT, skip: int = 0
    ) -> list[RazorpayPayment]:
        fault = await self._begin(FaultOperation.LIST_PAYMENTS)
        if not 1 <= count <= MAX_LIST_COUNT:
            raise bad_request("count must be between 1 and 100", "count")
        if skip < 0:
            raise bad_request("skip must not be negative", "skip")
        entities = await self._payments_of(await self.store.members("payments", "all"))
        window = [entity for entity in entities if epoch(from_ts) <= entity["created_at"] <= epoch(to_ts)]
        newest_first = sorted(window, key=lambda entity: entity["created_at"], reverse=True)
        self._finish(fault)
        return [RazorpayPayment.model_validate(entity) for entity in newest_first[skip : skip + count]]

    async def create_customer(
        self, *, name: str, email: str | None = None, contact: str | None = None, notes: Mapping[str, str] | None = None
    ) -> RazorpayCustomer:
        fault = await self._begin(FaultOperation.CREATE_CUSTOMER)
        existing_id = await self.store.lookup("customer_email", email.lower()) if email else None
        existing = await self.store.get(EntityKind.CUSTOMER, existing_id) if existing_id else None
        if existing is not None:
            self._finish(fault)
            return RazorpayCustomer.model_validate(existing)
        customer_id = await new_entity_id(self.store, "cust")
        entity = customer_entity(customer_id, self.clock.now(), CustomerSpec(name, email, contact, notes))
        await self.store.put(EntityKind.CUSTOMER, customer_id, entity)
        if email:
            await self.store.set_index("customer_email", email.lower(), customer_id)
        self._finish(fault)
        return RazorpayCustomer.model_validate(entity)

    async def create_plan(self, plan: PlanParams) -> RazorpayPlan:
        fault = await self._begin(FaultOperation.CREATE_PLAN)
        if plan.interval < 1 or (plan.period is PlanPeriod.DAILY and plan.interval < MINIMUM_DAILY_INTERVAL):
            raise bad_request("The interval is below the minimum allowed for this period", "interval")
        if plan.amount < MINIMUM_ORDER_AMOUNT:
            raise bad_request("Plan amount less than minimum amount allowed", "amount")
        plan_id = await new_entity_id(self.store, "plan")
        item_id = await new_entity_id(self.store, "item")
        entity = plan_entity(plan_id, item_id, self.clock.now(), plan)
        await self.store.put(EntityKind.PLAN, plan_id, entity)
        self._finish(fault)
        return RazorpayPlan.model_validate(entity)

    async def create_subscription(
        self,
        *,
        plan_id: str,
        total_count: int,
        notes: Mapping[str, str] | None = None,
        customer_notify: bool = True,
    ) -> RazorpaySubscription:
        fault = await self._begin(FaultOperation.CREATE_SUBSCRIPTION)
        if await self.store.get(EntityKind.PLAN, plan_id) is None:
            raise bad_request("The id provided does not exist", "plan_id")
        if total_count < 1:
            raise bad_request("total_count must be at least 1", "total_count")
        subscription_id = await new_entity_id(self.store, "sub")
        entity = subscription_entity(
            subscription_id, self.clock.now(), SubscriptionSpec(plan_id, total_count, customer_notify, notes)
        )
        await self.store.put(EntityKind.SUBSCRIPTION, subscription_id, entity)
        self._finish(fault)
        return RazorpaySubscription.model_validate(entity)

    async def fetch_subscription(self, subscription_id: str) -> RazorpaySubscription:
        fault = await self._begin(FaultOperation.FETCH_SUBSCRIPTION)
        entity = await require(self.store, EntityKind.SUBSCRIPTION, subscription_id)
        self._finish(fault)
        return RazorpaySubscription.model_validate(entity)

    async def cancel_subscription(self, subscription_id: str, *, at_cycle_end: bool) -> RazorpaySubscription:
        fault = await self._begin(FaultOperation.CANCEL_SUBSCRIPTION)
        entity = await require(self.store, EntityKind.SUBSCRIPTION, subscription_id)
        status = SubscriptionStatus(entity["status"])
        if status not in CANCELLABLE:
            raise bad_request(f"Subscription is not cancellable in {status.value} status")
        if at_cycle_end:
            if status is not SubscriptionStatus.ACTIVE:
                raise bad_request("The subscription cannot be cancelled at cycle end unless it is active")
            entity["has_scheduled_changes"] = True
            entity["change_scheduled_at"] = entity["current_end"]
            scheduled = await self.store.get(EntityKind.SCHEDULED_CHANGE, subscription_id) or {}
            await self.store.put(EntityKind.SCHEDULED_CHANGE, subscription_id, {**scheduled, "cancel": True})
        else:
            entity["status"] = SubscriptionStatus.CANCELLED.value
            entity["ended_at"] = epoch(self.clock.now())
            entity["has_scheduled_changes"] = False
            entity["change_scheduled_at"] = None
        await self.store.put(EntityKind.SUBSCRIPTION, subscription_id, entity)
        self._finish(fault)
        return RazorpaySubscription.model_validate(entity)

    async def update_subscription(
        self, subscription_id: str, *, plan_id: str, schedule_change_at: ScheduleChangeAt = ScheduleChangeAt.CYCLE_END
    ) -> RazorpaySubscription:
        fault = await self._begin(FaultOperation.UPDATE_SUBSCRIPTION)
        entity = await require(self.store, EntityKind.SUBSCRIPTION, subscription_id)
        if SubscriptionStatus(entity["status"]) not in UPDATABLE:
            raise bad_request("The subscription cannot be updated in its current status")
        if await self.store.get(EntityKind.PLAN, plan_id) is None:
            raise bad_request("The id provided does not exist", "plan_id")
        if schedule_change_at is ScheduleChangeAt.NOW:
            entity["plan_id"] = plan_id
        else:
            entity["has_scheduled_changes"] = True
            entity["change_scheduled_at"] = entity["current_end"]
            scheduled = await self.store.get(EntityKind.SCHEDULED_CHANGE, subscription_id) or {}
            await self.store.put(EntityKind.SCHEDULED_CHANGE, subscription_id, {**scheduled, "plan_id": plan_id})
        await self.store.put(EntityKind.SUBSCRIPTION, subscription_id, entity)
        self._finish(fault)
        return RazorpaySubscription.model_validate(entity)

    async def create_refund(
        self,
        payment_id: str,
        *,
        amount: int,
        notes: Mapping[str, str] | None = None,
        receipt: str | None = None,
    ) -> RazorpayRefund:
        fault = await self._begin(FaultOperation.CREATE_REFUND)
        payment = await require(self.store, EntityKind.PAYMENT, payment_id)
        if PaymentStatus(payment["status"]) not in REFUNDABLE:
            raise bad_request("The payment has not been captured yet")
        if amount < 1:
            raise bad_request("The refund amount must be greater than zero", "amount")
        if amount > payment["amount"] - payment["amount_refunded"]:
            raise bad_request("The refund amount provided is greater than the amount captured", "amount")
        refund_id = await new_entity_id(self.store, "rfnd")
        entity = refund_entity(
            refund_id,
            self.clock.now(),
            payment,
            RefundSpec(amount, self.refund_initial_status.value, notes, receipt),
        )
        payment["amount_refunded"] += amount
        full = payment["amount_refunded"] == payment["amount"]
        payment["status"] = (PaymentStatus.REFUNDED if full else PaymentStatus.PARTIALLY_REFUNDED).value
        payment["refund_status"] = "full" if full else "partial"
        await self.store.put(EntityKind.REFUND, refund_id, entity)
        await self.store.put(EntityKind.PAYMENT, payment_id, payment)
        await self.store.append("payment_refunds", payment_id, refund_id)
        self._finish(fault)
        return RazorpayRefund.model_validate(entity)

    async def fetch_refund(self, refund_id: str) -> RazorpayRefund:
        fault = await self._begin(FaultOperation.FETCH_REFUND)
        entity = await require(self.store, EntityKind.REFUND, refund_id)
        self._finish(fault)
        return RazorpayRefund.model_validate(entity)

    async def list_payment_refunds(self, payment_id: str) -> list[RazorpayRefund]:
        fault = await self._begin(FaultOperation.LIST_PAYMENT_REFUNDS)
        await require(self.store, EntityKind.PAYMENT, payment_id)
        entities = [
            await self.store.get(EntityKind.REFUND, refund_id)
            for refund_id in await self.store.members("payment_refunds", payment_id)
        ]
        self._finish(fault)
        return [RazorpayRefund.model_validate(entity) for entity in entities if entity is not None]
