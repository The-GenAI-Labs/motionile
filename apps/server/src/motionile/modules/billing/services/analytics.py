from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.modules.billing.admin_records import PlanCount, RevenueDay
from motionile.modules.billing.analytics_repository import AnalyticsStore, SqlAnalyticsRepository
from motionile.modules.billing.ports import Transaction
from motionile.modules.billing.services.analytics_rules import (
    AnalyticsRange,
    CreditsDay,
    fill_credits,
    fill_revenue,
    fill_statuses,
    resolve_range,
)
from motionile.modules.credits import BalanceTotals, CreditsService

type AnalyticsStoreOf = Callable[[AsyncSession], AnalyticsStore]


@dataclass(frozen=True)
class RevenueReport:
    window: AnalyticsRange
    days: list[RevenueDay]


@dataclass(frozen=True)
class SubscriptionReport:
    by_plan: tuple[PlanCount, ...]
    by_status: dict[str, int]


@dataclass(frozen=True)
class CreditsReport:
    window: AnalyticsRange
    days: list[CreditsDay]
    balances: BalanceTotals


class AnalyticsService:
    def __init__(
        self,
        transaction: Transaction,
        clock: Clock,
        ledger: CreditsService,
        *,
        store_factory: AnalyticsStoreOf = SqlAnalyticsRepository,
    ) -> None:
        self._transaction = transaction
        self._clock = clock
        self._credits = ledger
        self._store_factory = store_factory

    def _window(self, start: date | None, end: date | None) -> AnalyticsRange:
        return resolve_range(start, end, self._clock.now().date())

    async def revenue(self, start: date | None, end: date | None) -> RevenueReport:
        window = self._window(start, end)
        async with self._transaction() as session:
            rows = await self._store_factory(session).revenue_days(window.start, window.end)
        return RevenueReport(window, fill_revenue(rows, window))

    async def subscriptions(self) -> SubscriptionReport:
        async with self._transaction() as session:
            counts = await self._store_factory(session).subscription_counts()
        return SubscriptionReport(counts.by_plan, fill_statuses(counts.by_status))

    async def credits(self, start: date | None, end: date | None) -> CreditsReport:
        window = self._window(start, end)
        async with self._transaction() as session:
            rows = await self._credits.ledger_daily_totals(session, window.start, window.end)
            balances = await self._credits.balance_totals(session)
        return CreditsReport(window, fill_credits(rows, window), balances)
