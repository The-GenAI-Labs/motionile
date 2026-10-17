from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from hypothesis import strategies as st
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.credits import FakeCreditsStore, sign_rule_holds

from motionile.core.clock import FrozenClock
from motionile.core.errors import AppError
from motionile.core.ids import new_id
from motionile.modules.credits.domain import (
    AdjustCommand,
    Allocation,
    ClawbackCommand,
    CreditRef,
    GrantCommand,
    LedgerRefType,
    LotSource,
    ReserveCommand,
)
from motionile.modules.credits.exceptions import CreditInvariantError
from motionile.modules.credits.service import CreditsService

USER_COUNT = 2
SOURCES: tuple[LotSource, ...] = ("purchase", "subscription", "promo", "admin")
REF_TYPE_BY_SOURCE: dict[str, LedgerRefType] = {
    "purchase": "payment",
    "subscription": "payment",
    "promo": "promo",
    "admin": "admin",
}
RESERVATION_PURPOSES = ("job", "publication", "mcp_submission")

type Outcome = tuple[object, ...]


@dataclass(frozen=True)
class Grant:
    user: int
    amount: int
    source: LotSource
    expiry_seconds: int | None


@dataclass(frozen=True)
class Reserve:
    user: int
    amount: int
    ttl_seconds: int | None
    purpose: int


@dataclass(frozen=True)
class Commit:
    reservation: int
    permille: int
    active_only: bool


@dataclass(frozen=True)
class Spend:
    user: int
    amount: int
    permille: int


@dataclass(frozen=True)
class Release:
    reservation: int
    active_only: bool


@dataclass(frozen=True)
class Clawback:
    lot: int
    amount: int


@dataclass(frozen=True)
class Adjust:
    user: int
    delta: int
    expiry_seconds: int | None


@dataclass(frozen=True)
class Expire:
    user: int


@dataclass(frozen=True)
class SweepReservations:
    pass


@dataclass(frozen=True)
class Advance:
    seconds: int


@dataclass(frozen=True)
class Replay:
    call: int


type Op = Grant | Reserve | Commit | Spend | Release | Clawback | Adjust | Expire | SweepReservations | Advance | Replay


@dataclass(frozen=True)
class LotSnapshot:
    source: str
    amount: int
    remaining: int
    expires_at: datetime | None
    expired: bool


@dataclass(frozen=True)
class LedgerSnapshot:
    reason: str
    delta: int
    reserved_delta: int
    balance_after: int
    reserved_after: int


@dataclass(frozen=True)
class ReservationSnapshot:
    amount: int
    status: str
    committed_amount: int | None
    expires_at: datetime


@dataclass(frozen=True)
class UserSnapshot:
    balance: int
    reserved: int
    lots: tuple[LotSnapshot, ...]
    ledger: tuple[LedgerSnapshot, ...]
    reservations: tuple[ReservationSnapshot, ...]
    ledger_keys: tuple[str, ...]


type Snapshot = tuple[UserSnapshot, ...]


class Backend(Protocol):
    clock: FrozenClock
    service: CreditsService
    user_ids: list[UUID]

    def transaction(self) -> AbstractAsyncContextManager[AsyncSession]: ...

    async def snapshot(self) -> Snapshot: ...


class FakeBackend:
    def __init__(
        self, clock: FrozenClock, service: CreditsService, store: FakeCreditsStore, user_ids: list[UUID]
    ) -> None:
        self.clock = clock
        self.service = service
        self.store = store
        self.user_ids = user_ids

    def transaction(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self.store.transaction()

    async def snapshot(self) -> Snapshot:
        users: list[UserSnapshot] = []
        for user_id in self.user_ids:
            wallet = self.store.wallets.get(user_id)
            lots = sorted(
                (lot for lot in self.store.lots.values() if lot.user_id == user_id),
                key=lambda lot: (lot.created_at, lot.id),
            )
            reservations = sorted(
                (item for item in self.store.reservations.values() if item.user_id == user_id),
                key=lambda item: (item.created_at, item.id),
            )
            ledger = [entry for entry in self.store.ledger if entry.user_id == user_id]
            users.append(
                UserSnapshot(
                    balance=wallet.balance if wallet else 0,
                    reserved=wallet.reserved if wallet else 0,
                    lots=tuple(
                        LotSnapshot(lot.source, lot.amount, lot.remaining, lot.expires_at, lot.expired_at is not None)
                        for lot in lots
                    ),
                    ledger=tuple(
                        LedgerSnapshot(
                            entry.reason, entry.delta, entry.reserved_delta, entry.balance_after, entry.reserved_after
                        )
                        for entry in ledger
                    ),
                    reservations=tuple(
                        ReservationSnapshot(item.amount, item.status, item.committed_amount, item.expires_at)
                        for item in reservations
                    ),
                    ledger_keys=tuple(entry.idempotency_key for entry in ledger),
                )
            )
        return tuple(users)


def check_snapshot(snapshot: Snapshot) -> None:
    for user in snapshot:
        assert user.balance >= 0
        assert 0 <= user.reserved <= user.balance
        assert user.balance == sum(entry.delta for entry in user.ledger)
        assert user.balance == sum(lot.remaining for lot in user.lots)
        assert user.reserved == sum(entry.reserved_delta for entry in user.ledger)
        assert user.reserved == sum(item.amount for item in user.reservations if item.status == "active")
        if user.ledger:
            assert user.ledger[-1].balance_after == user.balance
            assert user.ledger[-1].reserved_after == user.reserved
        else:
            assert user.balance == 0
            assert user.reserved == 0
        for lot in user.lots:
            assert 0 <= lot.remaining <= lot.amount
            assert not lot.expired or lot.remaining == 0
        for entry in user.ledger:
            assert sign_rule_holds(entry.reason, entry.delta, entry.reserved_delta)
            assert entry.delta != 0 or entry.reserved_delta != 0
            assert 0 <= entry.reserved_after <= entry.balance_after
        assert len(set(user.ledger_keys)) == len(user.ledger_keys)


class Interpreter:
    def __init__(self, backend: Backend) -> None:
        self.backend = backend
        self.lot_ids: list[UUID] = []
        self.reservation_ids: list[UUID] = []
        self.active_ids: list[UUID] = []
        self.amounts: dict[UUID, int] = {}
        self.calls: list[tuple[Callable[[], Awaitable[Outcome]], Outcome]] = []
        self.steps = 0

    def user_id(self, index: int) -> UUID:
        return self.backend.user_ids[index % len(self.backend.user_ids)]

    def pick_reservation(self, index: int, *, active_only: bool) -> UUID | None:
        pool = self.active_ids if active_only else self.reservation_ids
        return pool[index % len(pool)] if pool else None

    def settle(self, reservation_id: UUID) -> None:
        if reservation_id in self.active_ids:
            self.active_ids.remove(reservation_id)

    def next_key(self) -> str:
        self.steps += 1
        return f"op:{self.steps}"

    def lot_index(self, lot_id: UUID) -> int:
        if lot_id not in self.lot_ids:
            self.lot_ids.append(lot_id)
        return self.lot_ids.index(lot_id)

    def allocations(self, allocations: tuple[Allocation, ...]) -> tuple[tuple[int, int], ...]:
        return tuple((self.lot_index(item.lot_id), item.amount) for item in allocations)

    async def run(self, call: Callable[[], Awaitable[Outcome]], *, replayable: Callable[[Outcome], bool]) -> Outcome:
        try:
            outcome = await call()
        except CreditInvariantError:
            raise
        except AppError as error:
            return ("error", error.code)
        if replayable(outcome):
            self.calls.append((call, outcome))
        return outcome

    async def apply(self, op: Op) -> Outcome:
        match op:
            case Grant():
                outcome = await self.grant(op)
            case Reserve():
                outcome = await self.reserve(op)
            case Commit():
                outcome = await self.commit(op)
            case Spend():
                outcome = await self.spend(op)
            case Release():
                outcome = await self.release(op)
            case Clawback():
                outcome = await self.clawback(op)
            case Adjust():
                outcome = await self.adjust(op)
            case Expire():
                outcome = await self.expire(op)
            case SweepReservations():
                outcome = await self.sweep()
            case Advance():
                self.backend.clock.advance(timedelta(seconds=op.seconds))
                outcome = ("advance", op.seconds)
            case Replay():
                outcome = await self.replay(op)
        return outcome

    async def grant(self, op: Grant) -> Outcome:
        expires_at = (
            self.backend.clock.now() + timedelta(seconds=op.expiry_seconds) if op.expiry_seconds is not None else None
        )
        command = GrantCommand(
            user_id=self.user_id(op.user),
            amount=op.amount,
            source=op.source,
            key=self.next_key(),
            expires_at=expires_at,
            ref=CreditRef(REF_TYPE_BY_SOURCE[op.source], new_id()),
        )

        async def call() -> Outcome:
            async with self.backend.transaction() as session:
                result = await self.backend.service.grant(session, command)
            return ("grant", result.amount, result.balance_after, result.expires_at, self.lot_index(result.lot_id))

        return await self.run(call, replayable=lambda _: True)

    async def reserve(self, op: Reserve) -> Outcome:
        command = ReserveCommand(
            user_id=self.user_id(op.user),
            amount=op.amount,
            ref_type=RESERVATION_PURPOSES[op.purpose % len(RESERVATION_PURPOSES)],
            ref_id=new_id(),
            key=self.next_key(),
            ttl=timedelta(seconds=op.ttl_seconds) if op.ttl_seconds is not None else None,
        )

        async def call() -> Outcome:
            async with self.backend.transaction() as session:
                result = await self.backend.service.reserve(session, command)
            if result.id not in self.reservation_ids:
                self.reservation_ids.append(result.id)
                self.active_ids.append(result.id)
                self.amounts[result.id] = result.amount
            return ("reserve", result.amount, result.reserved_after, result.expires_at)

        return await self.run(call, replayable=lambda _: True)

    async def commit(self, op: Commit) -> Outcome:
        reservation_id = self.pick_reservation(op.reservation, active_only=op.active_only)
        if reservation_id is None:
            return ("skip",)
        return await self.commit_reservation(reservation_id, op.permille)

    async def spend(self, op: Spend) -> Outcome:
        reserved = await self.reserve(Reserve(op.user, op.amount, None, 0))
        if reserved[0] != "reserve":
            return reserved
        return await self.commit_reservation(self.active_ids[-1], op.permille)

    async def commit_reservation(self, reservation_id: UUID, permille: int) -> Outcome:
        key = self.next_key()
        actual = self.amounts[reservation_id] * permille // 1000

        async def call() -> Outcome:
            async with self.backend.transaction() as session:
                result = await self.backend.service.commit(session, reservation_id, actual, key)
            self.settle(reservation_id)
            return (
                "commit",
                result.charged,
                result.released,
                self.allocations(result.allocations),
                result.balance_after,
                result.reserved_after,
            )

        return await self.run(call, replayable=lambda _: True)

    async def release(self, op: Release) -> Outcome:
        reservation_id = self.pick_reservation(op.reservation, active_only=op.active_only)
        if reservation_id is None:
            return ("skip",)
        key = self.next_key()

        async def call() -> Outcome:
            async with self.backend.transaction() as session:
                result = await self.backend.service.release(session, reservation_id, key)
            self.settle(reservation_id)
            return ("release", result.released, result.reserved_after)

        return await self.run(call, replayable=lambda _: True)

    async def clawback(self, op: Clawback) -> Outcome:
        if not self.lot_ids:
            return ("skip",)
        command = ClawbackCommand(
            lot_id=self.lot_ids[op.lot % len(self.lot_ids)],
            amount=op.amount,
            reason="refund",
            ref=CreditRef("refund", new_id()),
            key=self.next_key(),
        )

        async def call() -> Outcome:
            async with self.backend.transaction() as session:
                result = await self.backend.service.clawback(session, command)
            return ("clawback", result.requested, result.clawed_back, result.balance_after)

        return await self.run(call, replayable=lambda outcome: outcome[2] != 0)

    async def adjust(self, op: Adjust) -> Outcome:
        expires_at = (
            self.backend.clock.now() + timedelta(seconds=op.expiry_seconds)
            if op.expiry_seconds is not None and op.delta > 0
            else None
        )
        command = AdjustCommand(
            user_id=self.user_id(op.user),
            delta=op.delta,
            reason="support adjustment",
            actor_id=new_id(),
            key=self.next_key(),
            expires_at=expires_at,
        )

        async def call() -> Outcome:
            async with self.backend.transaction() as session:
                result = await self.backend.service.adjust(session, command)
            lot_index = self.lot_index(result.lot_id) if result.lot_id is not None else None
            return ("adjust", result.delta, lot_index, self.allocations(result.allocations), result.balance_after)

        return await self.run(call, replayable=lambda _: True)

    async def expire(self, op: Expire) -> Outcome:
        async def call() -> Outcome:
            async with self.backend.transaction() as session:
                result = await self.backend.service.expire_due_lots(session, self.user_id(op.user))
            return ("expire", result.expired)

        return await self.run(call, replayable=lambda _: False)

    async def sweep(self) -> Outcome:
        async def call() -> Outcome:
            released = 0
            async with self.backend.transaction() as session:
                ids = await self.backend.service.stale_reservation_ids(session, None, 1000)
            for reservation_id in ids:
                async with self.backend.transaction() as session:
                    if await self.backend.service.release_stale(session, reservation_id) is not None:
                        released += 1
                        self.settle(reservation_id)
            return ("sweep", released)

        return await self.run(call, replayable=lambda _: False)

    async def replay(self, op: Replay) -> Outcome:
        if not self.calls:
            return ("skip",)
        call, original = self.calls[op.call % len(self.calls)]
        before = await self.backend.snapshot()
        again = await call()
        after = await self.backend.snapshot()
        assert again == original
        assert after == before
        return ("replay", original)

    async def check(self) -> None:
        check_snapshot(await self.backend.snapshot())
        async with self.backend.transaction() as session:
            assert await self.backend.service.check_integrity(session) == []


def build_ops() -> st.SearchStrategy[Op]:
    users = st.integers(0, USER_COUNT - 1)
    expiry = st.one_of(
        st.none(), st.none(), st.integers(30, 1_800), st.integers(1_800, 20_000), st.integers(20_000, 3_500_000)
    )
    active_only = st.sampled_from([True, True, True, True, True, False])
    grant = st.builds(
        Grant,
        user=users,
        amount=st.integers(20, 250),
        source=st.sampled_from(SOURCES),
        expiry_seconds=expiry,
    )
    reserve = st.builds(
        Reserve,
        user=users,
        amount=st.integers(1, 90),
        ttl_seconds=st.one_of(st.none(), st.integers(60, 3_000), st.integers(3_000, 90_000)),
        purpose=st.integers(0, 2),
    )
    commit = st.builds(
        Commit,
        reservation=st.integers(0, 50),
        permille=st.one_of(st.integers(0, 1000), st.integers(0, 1000), st.integers(1001, 1500)),
        active_only=active_only,
    )
    spend = st.builds(
        Spend,
        user=users,
        amount=st.integers(1, 120),
        permille=st.one_of(st.integers(0, 1000), st.integers(0, 1000), st.integers(1001, 1200)),
    )
    release = st.builds(Release, reservation=st.integers(0, 50), active_only=active_only)
    clawback = st.builds(Clawback, lot=st.integers(0, 50), amount=st.integers(1, 450))
    adjust = st.builds(
        Adjust,
        user=users,
        delta=st.integers(-200, 200).filter(lambda value: value != 0),
        expiry_seconds=expiry,
    )
    expire = st.builds(Expire, user=users)
    sweep = st.just(SweepReservations())
    advance = st.builds(
        Advance,
        seconds=st.one_of(st.integers(1, 900), st.integers(900, 7_200), st.integers(7_200, 4_000_000)),
    )
    replay = st.builds(Replay, call=st.integers(0, 500))
    return st.one_of(
        grant,
        grant,
        reserve,
        reserve,
        reserve,
        reserve,
        commit,
        commit,
        spend,
        spend,
        spend,
        release,
        release,
        clawback,
        adjust,
        expire,
        sweep,
        advance,
        advance,
        replay,
        replay,
    )
