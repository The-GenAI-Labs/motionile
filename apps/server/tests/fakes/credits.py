from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from datetime import date, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.modules.audit import AuditEvent
from motionile.modules.credits.domain import (
    DailyUsage,
    LedgerRecord,
    LotRecord,
    ReservationRecord,
    UsageEntry,
    UsageRow,
    WalletAudit,
    WalletRecord,
    consumption_order,
)
from motionile.modules.credits.exceptions import (
    ActiveReservationExistsError,
    LotReferenceExistsError,
    UnknownCreditUserError,
)

SIGN_RULES: dict[str, tuple[str, str]] = {
    "purchase": ("positive", "zero"),
    "subscription_grant": ("positive", "zero"),
    "promo_grant": ("positive", "zero"),
    "admin_adjust": ("nonzero", "zero"),
    "reserve": ("zero", "positive"),
    "commit": ("non_positive", "negative"),
    "release": ("zero", "negative"),
    "refund_clawback": ("negative", "zero"),
    "expiry": ("negative", "zero"),
}
SIGN_TESTS: dict[str, Callable[[int], bool]] = {
    "positive": lambda value: value > 0,
    "negative": lambda value: value < 0,
    "zero": lambda value: value == 0,
    "nonzero": lambda value: value != 0,
    "non_positive": lambda value: value <= 0,
}


class ConstraintViolationError(AssertionError):
    pass


def sign_rule_holds(reason: str, delta: int, reserved_delta: int) -> bool:
    delta_rule, reserved_rule = SIGN_RULES[reason]
    return SIGN_TESTS[delta_rule](delta) and SIGN_TESTS[reserved_rule](reserved_delta)


@dataclass(frozen=True)
class StoredUsage:
    id: UUID
    entry: UsageEntry
    created_at: datetime


@dataclass(frozen=True)
class StoreState:
    wallets: dict[UUID, WalletRecord]
    lots: dict[UUID, LotRecord]
    reservations: dict[UUID, ReservationRecord]
    ledger: list[LedgerRecord]
    usage: list[StoredUsage]


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    async def __call__(self, session: AsyncSession, event: AuditEvent) -> UUID:
        del session
        self.events.append(event)
        return new_id()


class FakeCreditsStore:
    def __init__(self, clock: Clock, known_users: set[UUID] | None = None) -> None:
        self.clock = clock
        self.known_users = known_users
        self.wallets: dict[UUID, WalletRecord] = {}
        self.lots: dict[UUID, LotRecord] = {}
        self.reservations: dict[UUID, ReservationRecord] = {}
        self.ledger: list[LedgerRecord] = []
        self.usage: list[StoredUsage] = []

    def __call__(self, session: AsyncSession) -> "FakeCreditsStore":
        del session
        return self

    def snapshot(self) -> StoreState:
        return StoreState(
            wallets=dict(self.wallets),
            lots=dict(self.lots),
            reservations=dict(self.reservations),
            ledger=list(self.ledger),
            usage=list(self.usage),
        )

    def restore(self, state: StoreState) -> None:
        self.wallets = dict(state.wallets)
        self.lots = dict(state.lots)
        self.reservations = dict(state.reservations)
        self.ledger = list(state.ledger)
        self.usage = list(state.usage)

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        state = self.snapshot()
        session = AsyncSession()
        try:
            yield session
        except BaseException:
            self.restore(state)
            raise
        finally:
            await session.close()

    async def ensure_wallet(self, user_id: UUID) -> None:
        if self.known_users is not None and user_id not in self.known_users:
            raise UnknownCreditUserError(user_id)
        self.wallets.setdefault(user_id, WalletRecord(user_id=user_id, balance=0, reserved=0, version=0))

    async def wallet(self, user_id: UUID) -> WalletRecord | None:
        return self.wallets.get(user_id)

    async def lock_wallet(self, user_id: UUID) -> WalletRecord | None:
        return self.wallets.get(user_id)

    async def save_wallet(self, wallet: WalletRecord) -> None:
        if wallet.balance < 0 or wallet.reserved < 0 or wallet.reserved > wallet.balance:
            raise ConstraintViolationError("ck_credit_wallets")
        self.wallets[wallet.user_id] = wallet

    async def ledger_by_key(self, key: str) -> LedgerRecord | None:
        return next((entry for entry in self.ledger if entry.idempotency_key == key), None)

    async def add_ledger(self, entry: LedgerRecord) -> None:
        if any(existing.idempotency_key == entry.idempotency_key for existing in self.ledger):
            raise ConstraintViolationError("uq_credit_ledger_idempotency_key")
        if not sign_rule_holds(entry.reason, entry.delta, entry.reserved_delta):
            raise ConstraintViolationError("ck_credit_ledger_reason_deltas")
        if entry.delta == 0 and entry.reserved_delta == 0:
            raise ConstraintViolationError("ck_credit_ledger_moves_credits")
        if not 0 <= entry.reserved_after <= entry.balance_after:
            raise ConstraintViolationError("ck_credit_ledger_after_range")
        if (entry.ref_type is None) != (entry.ref_id is None):
            raise ConstraintViolationError("ck_credit_ledger_ref_consistent")
        self.ledger.append(entry)

    async def lot_owner(self, lot_id: UUID) -> UUID | None:
        lot = self.lots.get(lot_id)
        return lot.user_id if lot else None

    async def lot_by_reference(self, ref_type: str, ref_id: UUID) -> LotRecord | None:
        matches = [lot for lot in self.lots.values() if lot.ref_type == ref_type and lot.ref_id == ref_id]
        return min(matches, key=lambda lot: (lot.created_at, lot.id), default=None)

    async def lock_lot(self, lot_id: UUID) -> LotRecord | None:
        return self.lots.get(lot_id)

    async def lock_open_lots(self, user_id: UUID) -> list[LotRecord]:
        lots = [lot for lot in self.lots.values() if lot.user_id == user_id and lot.remaining > 0]
        return sorted(lots, key=consumption_order)

    async def lock_expired_lots(self, user_id: UUID, now: datetime) -> list[LotRecord]:
        return [
            lot for lot in await self.lock_open_lots(user_id) if lot.expires_at is not None and lot.expires_at <= now
        ]

    async def add_lot(self, lot: LotRecord) -> None:
        if lot.amount <= 0 or not 0 <= lot.remaining <= lot.amount:
            raise ConstraintViolationError("ck_credit_lots_remaining_range")
        if (lot.ref_type is None) != (lot.ref_id is None):
            raise ConstraintViolationError("ck_credit_lots_ref_consistent")
        if lot.ref_id is not None and any(
            (existing.source, existing.ref_type, existing.ref_id) == (lot.source, lot.ref_type, lot.ref_id)
            for existing in self.lots.values()
        ):
            raise LotReferenceExistsError
        self.lots[lot.id] = lot

    async def save_lot(self, lot: LotRecord) -> None:
        if not 0 <= lot.remaining <= lot.amount:
            raise ConstraintViolationError("ck_credit_lots_remaining_range")
        if lot.expired_at is not None and lot.remaining != 0:
            raise ConstraintViolationError("ck_credit_lots_expired_consistent")
        self.lots[lot.id] = lot

    async def reservation_owner(self, reservation_id: UUID) -> UUID | None:
        reservation = self.reservations.get(reservation_id)
        return reservation.user_id if reservation else None

    async def reservation(self, reservation_id: UUID) -> ReservationRecord | None:
        return self.reservations.get(reservation_id)

    async def lock_reservation(self, reservation_id: UUID) -> ReservationRecord | None:
        return self.reservations.get(reservation_id)

    async def active_reservation_for(self, ref_type: str, ref_id: UUID) -> ReservationRecord | None:
        return next(
            (
                item
                for item in self.reservations.values()
                if item.status == "active" and (item.ref_type, item.ref_id) == (ref_type, ref_id)
            ),
            None,
        )

    async def add_reservation(self, reservation: ReservationRecord) -> None:
        if reservation.amount <= 0:
            raise ConstraintViolationError("ck_credit_reservations_amount_positive")
        if reservation.status == "active" and await self.active_reservation_for(
            reservation.ref_type, reservation.ref_id
        ):
            raise ActiveReservationExistsError
        if any(item.idempotency_key == reservation.idempotency_key for item in self.reservations.values()):
            raise ConstraintViolationError("uq_credit_reservations_idempotency_key")
        self.reservations[reservation.id] = reservation

    async def save_reservation(self, reservation: ReservationRecord) -> None:
        if reservation.committed_amount is not None and not 0 <= reservation.committed_amount <= reservation.amount:
            raise ConstraintViolationError("ck_credit_reservations_committed_range")
        if (reservation.status == "committed") != (reservation.committed_amount is not None):
            raise ConstraintViolationError("ck_credit_reservations_committed_consistent")
        if (reservation.status == "active") != (reservation.settled_at is None):
            raise ConstraintViolationError("ck_credit_reservations_settled_consistent")
        self.reservations[reservation.id] = reservation

    async def expired_lot_remaining(self, user_id: UUID, now: datetime) -> int:
        return sum(lot.remaining for lot in await self.lock_expired_lots(user_id, now))

    async def expiring_lots(self, user_id: UUID, after: datetime, before: datetime) -> list[LotRecord]:
        return [
            lot
            for lot in await self.lock_open_lots(user_id)
            if lot.expires_at is not None and after < lot.expires_at <= before
        ]

    async def users_with_expirable_lots(self, now: datetime, after: UUID | None, limit: int) -> list[UUID]:
        users = {
            lot.user_id
            for lot in self.lots.values()
            if lot.remaining > 0
            and lot.expires_at is not None
            and lot.expires_at <= now
            and self.wallets[lot.user_id].balance > self.wallets[lot.user_id].reserved
        }
        return [user for user in sorted(users) if after is None or user > after][:limit]

    async def stale_reservations(self, now: datetime, after: UUID | None, limit: int) -> list[ReservationRecord]:
        stale = [
            item
            for item in self.reservations.values()
            if item.status == "active" and item.expires_at <= now and (after is None or item.id > after)
        ]
        return sorted(stale, key=lambda item: item.id)[:limit]

    async def claim_expiry_reminders(self, now: datetime, before: datetime, limit: int) -> list[LotRecord]:
        candidates = sorted(
            (
                lot
                for lot in self.lots.values()
                if lot.remaining > 0
                and lot.expires_at is not None
                and now < lot.expires_at <= before
                and lot.expiry_reminder_sent_at is None
            ),
            key=lambda lot: (lot.expires_at or now, lot.id),
        )[:limit]
        claimed = [replace(lot, expiry_reminder_sent_at=now) for lot in candidates]
        for lot in claimed:
            self.lots[lot.id] = lot
        return claimed

    async def ledger_page(self, user_id: UUID, cursor: Cursor | None, limit: int) -> list[LedgerRecord]:
        rows = [entry for entry in self.ledger if entry.user_id == user_id]
        rows.sort(key=lambda entry: (entry.created_at, entry.id), reverse=True)
        if cursor is not None:
            rows = [entry for entry in rows if (entry.created_at, entry.id) < (cursor.created_at, cursor.id)]
        return rows[: limit + 1]

    async def usage_page(self, user_id: UUID, cursor: Cursor | None, limit: int) -> list[UsageRow]:
        rows = [item for item in self.usage if item.entry.user_id == user_id]
        rows.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        if cursor is not None:
            rows = [item for item in rows if (item.created_at, item.id) < (cursor.created_at, cursor.id)]
        return [
            UsageRow(
                id=item.id,
                stage=item.entry.stage,
                credits=item.entry.credits,
                job_id=item.entry.job_id,
                publication_id=item.entry.publication_id,
                created_at=item.created_at,
            )
            for item in rows[: limit + 1]
        ]

    async def usage_daily(self, user_id: UUID, start: date, end: date) -> list[DailyUsage]:
        totals: dict[date, tuple[int, int]] = {}
        for item in self.usage:
            day = item.created_at.date()
            if item.entry.user_id == user_id and start <= day <= end:
                spent, records = totals.get(day, (0, 0))
                totals[day] = (spent + item.entry.credits, records + 1)
        return [DailyUsage(date=day, credits=totals[day][0], records=totals[day][1]) for day in sorted(totals)]

    async def insert_usage(self, entry: UsageEntry) -> UUID:
        if self.known_users is not None and entry.user_id not in self.known_users:
            raise UnknownCreditUserError(entry.user_id)
        for item in self.usage:
            if item.entry.key == entry.key:
                return item.id
        stored = StoredUsage(id=new_id(), entry=entry, created_at=self.clock.now())
        self.usage.append(stored)
        return stored.id

    async def wallet_audits(self) -> list[WalletAudit]:
        audits: list[WalletAudit] = []
        for wallet in self.wallets.values():
            rows = [entry for entry in self.ledger if entry.user_id == wallet.user_id]
            latest = rows[-1] if rows else None
            audit = WalletAudit(
                user_id=wallet.user_id,
                balance=wallet.balance,
                reserved=wallet.reserved,
                ledger_delta_sum=sum(entry.delta for entry in rows),
                ledger_reserved_sum=sum(entry.reserved_delta for entry in rows),
                lot_remaining_sum=sum(lot.remaining for lot in self.lots.values() if lot.user_id == wallet.user_id),
                active_reservation_sum=sum(
                    item.amount
                    for item in self.reservations.values()
                    if item.user_id == wallet.user_id and item.status == "active"
                ),
                latest_balance_after=latest.balance_after if latest else 0,
                latest_reserved_after=latest.reserved_after if latest else 0,
                negative_lots=sum(
                    1 for lot in self.lots.values() if lot.user_id == wallet.user_id and lot.remaining < 0
                ),
            )
            if audit.problems():
                audits.append(audit)
        return sorted(audits, key=lambda audit: audit.user_id)
