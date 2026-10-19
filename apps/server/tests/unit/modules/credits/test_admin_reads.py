from datetime import date, timedelta

import pytest
from tests.unit.modules.credits.conftest import Harness

from motionile.core.ids import new_id
from motionile.modules.credits import AdjustCommand, InvalidUsageRangeError


async def test_lots_are_paged_newest_first(harness: Harness) -> None:
    first = await harness.grant(10)
    harness.clock.advance(timedelta(seconds=1))
    second = await harness.grant(20, source="promo")
    harness.clock.advance(timedelta(seconds=1))
    third = await harness.grant(30)

    page = await harness.service.lots(harness.session, harness.user_id, None, 2)
    rest = await harness.service.lots(harness.session, harness.user_id, page.next_cursor, 2)

    assert [lot.id for lot in page.items] == [third.lot_id, second.lot_id]
    assert page.next_cursor is not None
    assert [lot.id for lot in rest.items] == [first.lot_id]
    assert rest.next_cursor is None


async def test_daily_totals_split_granted_and_removed_credits_by_reason(harness: Harness) -> None:
    await harness.grant(100)
    reservation = await harness.reserve(40)
    await harness.service.commit(harness.session, reservation.id, 30, harness.key("commit"))
    await harness.service.adjust(
        harness.session,
        AdjustCommand(harness.user_id, -5, "correction", new_id(), harness.key("adjust")),
    )
    today = harness.clock.now().date()

    totals = await harness.service.ledger_daily_totals(harness.session, today, today)

    assert {(row.reason, row.granted, row.removed) for row in totals} == {
        ("purchase", 100, 0),
        ("commit", 0, 30),
        ("admin_adjust", 0, 5),
    }
    assert {row.day for row in totals} == {today}


async def test_daily_totals_ignore_days_outside_the_window(harness: Harness) -> None:
    await harness.grant(100)
    yesterday = harness.clock.now().date() - timedelta(days=1)

    assert await harness.service.ledger_daily_totals(harness.session, yesterday, yesterday) == []


@pytest.mark.parametrize(
    ("start", "end"), [(date(2026, 10, 18), date(2026, 10, 17)), (date(2025, 1, 1), date(2026, 10, 1))]
)
async def test_daily_totals_reject_inverted_and_oversized_windows(harness: Harness, start: date, end: date) -> None:
    with pytest.raises(InvalidUsageRangeError):
        await harness.service.ledger_daily_totals(harness.session, start, end)


async def test_balance_totals_sum_every_wallet(harness: Harness) -> None:
    other = new_id()
    await harness.grant(70)
    await harness.grant(30, user_id=other)
    await harness.reserve(20)

    totals = await harness.service.balance_totals(harness.session)

    assert (totals.wallets, totals.balance, totals.reserved) == (2, 100, 20)
