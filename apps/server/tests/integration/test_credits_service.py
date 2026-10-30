import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import TypedDict, Unpack
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.credit_support import CreditsEnv, create_users, new_clock, purge_credit_data

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.core.resources import Resources
from motionile.modules.audit import AuditLogEntry
from motionile.modules.credits import (
    AdjustCommand,
    ClawbackCommand,
    CreditLedgerEntry,
    CreditLot,
    CreditRef,
    CreditReservation,
    CreditsService,
    CreditUserNotFoundError,
    CreditWallet,
    DuplicateLotReferenceError,
    GrantCommand,
    IdempotencyKeyConflictError,
    InsufficientCreditsError,
    ReservationAlreadyActiveError,
    ReservationNotActiveError,
    ReserveCommand,
    UsageEntry,
    UsageRecord,
    record_usage,
)
from motionile.modules.credits import tasks as credit_tasks
from motionile.modules.credits.repository import SqlCreditsRepository

CONCURRENCY = 12


@pytest.fixture
async def env(resources: Resources) -> AsyncIterator[CreditsEnv]:
    clock = new_clock()
    resources.clock = clock
    users = await create_users(resources.database, 3)
    yield CreditsEnv(
        resources=resources, clock=clock, service=CreditsService(clock, resources.settings.billing), users=users
    )
    await purge_credit_data(resources.database, users)


class GrantOptions(TypedDict, total=False):
    expires_in: timedelta
    payment: UUID


async def grant(env: CreditsEnv, user: UUID, amount: int, key: str, **options: Unpack[GrantOptions]) -> UUID:
    expires_in = options.get("expires_in")
    command = GrantCommand(
        user_id=user,
        amount=amount,
        source="purchase",
        key=key,
        expires_at=env.clock.now() + expires_in if expires_in is not None else None,
        ref=CreditRef("payment", options.get("payment") or new_id()),
    )
    result = await env.run(lambda session: env.service.grant(session, command))
    return result.lot_id


async def reserve(env: CreditsEnv, user: UUID, amount: int, key: str, *, ttl: timedelta | None = None) -> UUID:
    command = ReserveCommand(user_id=user, amount=amount, ref_type="job", ref_id=new_id(), key=key, ttl=ttl)
    return (await env.run(lambda session: env.service.reserve(session, command))).id


async def balances(env: CreditsEnv, user: UUID) -> tuple[int, int]:
    async def read(session: AsyncSession) -> tuple[int, int]:
        wallet = await session.scalar(select(CreditWallet).where(CreditWallet.user_id == user))
        assert wallet is not None
        return wallet.balance, wallet.reserved

    return await env.run(read)


async def lot_remaining(env: CreditsEnv, lot_id: UUID) -> int:
    async def read(session: AsyncSession) -> int:
        return await session.scalar(select(CreditLot.remaining).where(CreditLot.id == lot_id)) or 0

    return await env.run(read)


async def assert_clean(env: CreditsEnv) -> None:
    assert await env.run(env.service.check_integrity) == []


async def test_full_lifecycle_persists_wallet_lots_reservation_and_ledger(env: CreditsEnv) -> None:
    user = env.users[0]
    lot = await grant(env, user, 100, "payment:1", expires_in=timedelta(days=30))
    reservation = await reserve(env, user, 60, "reserve:1")

    committed = await env.run(lambda session: env.service.commit(session, reservation, 40, "commit:1"))

    assert (committed.charged, committed.released) == (40, 20)
    assert await balances(env, user) == (60, 0)
    assert await lot_remaining(env, lot) == 60

    async def rows(session: AsyncSession) -> list[tuple[str, int, int, int, int]]:
        entries = await session.scalars(
            select(CreditLedgerEntry)
            .where(CreditLedgerEntry.user_id == user)
            .order_by(CreditLedgerEntry.created_at, CreditLedgerEntry.id)
        )
        return [(e.reason, e.delta, e.reserved_delta, e.balance_after, e.reserved_after) for e in entries]

    assert await env.run(rows) == [
        ("purchase", 100, 0, 100, 0),
        ("reserve", 0, 60, 100, 60),
        ("commit", -40, -60, 60, 0),
    ]
    stored = await env.run(lambda session: session.get_one(CreditReservation, reservation))
    assert (stored.status, stored.committed_amount) == ("committed", 40)
    await assert_clean(env)


async def test_every_mutation_replays_without_new_rows(env: CreditsEnv) -> None:
    user = env.users[0]
    payment = new_id()
    first_lot = await grant(env, user, 100, "payment:replay", payment=payment)
    assert await grant(env, user, 100, "payment:replay", payment=payment) == first_lot
    reservation = await reserve(env, user, 30, "reserve:replay")
    ref = ReserveCommand(user_id=user, amount=30, ref_type="job", ref_id=new_id(), key="reserve:replay")
    with pytest.raises(IdempotencyKeyConflictError):
        await env.run(lambda session: env.service.reserve(session, ref))
    commit = await env.run(lambda session: env.service.commit(session, reservation, 10, "commit:replay"))
    again = await env.run(lambda session: env.service.commit(session, reservation, 10, "commit:replay"))
    assert again == commit
    second = await reserve(env, user, 5, "reserve:two")
    release = await env.run(lambda session: env.service.release(session, second, "release:replay"))
    assert await env.run(lambda session: env.service.release(session, second, "release:replay")) == release
    refund = CreditRef("refund", new_id())
    claw = ClawbackCommand(lot_id=first_lot, amount=20, reason="refund", ref=refund, key="refund:replay")
    clawed = await env.run(lambda session: env.service.clawback(session, claw))
    assert await env.run(lambda session: env.service.clawback(session, claw)) == clawed
    actor = env.users[2]
    adjust = AdjustCommand(user_id=user, delta=15, reason="bonus", actor_id=actor, key="adjust:replay")
    adjusted = await env.run(lambda session: env.service.adjust(session, adjust))
    assert await env.run(lambda session: env.service.adjust(session, adjust)) == adjusted

    assert await env.ledger_count(user) == 7
    audits = await env.run(
        lambda session: session.scalar(
            select(func.count()).select_from(AuditLogEntry).where(AuditLogEntry.target_id == str(user))
        )
    )
    assert audits == 1
    await assert_clean(env)


async def test_a_failed_operation_leaves_no_partial_writes(env: CreditsEnv) -> None:
    user = env.users[0]
    await grant(env, user, 50, "payment:small", expires_in=timedelta(days=1))
    env.clock.advance(timedelta(days=2))

    with pytest.raises(InsufficientCreditsError):
        await reserve(env, user, 10, "reserve:too-much")

    assert await balances(env, user) == (50, 0)
    assert await env.ledger_count(user) == 1
    await assert_clean(env)


async def test_unknown_users_are_reported_and_the_session_stays_usable(env: CreditsEnv) -> None:
    ghost = new_id()

    async def attempt(session: AsyncSession) -> None:
        with pytest.raises(CreditUserNotFoundError):
            await env.service.grant(session, GrantCommand(user_id=ghost, amount=5, source="promo", key="ghost:grant"))
        with pytest.raises(CreditUserNotFoundError):
            await record_usage(session, UsageEntry(user_id=ghost, stage="tts", provider="internal", key="ghost:usage"))
        assert await session.scalar(select(func.count()).select_from(CreditWallet)) is not None

    await env.run(attempt)


async def test_one_payment_cannot_create_two_lots_under_different_keys(env: CreditsEnv) -> None:
    payment = new_id()
    await grant(env, env.users[0], 10, "payment:a", payment=payment)

    with pytest.raises(DuplicateLotReferenceError):
        await grant(env, env.users[0], 10, "payment:b", payment=payment)

    assert await balances(env, env.users[0]) == (10, 0)


async def test_the_active_reservation_index_maps_to_a_conflict(
    env: CreditsEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    await grant(env, env.users[0], 100, "payment:index")
    await grant(env, env.users[1], 100, "payment:index-other")
    job = new_id()
    first = ReserveCommand(user_id=env.users[0], amount=10, ref_type="job", ref_id=job, key="job:a")
    second = ReserveCommand(user_id=env.users[1], amount=10, ref_type="job", ref_id=job, key="job:b")
    await env.run(lambda session: env.service.reserve(session, first))

    async def never_seen(_self: SqlCreditsRepository, ref_type: str, ref_id: UUID) -> None:
        del ref_type, ref_id

    monkeypatch.setattr(SqlCreditsRepository, "active_reservation_for", never_seen)
    with pytest.raises(ReservationAlreadyActiveError):
        await env.run(lambda session: env.service.reserve(session, second))

    assert await balances(env, env.users[1]) == (100, 0)


async def test_ledger_rows_are_ordered_by_the_operation_clock_not_the_transaction_start(env: CreditsEnv) -> None:
    user = env.users[0]
    await grant(env, user, 10, "payment:order-1")
    env.clock.advance(timedelta(seconds=5))
    await grant(env, user, 20, "payment:order-2")
    env.clock.advance(timedelta(seconds=5))
    await grant(env, user, 30, "payment:order-3")

    page = await env.run(lambda session: env.service.ledger(session, user, None, 2))
    assert [row.delta for row in page.items] == [30, 20]
    assert isinstance(page.next_cursor, Cursor)
    rest = await env.run(lambda session: env.service.ledger(session, user, page.next_cursor, 2))
    assert [row.delta for row in rest.items] == [10]
    assert rest.next_cursor is None
    await assert_clean(env)


async def test_expiry_and_stale_reservation_sweeps_run_through_the_tasks(env: CreditsEnv) -> None:
    first, second = env.users[0], env.users[1]
    await grant(env, first, 40, "payment:sweep-1", expires_in=timedelta(days=1))
    await grant(env, second, 25, "payment:sweep-2", expires_in=timedelta(days=1))
    await grant(env, first, 100, "payment:sweep-3")
    stale = await reserve(env, first, 30, "reserve:stale", ttl=timedelta(minutes=5))
    env.clock.advance(timedelta(days=2))
    transaction = env.database.transaction

    released = await credit_tasks.sweep_stale_reservations(transaction, env.service)
    expired = await credit_tasks.sweep_expired_lots(transaction, env.service)

    assert released == 1
    assert expired == 65
    assert await balances(env, first) == (100, 0)
    assert await balances(env, second) == (0, 0)
    status = await env.run(
        lambda session: session.scalar(select(CreditReservation.status).where(CreditReservation.id == stale))
    )
    assert status == "expired"
    assert await credit_tasks.sweep_expired_lots(transaction, env.service) == 0
    await assert_clean(env)


async def test_held_credits_survive_the_expiry_sweep_until_released(env: CreditsEnv) -> None:
    user = env.users[0]
    lot = await grant(env, user, 100, "payment:held", expires_in=timedelta(days=1))
    reservation = await reserve(env, user, 60, "reserve:held", ttl=timedelta(days=10))
    env.clock.advance(timedelta(days=2))

    assert await credit_tasks.sweep_expired_lots(env.database.transaction, env.service) == 40
    assert await lot_remaining(env, lot) == 60
    await env.run(lambda session: env.service.release(session, reservation, "release:held"))
    assert await credit_tasks.sweep_expired_lots(env.database.transaction, env.service) == 60
    assert await balances(env, user) == (0, 0)
    await assert_clean(env)


async def test_integrity_check_detects_a_corrupted_wallet_and_the_task_raises_an_alert(
    env: CreditsEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    healthy, broken = env.users[0], env.users[1]
    await grant(env, healthy, 100, "payment:healthy")
    await grant(env, broken, 100, "payment:broken")
    await reserve(env, broken, 25, "reserve:broken")
    await assert_clean(env)
    raised: list[tuple[str, dict[str, object]]] = []

    def capture(code: str, **fields: object) -> None:
        raised.append((code, fields))

    monkeypatch.setattr(credit_tasks, "raise_alert", capture)

    async def corrupt(session: AsyncSession) -> None:
        await session.execute(
            text("UPDATE credit_wallets SET balance = balance + 5 WHERE user_id = :id"), {"id": broken}
        )

    await env.run(corrupt)
    violations = await env.run(env.service.check_integrity)

    assert [violation.user_id for violation in violations] == [broken]
    found = {problem.invariant: (problem.expected, problem.actual) for problem in violations[0].problems}
    assert found == {
        "balance_equals_ledger_delta_sum": (100, 105),
        "balance_equals_lot_remaining_sum": (100, 105),
        "balance_equals_latest_balance_after": (100, 105),
    }

    await credit_tasks.verify_integrity(env.database.transaction, env.service)

    assert [code for code, _ in raised] == ["credit_integrity_violation"]
    assert raised[0][1]["user_ids"] == [str(broken)]
    assert await balances(env, broken) == (105, 25)


async def test_integrity_check_detects_drifted_lots_and_reservations(env: CreditsEnv) -> None:
    user = env.users[0]
    lot = await grant(env, user, 100, "payment:drift")
    reservation = await reserve(env, user, 30, "reserve:drift")

    async def drift(session: AsyncSession) -> None:
        await session.execute(text("UPDATE credit_lots SET remaining = remaining - 3 WHERE id = :id"), {"id": lot})
        await session.execute(
            text("UPDATE credit_reservations SET amount = amount - 1 WHERE id = :id"), {"id": reservation}
        )

    await env.run(drift)
    violations = await env.run(env.service.check_integrity)

    found = {problem.invariant for problem in violations[0].problems}
    assert found == {"balance_equals_lot_remaining_sum", "reserved_equals_active_reservations"}


async def test_usage_records_are_idempotent_and_aggregate_per_utc_day(env: CreditsEnv) -> None:
    user, other = env.users[0], env.users[1]

    async def write(session: AsyncSession) -> tuple[UUID, UUID]:
        entry = UsageEntry(user_id=user, stage="tts", provider="elevenlabs", key="usage:1", credits=4)
        first = await record_usage(session, entry)
        again = await record_usage(session, UsageEntry(user_id=user, stage="tts", provider="xx", key="usage:1"))
        await record_usage(
            session, UsageEntry(user_id=user, stage="render", provider="internal", key="usage:2", credits=6)
        )
        await record_usage(
            session, UsageEntry(user_id=other, stage="render", provider="internal", key="usage:3", credits=9)
        )
        return first, again

    first, again = await env.run(write)
    assert first == again
    count = await env.run(
        lambda session: session.scalar(select(func.count()).select_from(UsageRecord).where(UsageRecord.user_id == user))
    )
    assert count == 2

    today = env.clock.now().date()
    days = await env.run(
        lambda session: env.service.daily_usage(session, user, today - timedelta(days=1), today + timedelta(days=1))
    )
    assert [(item.credits, item.records) for item in days] == [(10, 2)]
    page = await env.run(lambda session: env.service.usage(session, user, None, 1))
    assert len(page.items) == 1
    assert page.next_cursor is not None
    theirs = await env.run(lambda session: env.service.usage(session, other, None, 10))
    assert len(theirs.items) == 1
    assert theirs.items[0].credits == 9


async def test_reminder_claims_never_hand_the_same_lot_to_two_workers(env: CreditsEnv) -> None:
    for index in range(6):
        await grant(env, env.users[index % 3], 5, f"payment:remind-{index}", expires_in=timedelta(days=3))

    claims = await asyncio.gather(
        *(env.run(lambda session: env.service.claim_expiry_reminders(session, 100)) for _ in range(4))
    )

    claimed_credits = sum(batch.credits for claim in claims for batch in claim)
    assert claimed_credits == 30
    assert await env.run(lambda session: env.service.claim_expiry_reminders(session, 100)) == []


async def test_concurrent_reservations_never_overdraw_the_wallet(env: CreditsEnv) -> None:
    user = env.users[0]
    await grant(env, user, 50, "payment:race")

    results = await asyncio.gather(
        *(reserve(env, user, 10, f"reserve:race:{index}") for index in range(CONCURRENCY)),
        return_exceptions=True,
    )

    succeeded = [item for item in results if isinstance(item, UUID)]
    failed = [item for item in results if isinstance(item, InsufficientCreditsError)]
    assert len(succeeded) == 5
    assert len(failed) == CONCURRENCY - 5
    assert await balances(env, user) == (50, 50)
    await assert_clean(env)


async def test_concurrent_commits_releases_and_clawbacks_keep_every_invariant(env: CreditsEnv) -> None:
    user = env.users[0]
    lot = await grant(env, user, 200, "payment:mixed", expires_in=timedelta(days=30))
    await grant(env, user, 100, "payment:mixed-forever")
    reservations = [await reserve(env, user, 20, f"reserve:mixed:{index}") for index in range(8)]

    operations = [
        *(env.run(lambda session, r=r: env.service.commit(session, r, 12, f"commit:{r}")) for r in reservations[:3]),
        *(env.run(lambda session, r=r: env.service.release(session, r, f"release:{r}")) for r in reservations[3:5]),
        *(
            env.run(
                lambda session, index=index: env.service.clawback(
                    session,
                    ClawbackCommand(
                        lot_id=lot, amount=25, reason="refund", ref=CreditRef("refund", new_id()), key=f"refund:{index}"
                    ),
                )
            )
            for index in range(4)
        ),
        *(reserve(env, user, 5, f"reserve:late:{index}") for index in range(3)),
    ]
    results = await asyncio.gather(*operations, return_exceptions=True)

    assert not [
        item for item in results if isinstance(item, BaseException) and not isinstance(item, InsufficientCreditsError)
    ]
    balance, reserved = await balances(env, user)
    assert 0 <= reserved <= balance
    await assert_clean(env)


async def test_concurrent_duplicates_of_one_key_write_exactly_one_ledger_row(env: CreditsEnv) -> None:
    user = env.users[0]
    payment = new_id()
    command = GrantCommand(
        user_id=user, amount=70, source="purchase", key="payment:dup", ref=CreditRef("payment", payment)
    )

    grants = await asyncio.gather(*(env.run(lambda session: env.service.grant(session, command)) for _ in range(8)))

    assert len({item.lot_id for item in grants}) == 1
    assert await env.ledger_count(user) == 1
    assert await balances(env, user) == (70, 0)

    job = new_id()
    reserve_command = ReserveCommand(user_id=user, amount=20, ref_type="job", ref_id=job, key="reserve:dup")
    reserved = await asyncio.gather(
        *(env.run(lambda session: env.service.reserve(session, reserve_command)) for _ in range(8))
    )
    assert len({item.id for item in reserved}) == 1
    assert await balances(env, user) == (70, 20)

    reservation = reserved[0].id
    commits = await asyncio.gather(
        *(env.run(lambda session: env.service.commit(session, reservation, 15, "commit:dup")) for _ in range(8))
    )
    assert len(set(commits)) == 1
    assert await balances(env, user) == (55, 0)
    assert await env.ledger_count(user) == 3
    await assert_clean(env)


async def test_concurrent_adjustments_cannot_push_the_balance_below_reserved(env: CreditsEnv) -> None:
    user = env.users[0]
    await grant(env, user, 100, "payment:adjust-race")
    await reserve(env, user, 40, "reserve:adjust-race")
    actor = env.users[2]

    results = await asyncio.gather(
        *(
            env.run(
                lambda session, index=index: env.service.adjust(
                    session,
                    AdjustCommand(user_id=user, delta=-20, reason="debit", actor_id=actor, key=f"adjust:race:{index}"),
                )
            )
            for index in range(6)
        ),
        return_exceptions=True,
    )

    assert len([item for item in results if not isinstance(item, BaseException)]) == 3
    assert await balances(env, user) == (40, 40)
    await assert_clean(env)


async def test_sweeps_running_alongside_user_operations_keep_every_invariant(env: CreditsEnv) -> None:
    user = env.users[0]
    for index in range(4):
        await grant(env, user, 50, f"payment:mix-{index}", expires_in=timedelta(hours=index + 1))
    await grant(env, user, 20, "payment:mix-forever")
    reservations = [
        await reserve(env, user, 10, f"reserve:mix:{index}", ttl=timedelta(minutes=1)) for index in range(5)
    ]
    env.clock.advance(timedelta(hours=2, minutes=30))
    transaction = env.database.transaction

    results = await asyncio.gather(
        credit_tasks.sweep_expired_lots(transaction, env.service),
        credit_tasks.sweep_stale_reservations(transaction, env.service),
        credit_tasks.sweep_expired_lots(transaction, env.service),
        *(env.run(lambda session, r=r: env.service.commit(session, r, 5, f"commit:mix:{r}")) for r in reservations[:3]),
        *(env.run(lambda session, r=r: env.service.release(session, r, f"release:mix:{r}")) for r in reservations[3:]),
        *(reserve(env, user, 5, f"reserve:mix-late:{index}") for index in range(3)),
        return_exceptions=True,
    )

    unexpected = [
        item
        for item in results
        if isinstance(item, BaseException)
        and not isinstance(item, ReservationNotActiveError | InsufficientCreditsError)
    ]
    assert unexpected == []
    balance, reserved = await balances(env, user)
    assert 0 <= reserved <= balance
    await assert_clean(env)
