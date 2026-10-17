from dataclasses import replace
from datetime import date, timedelta
from uuid import UUID

import pytest
from tests.unit.modules.credits.conftest import Harness

from motionile.core.ids import new_id
from motionile.modules.credits import (
    CreditUserNotFoundError,
    InvalidUsageRangeError,
    InvalidUsageRecordError,
    UsageEntry,
    record_usage,
)


def usage_entry(user_id: UUID, key: str) -> UsageEntry:
    return UsageEntry(user_id=user_id, stage="storyboard", provider="anthropic", key=key)


async def test_usage_is_recorded_once_per_idempotency_key(harness: Harness) -> None:
    job = new_id()
    entry = replace(
        UsageEntry(user_id=harness.user_id, stage="tts", provider="elevenlabs", key="stage:1"),
        model="eleven_v3",
        audio_characters=1200,
        cost_micros_usd=45_000,
        credits=3,
        job_id=job,
    )

    first = await record_usage(harness.session, entry, store_factory=harness.store)
    again = await record_usage(harness.session, replace(entry, credits=99), store_factory=harness.store)

    assert again == first
    assert len(harness.store.usage) == 1
    assert harness.store.usage[0].entry.credits == 3


async def test_distinct_keys_create_distinct_usage_records(harness: Harness) -> None:
    first = await record_usage(harness.session, usage_entry(harness.user_id, "a"), store_factory=harness.store)
    second = await record_usage(harness.session, usage_entry(harness.user_id, "b"), store_factory=harness.store)

    assert first != second
    assert len(harness.store.usage) == 2


@pytest.mark.parametrize(
    "overrides",
    [
        {"stage": "Render"},
        {"stage": "x"},
        {"provider": "bad provider"},
        {"model": "m" * 101},
        {"input_tokens": -1},
        {"credits": -1},
        {"cost_micros_usd": -5},
        {"render_ms": 2_147_483_648},
        {"key": ""},
    ],
)
def test_usage_entries_validate_their_fields(overrides: dict[str, int | str]) -> None:
    with pytest.raises(InvalidUsageRecordError) as raised:
        replace(usage_entry(new_id(), "k"), **overrides)

    assert raised.value.status_code == 422


async def test_usage_for_an_unknown_user_is_not_found(harness: Harness) -> None:
    harness.store.known_users = set()

    with pytest.raises(CreditUserNotFoundError):
        await record_usage(harness.session, usage_entry(harness.user_id, "ghost"), store_factory=harness.store)


async def test_usage_pages_are_newest_first_and_owner_scoped(harness: Harness) -> None:
    other = new_id()
    for index in range(5):
        harness.clock.advance(timedelta(seconds=1))
        await record_usage(harness.session, usage_entry(harness.user_id, f"mine:{index}"), store_factory=harness.store)
    await record_usage(harness.session, usage_entry(other, "theirs"), store_factory=harness.store)

    first = await harness.service.usage(harness.session, harness.user_id, None, 2)
    assert first.next_cursor is not None
    second = await harness.service.usage(harness.session, harness.user_id, first.next_cursor, 2)
    last = await harness.service.usage(harness.session, harness.user_id, second.next_cursor, 2)

    seen = [row.id for row in first.items + second.items + last.items]
    assert len(seen) == len(set(seen)) == 5
    assert [row.created_at for row in first.items] == sorted((row.created_at for row in first.items), reverse=True)
    assert last.next_cursor is None
    assert not {stored.id for stored in harness.store.usage if stored.entry.user_id == other} & set(seen)


async def test_daily_usage_groups_by_utc_day_inside_the_range(harness: Harness) -> None:
    for offset_hours, spent in [(0, 2), (3, 5), (12, 1), (30, 7)]:
        harness.clock.set(harness.clock.now().replace(hour=0, minute=0) + timedelta(hours=offset_hours))
        await record_usage(
            harness.session,
            replace(usage_entry(harness.user_id, f"u:{offset_hours}"), credits=spent),
            store_factory=harness.store,
        )

    days = await harness.service.daily_usage(harness.session, harness.user_id, date(2026, 10, 17), date(2026, 10, 18))

    assert [(item.date, item.credits, item.records) for item in days] == [
        (date(2026, 10, 17), 8, 3),
        (date(2026, 10, 18), 7, 1),
    ]


async def test_daily_usage_defaults_to_the_last_thirty_days(harness: Harness) -> None:
    await record_usage(harness.session, usage_entry(harness.user_id, "today"), store_factory=harness.store)
    harness.clock.advance(timedelta(days=29))
    await record_usage(harness.session, usage_entry(harness.user_id, "later"), store_factory=harness.store)
    harness.clock.advance(timedelta(days=1))

    days = await harness.service.daily_usage(harness.session, harness.user_id, None, None)

    assert [item.date for item in days] == [date(2026, 11, 15)]


async def test_daily_usage_range_is_bounded_to_366_days(harness: Harness) -> None:
    start = date(2025, 10, 17)

    assert await harness.service.daily_usage(harness.session, harness.user_id, start, date(2026, 10, 17)) == []
    with pytest.raises(InvalidUsageRangeError):
        await harness.service.daily_usage(harness.session, harness.user_id, start, date(2026, 10, 18))
    with pytest.raises(InvalidUsageRangeError):
        await harness.service.daily_usage(harness.session, harness.user_id, date(2026, 10, 18), date(2026, 10, 17))


async def test_ledger_pages_are_newest_first_and_owner_scoped(harness: Harness) -> None:
    other = new_id()
    for index in range(5):
        harness.clock.advance(timedelta(seconds=1))
        await harness.grant(index + 1)
    await harness.grant(500, user_id=other)

    first = await harness.service.ledger(harness.session, harness.user_id, None, 3)
    assert first.next_cursor is not None
    second = await harness.service.ledger(harness.session, harness.user_id, first.next_cursor, 3)

    assert [row.delta for row in first.items + second.items] == [5, 4, 3, 2, 1]
    assert second.next_cursor is None
    assert all(row.user_id == harness.user_id for row in first.items + second.items)


async def test_reminders_are_claimed_once_per_lot_and_grouped_per_user(harness: Harness) -> None:
    other = new_id()
    await harness.grant(10, expires_in=timedelta(days=3))
    await harness.grant(5, expires_in=timedelta(days=6))
    await harness.grant(20, expires_in=timedelta(days=30))
    await harness.grant(40)
    await harness.grant(7, expires_in=timedelta(days=2), user_id=other)

    batches = await harness.service.claim_expiry_reminders(harness.session, 100)
    again = await harness.service.claim_expiry_reminders(harness.session, 100)

    by_user = {batch.user_id: batch for batch in batches}
    assert set(by_user) == {harness.user_id, other}
    assert by_user[harness.user_id].credits == 15
    assert by_user[harness.user_id].expires_at == harness.clock.now() + timedelta(days=3)
    assert by_user[other].credits == 7
    assert again == []
    assert sum(1 for lot in harness.store.lots.values() if lot.expiry_reminder_sent_at is not None) == 3


async def test_reminders_skip_empty_and_already_expired_lots_and_honour_the_limit(harness: Harness) -> None:
    spent = await harness.grant(10, expires_in=timedelta(days=2))
    reservation = await harness.reserve(10)
    await harness.service.commit(harness.session, reservation.id, 10, "commit:spend")
    assert harness.lot_remaining(spent.lot_id) == 0
    for index in range(3):
        await harness.grant(index + 1, expires_in=timedelta(days=4), user_id=new_id())

    batches = await harness.service.claim_expiry_reminders(harness.session, 2)
    rest = await harness.service.claim_expiry_reminders(harness.session, 2)

    assert len(batches) == 2
    assert len(rest) == 1
    assert all(batch.user_id != harness.user_id for batch in batches + rest)


async def test_integrity_check_is_clean_after_normal_operations(harness: Harness) -> None:
    await harness.grant(100, expires_in=timedelta(days=1))
    reservation = await harness.reserve(40)
    await harness.service.commit(harness.session, reservation.id, 30, "commit:clean")
    harness.clock.advance(timedelta(days=2))
    await harness.service.expire_due_lots(harness.session, harness.user_id)

    assert await harness.service.check_integrity(harness.session) == []


async def test_integrity_check_reports_every_broken_invariant(harness: Harness) -> None:
    await harness.grant(100)
    await harness.reserve(40)
    healthy = new_id()
    await harness.grant(10, user_id=healthy)
    wallet = harness.store.wallets[harness.user_id]
    harness.store.wallets[harness.user_id] = replace(wallet, balance=wallet.balance + 7, reserved=wallet.reserved + 3)

    violations = await harness.service.check_integrity(harness.session)

    assert [violation.user_id for violation in violations] == [harness.user_id]
    found = {problem.invariant: (problem.expected, problem.actual) for problem in violations[0].problems}
    assert found == {
        "balance_equals_ledger_delta_sum": (100, 107),
        "balance_equals_lot_remaining_sum": (100, 107),
        "reserved_equals_ledger_reserved_sum": (40, 43),
        "reserved_equals_active_reservations": (40, 43),
        "balance_equals_latest_balance_after": (100, 107),
        "reserved_equals_latest_reserved_after": (40, 43),
    }


async def test_integrity_check_never_mutates_data(harness: Harness) -> None:
    await harness.grant(100)
    wallet = harness.store.wallets[harness.user_id]
    harness.store.wallets[harness.user_id] = replace(wallet, balance=1)
    snapshot = harness.store.snapshot()

    assert await harness.service.check_integrity(harness.session)

    assert harness.store.snapshot() == snapshot
