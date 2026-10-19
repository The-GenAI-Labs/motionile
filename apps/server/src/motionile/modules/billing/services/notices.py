from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.resources import Resources
from motionile.modules.billing.services.receipts import DATE_FORMAT, INCLUSIVE_OF_GST, format_amount
from motionile.modules.notifications import BillingTemplateName, enqueue_billing_email
from motionile.modules.users import UsersService

NO_DATE = "Not scheduled"


@dataclass(frozen=True)
class BillingNotice:
    user_id: UUID
    template: BillingTemplateName
    context: dict[str, str]


type NoticeSender = Callable[[AsyncSession, BillingNotice], Awaitable[None]]


def formatted_date(moment: datetime | None) -> str:
    return moment.strftime(DATE_FORMAT) if moment is not None else NO_DATE


@dataclass(frozen=True)
class ChargeSummary:
    plan_name: str
    amount_paise: int
    currency: str
    credit_count: int
    next_charge_at: datetime | None


def charge_notice(user_id: UUID, summary: ChargeSummary, *, first: bool) -> BillingNotice:
    return BillingNotice(
        user_id=user_id,
        template="subscription_activated" if first else "renewal_receipt",
        context={
            "plan": summary.plan_name,
            "amount": f"{format_amount(summary.amount_paise, summary.currency)} {INCLUSIVE_OF_GST}",
            "credits": str(summary.credit_count),
            "next_charge": formatted_date(summary.next_charge_at),
        },
    )


def charge_failed_notice(user_id: UUID, plan_name: str, next_charge_at: datetime | None) -> BillingNotice:
    return BillingNotice(
        user_id=user_id,
        template="charge_failed",
        context={"plan": plan_name, "next_attempt": formatted_date(next_charge_at)},
    )


def halted_notice(user_id: UUID, plan_name: str) -> BillingNotice:
    return BillingNotice(user_id=user_id, template="subscription_halted", context={"plan": plan_name})


def cancellation_notice(user_id: UUID, plan_name: str, ends_at: datetime | None) -> BillingNotice:
    return BillingNotice(
        user_id=user_id,
        template="cancellation_scheduled",
        context={"plan": plan_name, "ends": formatted_date(ends_at)},
    )


def ended_notice(user_id: UUID, plan_name: str) -> BillingNotice:
    return BillingNotice(user_id=user_id, template="subscription_ended", context={"plan": plan_name})


@dataclass(frozen=True)
class RefundSummary:
    amount_paise: int
    currency: str
    credits_recovered: int
    reference: str


def refund_notice(user_id: UUID, summary: RefundSummary) -> BillingNotice:
    return BillingNotice(
        user_id=user_id,
        template="refund_processed",
        context={
            "amount": format_amount(summary.amount_paise, summary.currency),
            "credits_recovered": str(summary.credits_recovered),
            "reference": summary.reference,
        },
    )


class NoticeMailer:
    def __init__(self, resources: Resources) -> None:
        self._resources = resources

    async def send(self, session: AsyncSession, notice: BillingNotice) -> None:
        email = await UsersService(session).primary_verified_email(notice.user_id)
        if email is None:
            return
        enqueue_billing_email(self._resources, session, email=email, template=notice.template, context=notice.context)
