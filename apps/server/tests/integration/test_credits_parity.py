import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from hypothesis import HealthCheck, given
from hypothesis import settings as hypothesis_settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.credits import FakeAudit, FakeCreditsStore
from tests.fakes.credits_ops import (
    USER_COUNT,
    FakeBackend,
    Interpreter,
    LedgerSnapshot,
    LotSnapshot,
    Op,
    ReservationSnapshot,
    Snapshot,
    UserSnapshot,
    build_ops,
)
from tests.integration.credit_support import create_users, purge_credit_data

from motionile.core.clock import FrozenClock
from motionile.core.config import Settings
from motionile.core.db import Database
from motionile.core.resources import build_resources
from motionile.modules.credits import CreditLedgerEntry, CreditLot, CreditReservation, CreditsService, CreditWallet

START = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


class SqlBackend:
    def __init__(self, database: Database, clock: FrozenClock, service: CreditsService, user_ids: list[UUID]) -> None:
        self.database = database
        self.clock = clock
        self.service = service
        self.user_ids = user_ids

    def transaction(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self.database.transaction()

    async def snapshot(self) -> Snapshot:
        async with self.database.transaction() as session:
            return tuple([await self.user_snapshot(session, user_id) for user_id in self.user_ids])

    async def user_snapshot(self, session: AsyncSession, user_id: UUID) -> UserSnapshot:
        wallet = await session.scalar(select(CreditWallet).where(CreditWallet.user_id == user_id))
        lots = await session.scalars(
            select(CreditLot).where(CreditLot.user_id == user_id).order_by(CreditLot.created_at, CreditLot.id)
        )
        reservations = await session.scalars(
            select(CreditReservation)
            .where(CreditReservation.user_id == user_id)
            .order_by(CreditReservation.created_at, CreditReservation.id)
        )
        ledger = list(
            await session.scalars(
                select(CreditLedgerEntry)
                .where(CreditLedgerEntry.user_id == user_id)
                .order_by(CreditLedgerEntry.created_at, CreditLedgerEntry.id)
            )
        )
        return UserSnapshot(
            balance=wallet.balance if wallet else 0,
            reserved=wallet.reserved if wallet else 0,
            lots=tuple(
                LotSnapshot(lot.source, lot.amount, lot.remaining, lot.expires_at, lot.expired_at is not None)
                for lot in lots
            ),
            ledger=tuple(
                LedgerSnapshot(e.reason, e.delta, e.reserved_delta, e.balance_after, e.reserved_after) for e in ledger
            ),
            reservations=tuple(
                ReservationSnapshot(item.amount, item.status, item.committed_amount, item.expires_at)
                for item in reservations
            ),
            ledger_keys=tuple(entry.idempotency_key for entry in ledger),
        )


def comparable(snapshot: Snapshot) -> Snapshot:
    return tuple(replace(user, ledger_keys=()) for user in snapshot)


async def play(settings_value: Settings, operations: list[Op]) -> None:
    resources = build_resources(settings_value, application_name="motionile-credits-parity")
    users = await create_users(resources.database, USER_COUNT)
    try:
        fake_clock, sql_clock = FrozenClock(START), FrozenClock(START)
        fake_store = FakeCreditsStore(fake_clock, set(users))
        fake_service = CreditsService(
            fake_clock, resources.settings.billing, store_factory=fake_store, audit=FakeAudit()
        )
        fake = Interpreter(FakeBackend(fake_clock, fake_service, fake_store, users))
        sql_service = CreditsService(sql_clock, resources.settings.billing, audit=FakeAudit())
        sql = Interpreter(SqlBackend(resources.database, sql_clock, sql_service, users))
        for operation in operations:
            expected = await fake.apply(operation)
            actual = await sql.apply(operation)
            assert actual == expected, operation
            await fake.check()
            await sql.check()
            assert comparable(await sql.backend.snapshot()) == comparable(await fake.backend.snapshot()), operation
    finally:
        await purge_credit_data(resources.database, users)
        await resources.aclose()


@pytest.mark.slow
@hypothesis_settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(operations=st.lists(build_ops(), min_size=25, max_size=40))
def test_the_sql_repository_behaves_exactly_like_the_in_memory_one(settings: Settings, operations: list[Op]) -> None:
    asyncio.run(play(settings, operations))
