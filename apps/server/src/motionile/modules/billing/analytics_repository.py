from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.billing.admin_records import PlanCount, RevenueDay, SubscriptionCounts
from motionile.modules.billing.models import Payment, Product, Refund, Subscription
from motionile.modules.billing.repository import CAPTURED_FAMILY_VALUES, LIVE_STATUS_VALUES
from motionile.modules.billing.states import RefundStatus, SubscriptionStatus

ANALYTICS_CURRENCY = "INR"


class AnalyticsStore(Protocol):
    async def revenue_days(self, start: date, end: date) -> list[RevenueDay]: ...
    async def subscription_counts(self) -> SubscriptionCounts: ...


def day_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(start, time.min).replace(tzinfo=UTC),
        datetime.combine(end + timedelta(days=1), time.min).replace(tzinfo=UTC),
    )


class SqlAnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def revenue_days(self, start: date, end: date) -> list[RevenueDay]:
        lower, upper = day_bounds(start, end)
        captured_at = func.coalesce(Payment.captured_at, Payment.created_at)
        captured_day = cast(func.timezone("UTC", captured_at), Date)
        captured_rows = await self.session.execute(
            select(captured_day, func.sum(Payment.amount_paise), func.count())
            .where(
                Payment.status.in_(CAPTURED_FAMILY_VALUES),
                Payment.currency == ANALYTICS_CURRENCY,
                captured_at >= lower,
                captured_at < upper,
            )
            .group_by(captured_day)
        )
        refunded_day = cast(func.timezone("UTC", Refund.processed_at), Date)
        refunded_rows = await self.session.execute(
            select(refunded_day, func.sum(Refund.amount_paise))
            .join(Payment, Payment.id == Refund.payment_id)
            .where(
                Refund.status == RefundStatus.PROCESSED.value,
                Payment.currency == ANALYTICS_CURRENCY,
                Refund.processed_at >= lower,
                Refund.processed_at < upper,
            )
            .group_by(refunded_day)
        )
        captured = {row[0]: (int(row[1]), int(row[2])) for row in captured_rows}
        refunded = {row[0]: int(row[1]) for row in refunded_rows}
        return [
            RevenueDay(
                day=day,
                captured_paise=captured.get(day, (0, 0))[0],
                refunded_paise=refunded.get(day, 0),
                payment_count=captured.get(day, (0, 0))[1],
            )
            for day in sorted(captured.keys() | refunded.keys())
        ]

    async def subscription_counts(self) -> SubscriptionCounts:
        live = Subscription.status.in_(LIVE_STATUS_VALUES)
        active = Subscription.status == SubscriptionStatus.ACTIVE.value
        plan_rows = await self.session.execute(
            select(
                Product.plan_key,
                Product.code,
                Product.name,
                Product.interval,
                func.count().filter(live),
                func.count().filter(active),
            )
            .join(Product, Product.id == Subscription.product_id)
            .where(live)
            .group_by(Product.plan_key, Product.code, Product.name, Product.interval)
            .order_by(Product.plan_key, Product.interval, Product.code)
        )
        status_rows = await self.session.execute(
            select(Subscription.status, func.count()).group_by(Subscription.status)
        )
        return SubscriptionCounts(
            by_plan=tuple(
                PlanCount(
                    plan_key=row[0],
                    product_code=row[1],
                    product_name=row[2],
                    interval=row[3],
                    live_count=int(row[4]),
                    active_count=int(row[5]),
                )
                for row in plan_rows
            ),
            by_status={row[0]: int(row[1]) for row in status_rows},
        )
