from datetime import date

import pytest

from motionile.modules.billing.admin_records import RevenueDay
from motionile.modules.billing.exceptions import InvalidAnalyticsRangeError
from motionile.modules.billing.services.analytics_rules import (
    DEFAULT_RANGE_DAYS,
    MAX_RANGE_DAYS,
    AnalyticsRange,
    credits_day,
    fill_credits,
    fill_revenue,
    fill_statuses,
    resolve_range,
)
from motionile.modules.credits import LedgerDayTotal

TODAY = date(2026, 10, 18)


def test_the_default_window_is_the_last_thirty_days() -> None:
    window = resolve_range(None, None, TODAY)

    assert window.end == TODAY
    assert len(window.days) == DEFAULT_RANGE_DAYS
    assert window.days[0] == date(2026, 9, 19)


def test_a_single_day_window_is_valid() -> None:
    assert resolve_range(TODAY, TODAY, TODAY).days == [TODAY]


def test_an_open_start_ends_today() -> None:
    window = resolve_range(date(2026, 10, 10), None, TODAY)

    assert (window.start, window.end) == (date(2026, 10, 10), TODAY)


def test_the_longest_window_is_three_hundred_sixty_six_days() -> None:
    window = resolve_range(date(2025, 10, 18), date(2026, 10, 18), TODAY)

    assert len(window.days) == MAX_RANGE_DAYS


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (date(2026, 10, 19), date(2026, 10, 18)),
        (date(2025, 10, 17), date(2026, 10, 18)),
        (date(2020, 1, 1), None),
    ],
)
def test_an_inverted_or_oversized_window_is_rejected(start: date, end: date | None) -> None:
    with pytest.raises(InvalidAnalyticsRangeError):
        resolve_range(start, end, TODAY)


def test_revenue_is_zero_filled_in_order() -> None:
    window = AnalyticsRange(date(2026, 10, 16), date(2026, 10, 19))
    rows = [RevenueDay(date(2026, 10, 18), 5_000, 1_000, 2), RevenueDay(date(2026, 10, 16), 100, 0, 1)]

    filled = fill_revenue(rows, window)

    assert [day.day for day in filled] == window.days
    assert [(day.captured_paise, day.refunded_paise, day.payment_count) for day in filled] == [
        (100, 0, 1),
        (0, 0, 0),
        (5_000, 1_000, 2),
        (0, 0, 0),
    ]


def test_credit_totals_are_split_by_source_and_cause() -> None:
    day = date(2026, 10, 18)
    rows = [
        LedgerDayTotal(day, "purchase", granted=100, removed=0),
        LedgerDayTotal(day, "subscription_grant", granted=300, removed=0),
        LedgerDayTotal(day, "promo_grant", granted=20, removed=0),
        LedgerDayTotal(day, "admin_adjust", granted=7, removed=3),
        LedgerDayTotal(day, "commit", granted=0, removed=40),
        LedgerDayTotal(day, "expiry", granted=0, removed=11),
        LedgerDayTotal(day, "refund_clawback", granted=0, removed=25),
    ]

    result = credits_day(day, rows)

    assert dict(result.granted) == {"purchase": 100, "subscription": 300, "promo": 20, "admin": 7}
    assert result.granted_total == 427
    assert (result.consumed, result.expired, result.clawed_back, result.adjusted_down) == (40, 11, 25, 3)


def test_credit_days_without_entries_are_zero() -> None:
    window = AnalyticsRange(date(2026, 10, 17), date(2026, 10, 18))

    filled = fill_credits([LedgerDayTotal(date(2026, 10, 18), "commit", 0, 9)], window)

    assert [(day.consumed, day.granted_total) for day in filled] == [(0, 0), (9, 0)]


def test_every_subscription_status_is_listed() -> None:
    counts = fill_statuses({"active": 3, "cancelled": 1})

    assert counts["active"] == 3
    assert counts["halted"] == 0
    assert set(counts) == {
        "created",
        "authenticated",
        "active",
        "pending",
        "halted",
        "paused",
        "cancelled",
        "completed",
        "expired",
    }
