from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import TypedDict, Unpack
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.credits import FakeAudit, FakeCreditsStore
from tests.fakes.settings import make_settings

from motionile.core.clock import FrozenClock
from motionile.core.ids import new_id
from motionile.modules.credits import (
    CreditRef,
    CreditsService,
    GrantCommand,
    GrantResult,
    ReservationResult,
    ReserveCommand,
)
from motionile.modules.credits.domain import LotSource

START = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)


class GrantOptions(TypedDict, total=False):
    source: LotSource
    expires_in: timedelta
    user_id: UUID
    key: str
    payment_id: UUID


class Harness:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.clock = FrozenClock(START)
        self.store = FakeCreditsStore(self.clock)
        self.audit = FakeAudit()
        self.service = CreditsService(self.clock, make_settings().billing, store_factory=self.store, audit=self.audit)
        self.user_id = new_id()
        self.counter = 0

    def key(self, prefix: str = "k") -> str:
        self.counter += 1
        return f"{prefix}:{self.counter}"

    async def grant(self, amount: int, **options: Unpack[GrantOptions]) -> GrantResult:
        expires_in = options.get("expires_in")
        key = options.get("key")
        return await self.service.grant(
            self.session,
            GrantCommand(
                user_id=options.get("user_id") or self.user_id,
                amount=amount,
                source=options.get("source", "purchase"),
                key=key if key is not None else self.key("grant"),
                expires_at=self.clock.now() + expires_in if expires_in is not None else None,
                ref=CreditRef("payment", options.get("payment_id") or new_id()),
            ),
        )

    async def reserve(
        self,
        amount: int,
        *,
        ttl: timedelta | None = None,
        user_id: UUID | None = None,
        key: str | None = None,
        ref_id: UUID | None = None,
    ) -> ReservationResult:
        return await self.service.reserve(
            self.session,
            ReserveCommand(
                user_id=user_id or self.user_id,
                amount=amount,
                ref_type="job",
                ref_id=ref_id or new_id(),
                key=key if key is not None else self.key("reserve"),
                ttl=ttl,
            ),
        )

    def wallet(self, user_id: UUID | None = None) -> tuple[int, int]:
        record = self.store.wallets[user_id or self.user_id]
        return record.balance, record.reserved

    def lot_remaining(self, lot_id: UUID) -> int:
        return self.store.lots[lot_id].remaining

    def ledger(self, user_id: UUID | None = None) -> list[tuple[str, int, int]]:
        return [
            (entry.reason, entry.delta, entry.reserved_delta)
            for entry in self.store.ledger
            if entry.user_id == (user_id or self.user_id)
        ]


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    opened = AsyncSession()
    yield opened
    await opened.close()


@pytest.fixture
def harness(session: AsyncSession) -> Harness:
    return Harness(session)
