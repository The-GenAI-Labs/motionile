from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import FrozenClock
from motionile.core.db import Database
from motionile.core.ids import new_id
from motionile.core.resources import Resources
from motionile.modules.credits import CreditLedgerEntry, CreditsService
from motionile.modules.users import User

CREDIT_TABLES = "credit_ledger, credit_reservations, credit_lots, credit_wallets, usage_records"


@dataclass
class CreditsEnv:
    resources: Resources
    clock: FrozenClock
    service: CreditsService
    users: list[UUID]

    @property
    def database(self) -> Database:
        return self.resources.database

    async def run[ResultT](self, operation: Callable[[AsyncSession], Awaitable[ResultT]]) -> ResultT:
        async with self.database.transaction() as session:
            return await operation(session)

    async def ledger_count(self, user_id: UUID) -> int:
        async with self.database.transaction() as session:
            return (
                await session.scalar(
                    select(func.count()).select_from(CreditLedgerEntry).where(CreditLedgerEntry.user_id == user_id)
                )
                or 0
            )


def new_clock() -> FrozenClock:
    return FrozenClock(datetime.now(UTC).replace(microsecond=0))


async def create_users(database: Database, count: int) -> list[UUID]:
    ids = [new_id() for _ in range(count)]
    async with database.transaction() as session:
        for user_id in ids:
            session.add(User(id=user_id, name="Credits integration", status="active"))
    return ids


async def purge_credit_data(database: Database, user_ids: list[UUID]) -> None:
    async with database.transaction() as session:
        await session.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
        await session.execute(text(f"TRUNCATE {CREDIT_TABLES}"))
        await session.execute(text("DELETE FROM audit_log WHERE action = 'credits.adjusted'"))
        await session.execute(delete(User).where(User.id.in_(user_ids)))
