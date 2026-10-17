import calendar
import secrets
import string
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from motionile.modules.billing.razorpay.api import PlanParams, PlanPeriod
from motionile.modules.billing.razorpay.exceptions import RazorpayBadRequestError, RazorpayNotFoundError
from motionile.modules.billing.razorpay.fake_store import Entity, EntityKind, FakeRazorpayStore

ALPHABET = string.ascii_letters + string.digits
RANDOM_PREFIX_LENGTH = 6
SEQUENCE_WIDTH = 8
MINIMUM_ORDER_AMOUNT = 100
BAD_REQUEST = "BAD_REQUEST_ERROR"
MONTHS_PER_YEAR = 12
FEE_PERCENT = 2
TAX_PERCENT = 18
FAKE_ACCOUNT_ID = "acc_FakeMotionile01"


def base62(value: int, width: int) -> str:
    digits: list[str] = []
    remaining = value
    while remaining:
        remaining, index = divmod(remaining, len(ALPHABET))
        digits.append(ALPHABET[index])
    return "".join(reversed(digits)).rjust(width, "0")[-width:]


async def new_entity_id(store: FakeRazorpayStore, prefix: str) -> str:
    sequence = await store.next_sequence(prefix)
    randomness = "".join(secrets.choice(ALPHABET) for _ in range(RANDOM_PREFIX_LENGTH))
    return f"{prefix}_{randomness}{base62(sequence, SEQUENCE_WIDTH)}"


def epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def add_months(moment: datetime, months: int) -> datetime:
    index = moment.month - 1 + months
    year = moment.year + index // MONTHS_PER_YEAR
    month = index % MONTHS_PER_YEAR + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def add_period(moment: datetime, period: str, interval: int) -> datetime:
    match PlanPeriod(period):
        case PlanPeriod.DAILY:
            return moment + timedelta(days=interval)
        case PlanPeriod.WEEKLY:
            return moment + timedelta(weeks=interval)
        case PlanPeriod.MONTHLY:
            return add_months(moment, interval)
        case PlanPeriod.YEARLY:
            return add_months(moment, interval * MONTHS_PER_YEAR)


def bad_request(description: str, field: str | None = None) -> RazorpayBadRequestError:
    return RazorpayBadRequestError(400, code=BAD_REQUEST, description=description, field=field)


def not_found() -> RazorpayNotFoundError:
    return RazorpayNotFoundError(404, code=BAD_REQUEST, description="The id provided does not exist")


async def require(store: FakeRazorpayStore, kind: EntityKind, entity_id: str) -> Entity:
    entity = await store.get(kind, entity_id)
    if entity is None:
        raise not_found()
    return entity


def normalized_notes(notes: Mapping[str, str] | None) -> dict[str, str]:
    return dict(notes or {})


@dataclass(frozen=True)
class OrderSpec:
    amount: int
    currency: str
    receipt: str | None = None
    notes: Mapping[str, str] | None = None


@dataclass(frozen=True)
class PaymentSpec:
    amount: int
    currency: str
    status: str
    method: str = "card"
    order_id: str | None = None
    invoice_id: str | None = None
    notes: Mapping[str, str] | None = None


@dataclass(frozen=True)
class RefundSpec:
    amount: int
    status: str
    notes: Mapping[str, str] | None = None
    receipt: str | None = None


@dataclass(frozen=True)
class CustomerSpec:
    name: str
    email: str | None = None
    contact: str | None = None
    notes: Mapping[str, str] | None = None


@dataclass(frozen=True)
class SubscriptionSpec:
    plan_id: str
    total_count: int
    customer_notify: bool = True
    notes: Mapping[str, str] | None = None


def order_entity(order_id: str, now: datetime, spec: OrderSpec) -> Entity:
    return {
        "id": order_id,
        "entity": "order",
        "amount": spec.amount,
        "amount_paid": 0,
        "amount_due": spec.amount,
        "currency": spec.currency,
        "receipt": spec.receipt,
        "offer_id": None,
        "status": "created",
        "attempts": 0,
        "notes": normalized_notes(spec.notes),
        "created_at": epoch(now),
    }


def payment_entity(payment_id: str, now: datetime, spec: PaymentSpec) -> Entity:
    captured = spec.status == "captured"
    failed = spec.status == "failed"
    fee = spec.amount * FEE_PERCENT // 100 if captured else None
    return {
        "id": payment_id,
        "entity": "payment",
        "amount": spec.amount,
        "currency": spec.currency,
        "status": spec.status,
        "order_id": spec.order_id,
        "invoice_id": spec.invoice_id,
        "international": False,
        "method": spec.method,
        "amount_refunded": 0,
        "refund_status": None,
        "captured": captured,
        "description": "Motionile",
        "email": "customer@example.com",
        "contact": "+919999999999",
        "fee": fee,
        "tax": fee * TAX_PERCENT // 100 if fee is not None else None,
        "error_code": "BAD_REQUEST_ERROR" if failed else None,
        "error_description": "Payment processing failed because of incorrect OTP" if failed else None,
        "error_source": "customer" if failed else None,
        "error_step": "payment_authentication" if failed else None,
        "error_reason": "incorrect_otp" if failed else None,
        "notes": normalized_notes(spec.notes),
        "created_at": epoch(now),
    }


def refund_entity(refund_id: str, now: datetime, payment: Entity, spec: RefundSpec) -> Entity:
    return {
        "id": refund_id,
        "entity": "refund",
        "amount": spec.amount,
        "currency": payment["currency"],
        "payment_id": payment["id"],
        "notes": normalized_notes(spec.notes),
        "receipt": spec.receipt,
        "acquirer_data": {"arn": None},
        "created_at": epoch(now),
        "batch_id": None,
        "status": spec.status,
        "speed_processed": "normal",
        "speed_requested": "normal",
    }


def plan_entity(plan_id: str, item_id: str, now: datetime, plan: PlanParams) -> Entity:
    return {
        "id": plan_id,
        "entity": "plan",
        "interval": plan.interval,
        "period": plan.period.value,
        "item": {
            "id": item_id,
            "active": True,
            "name": plan.name,
            "description": plan.description,
            "amount": plan.amount,
            "unit_amount": plan.amount,
            "currency": plan.currency,
            "type": "plan",
            "unit": None,
            "tax_inclusive": False,
            "hsn_code": None,
            "sac_code": None,
            "tax_rate": None,
            "tax_id": None,
            "tax_group_id": None,
            "created_at": epoch(now),
            "updated_at": epoch(now),
        },
        "notes": normalized_notes(plan.notes),
        "created_at": epoch(now),
    }


def customer_entity(customer_id: str, now: datetime, spec: CustomerSpec) -> Entity:
    return {
        "id": customer_id,
        "entity": "customer",
        "name": spec.name,
        "email": spec.email,
        "contact": spec.contact,
        "gstin": None,
        "notes": normalized_notes(spec.notes),
        "created_at": epoch(now),
    }


def subscription_entity(subscription_id: str, now: datetime, spec: SubscriptionSpec) -> Entity:
    return {
        "id": subscription_id,
        "entity": "subscription",
        "plan_id": spec.plan_id,
        "customer_id": None,
        "status": "created",
        "current_start": None,
        "current_end": None,
        "ended_at": None,
        "quantity": 1,
        "notes": normalized_notes(spec.notes),
        "charge_at": epoch(now),
        "start_at": epoch(now),
        "end_at": None,
        "auth_attempts": 0,
        "total_count": spec.total_count,
        "paid_count": 0,
        "customer_notify": spec.customer_notify,
        "created_at": epoch(now),
        "expire_by": epoch(now + timedelta(days=30)),
        "short_url": f"https://rzp.io/i/{subscription_id.removeprefix('sub_')}",
        "has_scheduled_changes": False,
        "change_scheduled_at": None,
        "source": "api",
        "remaining_count": spec.total_count,
    }
