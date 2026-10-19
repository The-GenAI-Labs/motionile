from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

from motionile.modules.billing.admin_records import RevenueDay
from motionile.modules.billing.exceptions import InvalidAnalyticsRangeError
from motionile.modules.billing.states import SubscriptionStatus
from motionile.modules.credits import LedgerDayTotal

MAX_RANGE_DAYS = 366
DEFAULT_RANGE_DAYS = 30
GRANT_SOURCE_BY_REASON = {
    "purchase": "purchase",
    "subscription_grant": "subscription",
    "promo_grant": "promo",
    "admin_adjust": "admin",
}
GRANT_SOURCES = tuple(GRANT_SOURCE_BY_REASON.values())


@dataclass(frozen=True)
class AnalyticsRange:
    start: date
    end: date

    @property
    def days(self) -> list[date]:
        return [self.start + timedelta(days=offset) for offset in range((self.end - self.start).days + 1)]


@dataclass(frozen=True)
class CreditsDay:
    day: date
    granted: Mapping[str, int]
    consumed: int
    expired: int
    clawed_back: int
    adjusted_down: int

    @property
    def granted_total(self) -> int:
        return sum(self.granted.values())


def resolve_range(start: date | None, end: date | None, today: date) -> AnalyticsRange:
    last = end or today
    first = start or last - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if first > last or (last - first).days + 1 > MAX_RANGE_DAYS:
        raise InvalidAnalyticsRangeError(f"The range must be between 1 and {MAX_RANGE_DAYS} days.")
    return AnalyticsRange(first, last)


def fill_revenue(rows: Iterable[RevenueDay], window: AnalyticsRange) -> list[RevenueDay]:
    by_day = {row.day: row for row in rows}
    return [by_day.get(day) or RevenueDay(day, 0, 0, 0) for day in window.days]


def fill_credits(rows: Iterable[LedgerDayTotal], window: AnalyticsRange) -> list[CreditsDay]:
    by_day: dict[date, list[LedgerDayTotal]] = {}
    for row in rows:
        by_day.setdefault(row.day, []).append(row)
    return [credits_day(day, by_day.get(day, [])) for day in window.days]


def credits_day(day: date, rows: Iterable[LedgerDayTotal]) -> CreditsDay:
    granted = dict.fromkeys(GRANT_SOURCES, 0)
    consumed = expired = clawed_back = adjusted_down = 0
    for row in rows:
        source = GRANT_SOURCE_BY_REASON.get(row.reason)
        if source is not None:
            granted[source] += row.granted
        if row.reason == "admin_adjust":
            adjusted_down += row.removed
        elif row.reason == "commit":
            consumed += row.removed
        elif row.reason == "expiry":
            expired += row.removed
        elif row.reason == "refund_clawback":
            clawed_back += row.removed
    return CreditsDay(
        day=day,
        granted=granted,
        consumed=consumed,
        expired=expired,
        clawed_back=clawed_back,
        adjusted_down=adjusted_down,
    )


def fill_statuses(counts: Mapping[str, int]) -> dict[str, int]:
    return {status.value: counts.get(status.value, 0) for status in SubscriptionStatus}
