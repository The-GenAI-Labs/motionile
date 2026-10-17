import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.alerts import raise_alert
from motionile.core.clock import Clock
from motionile.core.config import BillingSettings
from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.modules.audit import ActorType, AuditEvent
from motionile.modules.audit import record as record_audit
from motionile.modules.credits.domain import (
    GRANT_REASON_BY_SOURCE,
    GRANT_REASONS,
    LOT_REF_TYPES,
    MAX_KEY_LENGTH,
    MAX_USAGE_RANGE_DAYS,
    REASON_TEXT_LIMIT,
    AdjustCommand,
    AdjustResult,
    Allocation,
    ClawbackCommand,
    ClawbackResult,
    CommitResult,
    CreditRef,
    DailyUsage,
    ExpiringLot,
    ExpiryResult,
    GrantCommand,
    GrantResult,
    IntegrityViolation,
    JsonObject,
    LedgerRecord,
    LotRecord,
    Page,
    ReleaseResult,
    ReminderBatch,
    ReservationRecord,
    ReservationResult,
    ReserveCommand,
    UsageEntry,
    UsageRow,
    WalletRecord,
    WalletView,
    allocate,
)
from motionile.modules.credits.exceptions import (
    ActiveReservationExistsError,
    AdjustmentExceedsAvailableError,
    CommitExceedsReservationError,
    CreditInvariantError,
    CreditUserNotFoundError,
    DuplicateLotReferenceError,
    IdempotencyKeyConflictError,
    InsufficientCreditsError,
    InvalidAdjustmentReasonError,
    InvalidCreditAmountError,
    InvalidCreditExpiryError,
    InvalidCreditReferenceError,
    InvalidIdempotencyKeyError,
    InvalidUsageRangeError,
    LotNotFoundError,
    LotReferenceExistsError,
    ReservationAlreadyActiveError,
    ReservationNotActiveError,
    ReservationNotFoundError,
    UnknownCreditUserError,
)
from motionile.modules.credits.repository import CreditsStore, SqlCreditsRepository

RESERVATION_REF_TYPE = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
REFUND_REF_TYPE = "refund"
DEFAULT_USAGE_WINDOW_DAYS = 30

type StoreFactory = Callable[[AsyncSession], CreditsStore]
type AuditRecorder = Callable[[AsyncSession, AuditEvent], Awaitable[UUID]]


@dataclass(frozen=True)
class Posting:
    reason: str
    delta: int
    reserved_delta: int
    key: str
    ref: CreditRef | None
    metadata: JsonObject


@dataclass(frozen=True)
class Expected:
    reasons: frozenset[str]
    ref_id: UUID | None = None
    delta: int | None = None
    reserved_delta: int | None = None
    metadata: JsonObject = field(default_factory=dict[str, Any])


@dataclass(frozen=True)
class Settlement:
    final_status: str
    cause: str
    stale_only: bool


MANUAL_RELEASE = Settlement(final_status="released", cause="release", stale_only=False)
TTL_RELEASE = Settlement(final_status="expired", cause="ttl", stale_only=True)


class Positioned(Protocol):
    @property
    def created_at(self) -> datetime: ...

    @property
    def id(self) -> UUID: ...


def page_of[RowT: Positioned](rows: Sequence[RowT], limit: int) -> Page[RowT]:
    items = list(rows[:limit])
    more = len(rows) > limit and bool(items)
    return Page(items=items, next_cursor=Cursor(items[-1].created_at, items[-1].id) if more else None)


def allocations_metadata(allocations: Sequence[Allocation]) -> list[dict[str, Any]]:
    return [{"lotId": str(item.lot_id), "amount": item.amount} for item in allocations]


def allocations_of(metadata: JsonObject) -> tuple[Allocation, ...]:
    return tuple(Allocation(UUID(item["lotId"]), int(item["amount"])) for item in metadata.get("allocations", []))


def valid_reason_text(reason: str) -> str:
    text = reason.strip()
    if not 0 < len(text) <= REASON_TEXT_LIMIT:
        raise InvalidAdjustmentReasonError
    return text


def valid_key(key: str) -> str:
    if not 0 < len(key) <= MAX_KEY_LENGTH:
        raise InvalidIdempotencyKeyError
    return key


class CreditsService:
    def __init__(
        self,
        clock: Clock,
        settings: BillingSettings,
        *,
        store_factory: StoreFactory = SqlCreditsRepository,
        audit: AuditRecorder = record_audit,
    ) -> None:
        self._clock = clock
        self._settings = settings
        self._store_factory = store_factory
        self._audit = audit

    def _store(self, session: AsyncSession) -> CreditsStore:
        return self._store_factory(session)

    async def wallet(self, session: AsyncSession, user_id: UUID) -> WalletView:
        store = self._store(session)
        wallet = await store.wallet(user_id)
        if wallet is None:
            return WalletView(balance=0, reserved=0, available=0, expiring_soon=())
        now = self._clock.now()
        lead = timedelta(days=self._settings.expiry_reminder_lead_days)
        expired = await store.expired_lot_remaining(user_id, now)
        soon = await store.expiring_lots(user_id, now, now + lead)
        return WalletView(
            balance=wallet.balance,
            reserved=wallet.reserved,
            available=max(0, wallet.balance - wallet.reserved - expired),
            expiring_soon=tuple(
                ExpiringLot(source=lot.source, remaining=lot.remaining, expires_at=lot.expires_at)
                for lot in soon
                if lot.expires_at is not None
            ),
        )

    async def grant(self, session: AsyncSession, command: GrantCommand) -> GrantResult:
        if command.amount <= 0:
            raise InvalidCreditAmountError
        if command.ref is not None and command.ref.ref_type not in LOT_REF_TYPES:
            raise InvalidCreditReferenceError
        key = valid_key(command.key)
        store = self._store(session)
        try:
            await store.ensure_wallet(command.user_id)
        except UnknownCreditUserError as error:
            raise CreditUserNotFoundError from error
        wallet = await self._require_wallet(store, command.user_id)
        replay = self._replayed(
            await store.ledger_by_key(key),
            command.user_id,
            Expected(GRANT_REASONS, ref_id=command.ref.ref_id if command.ref else None, delta=command.amount),
        )
        if replay is not None:
            replayed_expiry = replay.metadata.get("expiresAt")
            return GrantResult(
                lot_id=UUID(replay.metadata["lotId"]),
                ledger_id=replay.id,
                amount=replay.delta,
                balance_after=replay.balance_after,
                expires_at=datetime.fromisoformat(replayed_expiry) if replayed_expiry else None,
            )
        now = self._clock.now()
        lot = LotRecord(
            id=new_id(),
            user_id=command.user_id,
            source=command.source,
            amount=command.amount,
            remaining=command.amount,
            expires_at=command.expires_at,
            ref_type=command.ref.ref_type if command.ref else None,
            ref_id=command.ref.ref_id if command.ref else None,
            created_at=now,
        )
        try:
            await store.add_lot(lot)
        except LotReferenceExistsError as error:
            raise DuplicateLotReferenceError from error
        updated, entry = await self._post(
            store,
            wallet,
            now,
            Posting(
                reason=GRANT_REASON_BY_SOURCE[command.source],
                delta=command.amount,
                reserved_delta=0,
                key=key,
                ref=command.ref,
                metadata={
                    "lotId": str(lot.id),
                    "source": command.source,
                    "expiresAt": command.expires_at.isoformat() if command.expires_at else None,
                },
            ),
        )
        return GrantResult(
            lot_id=lot.id,
            ledger_id=entry.id,
            amount=command.amount,
            balance_after=updated.balance,
            expires_at=command.expires_at,
        )

    async def reserve(self, session: AsyncSession, command: ReserveCommand) -> ReservationResult:
        if command.amount <= 0:
            raise InvalidCreditAmountError
        if RESERVATION_REF_TYPE.fullmatch(command.ref_type) is None:
            raise InvalidCreditReferenceError
        ttl = command.ttl if command.ttl is not None else timedelta(seconds=self._settings.reservation_ttl_seconds)
        if ttl <= timedelta(0):
            raise InvalidCreditAmountError(code="invalid_reservation_ttl")
        key = valid_key(command.key)
        store = self._store(session)
        wallet = await store.lock_wallet(command.user_id)
        if wallet is None:
            raise InsufficientCreditsError(available=0, required=command.amount)
        replay = self._replayed(
            await store.ledger_by_key(key),
            command.user_id,
            Expected(
                frozenset({"reserve"}),
                reserved_delta=command.amount,
                metadata={"purposeType": command.ref_type, "purposeId": str(command.ref_id)},
            ),
        )
        if replay is not None:
            return await self._reservation_result(store, replay)
        now = self._clock.now()
        wallet = await self._expire(store, wallet, now)
        if await store.active_reservation_for(command.ref_type, command.ref_id) is not None:
            raise ReservationAlreadyActiveError
        available = wallet.balance - wallet.reserved
        if available < command.amount:
            raise InsufficientCreditsError(available=available, required=command.amount)
        reservation = ReservationRecord(
            id=new_id(),
            user_id=command.user_id,
            amount=command.amount,
            status="active",
            ref_type=command.ref_type,
            ref_id=command.ref_id,
            committed_amount=None,
            idempotency_key=key,
            expires_at=now + ttl,
            settled_at=None,
            created_at=now,
        )
        try:
            await store.add_reservation(reservation)
        except ActiveReservationExistsError as error:
            raise ReservationAlreadyActiveError from error
        updated, _ = await self._post(
            store,
            wallet,
            now,
            Posting(
                reason="reserve",
                delta=0,
                reserved_delta=command.amount,
                key=key,
                ref=CreditRef("reservation", reservation.id),
                metadata={
                    "purposeType": command.ref_type,
                    "purposeId": str(command.ref_id),
                    "expiresAt": reservation.expires_at.isoformat(),
                },
            ),
        )
        return ReservationResult(
            id=reservation.id,
            user_id=command.user_id,
            amount=command.amount,
            expires_at=reservation.expires_at,
            reserved_after=updated.reserved,
        )

    async def commit(self, session: AsyncSession, reservation_id: UUID, actual: int, key: str) -> CommitResult:
        if actual < 0:
            raise InvalidCreditAmountError
        key = valid_key(key)
        store = self._store(session)
        user_id = await store.reservation_owner(reservation_id)
        if user_id is None:
            raise ReservationNotFoundError
        wallet = await self._require_wallet(store, user_id)
        replay = self._replayed(
            await store.ledger_by_key(key),
            user_id,
            Expected(frozenset({"commit"}), ref_id=reservation_id, delta=-actual),
        )
        if replay is not None:
            return CommitResult(
                reservation_id=reservation_id,
                charged=-replay.delta,
                released=-replay.reserved_delta + replay.delta,
                allocations=allocations_of(replay.metadata),
                balance_after=replay.balance_after,
                reserved_after=replay.reserved_after,
            )
        reservation = await self._locked_reservation(store, reservation_id, user_id)
        if reservation.status != "active":
            raise ReservationNotActiveError
        if actual > reservation.amount:
            raise CommitExceedsReservationError
        now = self._clock.now()
        wallet = await self._expire(store, wallet, now)
        lots = await store.lock_open_lots(user_id)
        allocations = allocate(lots, actual)
        await self._consume(store, lots, allocations)
        await store.save_reservation(replace(reservation, status="committed", committed_amount=actual, settled_at=now))
        updated, _ = await self._post(
            store,
            wallet,
            now,
            Posting(
                reason="commit",
                delta=-actual,
                reserved_delta=-reservation.amount,
                key=key,
                ref=CreditRef("reservation", reservation_id),
                metadata={"allocations": allocations_metadata(allocations), "reservedAmount": reservation.amount},
            ),
        )
        return CommitResult(
            reservation_id=reservation_id,
            charged=actual,
            released=reservation.amount - actual,
            allocations=allocations,
            balance_after=updated.balance,
            reserved_after=updated.reserved,
        )

    async def release(self, session: AsyncSession, reservation_id: UUID, key: str) -> ReleaseResult:
        result = await self._release(session, reservation_id, valid_key(key), MANUAL_RELEASE)
        if result is None:
            raise ReservationNotActiveError
        return result

    async def release_stale(self, session: AsyncSession, reservation_id: UUID) -> ReleaseResult | None:
        return await self._release(session, reservation_id, f"reservation:{reservation_id}:ttl", TTL_RELEASE)

    async def clawback(self, session: AsyncSession, command: ClawbackCommand) -> ClawbackResult:
        if command.amount <= 0:
            raise InvalidCreditAmountError
        if command.ref.ref_type != REFUND_REF_TYPE:
            raise InvalidCreditReferenceError
        reason = valid_reason_text(command.reason)
        key = valid_key(command.key)
        store = self._store(session)
        user_id = await store.lot_owner(command.lot_id)
        if user_id is None:
            raise LotNotFoundError
        wallet = await self._require_wallet(store, user_id)
        replay = self._replayed(
            await store.ledger_by_key(key),
            user_id,
            Expected(frozenset({"refund_clawback"}), ref_id=command.ref.ref_id),
        )
        if replay is not None:
            return ClawbackResult(
                lot_id=command.lot_id,
                requested=int(replay.metadata.get("requested", command.amount)),
                clawed_back=-replay.delta,
                balance_after=replay.balance_after,
            )
        now = self._clock.now()
        wallet = await self._expire(store, wallet, now)
        lot = await store.lock_lot(command.lot_id)
        if lot is None or lot.user_id != user_id:
            raise LotNotFoundError
        taken = min(command.amount, lot.remaining, wallet.balance - wallet.reserved)
        if taken <= 0:
            return ClawbackResult(
                lot_id=command.lot_id, requested=command.amount, clawed_back=0, balance_after=wallet.balance
            )
        await store.save_lot(replace(lot, remaining=lot.remaining - taken))
        updated, _ = await self._post(
            store,
            wallet,
            now,
            Posting(
                reason="refund_clawback",
                delta=-taken,
                reserved_delta=0,
                key=key,
                ref=command.ref,
                metadata={"lotId": str(lot.id), "requested": command.amount, "reason": reason},
            ),
        )
        return ClawbackResult(
            lot_id=command.lot_id, requested=command.amount, clawed_back=taken, balance_after=updated.balance
        )

    async def adjust(self, session: AsyncSession, command: AdjustCommand) -> AdjustResult:
        if command.delta == 0:
            raise InvalidCreditAmountError
        reason = valid_reason_text(command.reason)
        key = valid_key(command.key)
        store = self._store(session)
        if command.delta > 0:
            try:
                await store.ensure_wallet(command.user_id)
            except UnknownCreditUserError as error:
                raise CreditUserNotFoundError from error
        wallet = await store.lock_wallet(command.user_id)
        if wallet is None:
            raise AdjustmentExceedsAvailableError
        replay = self._replayed(
            await store.ledger_by_key(key),
            command.user_id,
            Expected(frozenset({"admin_adjust"}), delta=command.delta),
        )
        if replay is not None:
            replayed_lot = replay.metadata.get("lotId")
            return AdjustResult(
                user_id=command.user_id,
                delta=replay.delta,
                action_id=replay.ref_id or new_id(),
                lot_id=UUID(replayed_lot) if replayed_lot else None,
                allocations=allocations_of(replay.metadata),
                balance_after=replay.balance_after,
            )
        now = self._clock.now()
        if command.expires_at is not None and (command.delta < 0 or command.expires_at <= now):
            raise InvalidCreditExpiryError
        wallet = await self._expire(store, wallet, now)
        action_id = new_id()
        lot_id: UUID | None = None
        allocations: tuple[Allocation, ...] = ()
        metadata: JsonObject = {"actorId": str(command.actor_id), "reason": reason, "actionId": str(action_id)}
        if command.delta > 0:
            lot = LotRecord(
                id=new_id(),
                user_id=command.user_id,
                source="admin",
                amount=command.delta,
                remaining=command.delta,
                expires_at=command.expires_at,
                ref_type="admin",
                ref_id=action_id,
                created_at=now,
            )
            try:
                await store.add_lot(lot)
            except LotReferenceExistsError as error:
                raise DuplicateLotReferenceError from error
            lot_id = lot.id
            metadata["lotId"] = str(lot.id)
        else:
            available = wallet.balance - wallet.reserved
            if -command.delta > available:
                raise AdjustmentExceedsAvailableError
            lots = await store.lock_open_lots(command.user_id)
            allocations = allocate(lots, -command.delta)
            await self._consume(store, lots, allocations)
            metadata["allocations"] = allocations_metadata(allocations)
        updated, _ = await self._post(
            store,
            wallet,
            now,
            Posting(
                reason="admin_adjust",
                delta=command.delta,
                reserved_delta=0,
                key=key,
                ref=CreditRef("admin", action_id),
                metadata=metadata,
            ),
        )
        await self._audit(
            session,
            AuditEvent(
                action="credits.adjusted",
                actor_type=ActorType.ADMIN,
                actor_user_id=command.actor_id,
                target_type="user",
                target_id=str(command.user_id),
                metadata={"delta": command.delta, "reason": reason, "actionId": str(action_id), "ledgerKey": key},
            ),
        )
        return AdjustResult(
            user_id=command.user_id,
            delta=command.delta,
            action_id=action_id,
            lot_id=lot_id,
            allocations=allocations,
            balance_after=updated.balance,
        )

    async def expire_due_lots(self, session: AsyncSession, user_id: UUID) -> ExpiryResult:
        store = self._store(session)
        wallet = await store.lock_wallet(user_id)
        if wallet is None:
            return ExpiryResult(user_id=user_id, expired=0)
        updated = await self._expire(store, wallet, self._clock.now())
        return ExpiryResult(user_id=user_id, expired=wallet.balance - updated.balance)

    async def users_due_for_expiry(self, session: AsyncSession, after: UUID | None, limit: int) -> list[UUID]:
        return await self._store(session).users_with_expirable_lots(self._clock.now(), after, limit)

    async def stale_reservation_ids(self, session: AsyncSession, after: UUID | None, limit: int) -> list[UUID]:
        rows = await self._store(session).stale_reservations(self._clock.now(), after, limit)
        return [row.id for row in rows]

    async def claim_expiry_reminders(self, session: AsyncSession, limit: int) -> list[ReminderBatch]:
        now = self._clock.now()
        before = now + timedelta(days=self._settings.expiry_reminder_lead_days)
        lots = await self._store(session).claim_expiry_reminders(now, before, limit)
        batches: dict[UUID, ReminderBatch] = {}
        for lot in lots:
            if lot.expires_at is None:
                continue
            current = batches.get(lot.user_id)
            batches[lot.user_id] = ReminderBatch(
                user_id=lot.user_id,
                credits=(current.credits if current else 0) + lot.remaining,
                expires_at=min(current.expires_at, lot.expires_at) if current else lot.expires_at,
            )
        return sorted(batches.values(), key=lambda batch: str(batch.user_id))

    async def check_integrity(self, session: AsyncSession) -> list[IntegrityViolation]:
        audits = await self._store(session).wallet_audits()
        return [
            IntegrityViolation(user_id=item.user_id, problems=item.problems()) for item in audits if item.problems()
        ]

    async def ledger(
        self, session: AsyncSession, user_id: UUID, cursor: Cursor | None, limit: int
    ) -> Page[LedgerRecord]:
        return page_of(await self._store(session).ledger_page(user_id, cursor, limit), limit)

    async def usage(self, session: AsyncSession, user_id: UUID, cursor: Cursor | None, limit: int) -> Page[UsageRow]:
        return page_of(await self._store(session).usage_page(user_id, cursor, limit), limit)

    async def daily_usage(
        self, session: AsyncSession, user_id: UUID, start: date | None, end: date | None
    ) -> list[DailyUsage]:
        last = end or self._clock.now().date()
        first = start or last - timedelta(days=DEFAULT_USAGE_WINDOW_DAYS - 1)
        if first > last or (last - first).days + 1 > MAX_USAGE_RANGE_DAYS:
            raise InvalidUsageRangeError
        return await self._store(session).usage_daily(user_id, first, last)

    async def _require_wallet(self, store: CreditsStore, user_id: UUID) -> WalletRecord:
        wallet = await store.lock_wallet(user_id)
        if wallet is None:
            raise_alert("credit_wallet_missing", user_id=str(user_id))
            raise CreditInvariantError
        return wallet

    async def _locked_reservation(self, store: CreditsStore, reservation_id: UUID, user_id: UUID) -> ReservationRecord:
        reservation = await store.lock_reservation(reservation_id)
        if reservation is None or reservation.user_id != user_id:
            raise ReservationNotFoundError
        return reservation

    def _replayed(self, row: LedgerRecord | None, user_id: UUID, expected: Expected) -> LedgerRecord | None:
        if row is None:
            return None
        mismatched = (
            row.user_id != user_id
            or row.reason not in expected.reasons
            or (expected.ref_id is not None and row.ref_id != expected.ref_id)
            or (expected.delta is not None and row.delta != expected.delta)
            or (expected.reserved_delta is not None and row.reserved_delta != expected.reserved_delta)
            or any(row.metadata.get(name) != value for name, value in expected.metadata.items())
        )
        if mismatched:
            raise IdempotencyKeyConflictError
        return row

    async def _reservation_result(self, store: CreditsStore, replay: LedgerRecord) -> ReservationResult:
        reservation = await store.reservation(replay.ref_id) if replay.ref_id is not None else None
        if reservation is None:
            raise CreditInvariantError
        return ReservationResult(
            id=reservation.id,
            user_id=reservation.user_id,
            amount=reservation.amount,
            expires_at=reservation.expires_at,
            reserved_after=replay.reserved_after,
        )

    async def _release(
        self, session: AsyncSession, reservation_id: UUID, key: str, mode: Settlement
    ) -> ReleaseResult | None:
        store = self._store(session)
        user_id = await store.reservation_owner(reservation_id)
        if user_id is None:
            if mode.stale_only:
                return None
            raise ReservationNotFoundError
        wallet = await self._require_wallet(store, user_id)
        replay = self._replayed(
            await store.ledger_by_key(key), user_id, Expected(frozenset({"release"}), ref_id=reservation_id)
        )
        if replay is not None:
            return ReleaseResult(
                reservation_id=reservation_id, released=-replay.reserved_delta, reserved_after=replay.reserved_after
            )
        reservation = await self._locked_reservation(store, reservation_id, user_id)
        now = self._clock.now()
        if reservation.status != "active":
            if mode.stale_only:
                return None
            raise ReservationNotActiveError
        if mode.stale_only and reservation.expires_at > now:
            return None
        await store.save_reservation(replace(reservation, status=mode.final_status, settled_at=now))
        updated, _ = await self._post(
            store,
            wallet,
            now,
            Posting(
                reason="release",
                delta=0,
                reserved_delta=-reservation.amount,
                key=key,
                ref=CreditRef("reservation", reservation_id),
                metadata={"cause": mode.cause},
            ),
        )
        return ReleaseResult(
            reservation_id=reservation_id, released=reservation.amount, reserved_after=updated.reserved
        )

    async def _expire(self, store: CreditsStore, wallet: WalletRecord, now: datetime) -> WalletRecord:
        capacity = wallet.balance - wallet.reserved
        if capacity <= 0:
            return wallet
        for lot in await store.lock_expired_lots(wallet.user_id, now):
            if capacity <= 0:
                break
            taken = min(lot.remaining, capacity)
            remaining = lot.remaining - taken
            await store.save_lot(replace(lot, remaining=remaining, expired_at=now if remaining == 0 else None))
            wallet, _ = await self._post(
                store,
                wallet,
                now,
                Posting(
                    reason="expiry",
                    delta=-taken,
                    reserved_delta=0,
                    key=f"expiry:{lot.id}:{wallet.version}",
                    ref=CreditRef("lot", lot.id),
                    metadata={
                        "lotId": str(lot.id),
                        "expiredAt": lot.expires_at.isoformat() if lot.expires_at else None,
                    },
                ),
            )
            capacity -= taken
        return wallet

    async def _consume(self, store: CreditsStore, lots: Sequence[LotRecord], allocations: Sequence[Allocation]) -> None:
        by_id = {lot.id: lot for lot in lots}
        for allocation in allocations:
            lot = by_id[allocation.lot_id]
            await store.save_lot(replace(lot, remaining=lot.remaining - allocation.amount))

    async def _post(
        self, store: CreditsStore, wallet: WalletRecord, now: datetime, posting: Posting
    ) -> tuple[WalletRecord, LedgerRecord]:
        reason = posting.reason
        delta = posting.delta
        reserved_delta = posting.reserved_delta
        ref = posting.ref
        updated = replace(
            wallet,
            balance=wallet.balance + delta,
            reserved=wallet.reserved + reserved_delta,
            version=wallet.version + 1,
        )
        if updated.reserved < 0 or updated.reserved > updated.balance:
            raise_alert(
                "credit_invariant_violation",
                user_id=str(wallet.user_id),
                operation=reason,
                balance=updated.balance,
                reserved=updated.reserved,
            )
            raise CreditInvariantError
        entry = LedgerRecord(
            id=new_id(),
            user_id=wallet.user_id,
            delta=delta,
            reserved_delta=reserved_delta,
            balance_after=updated.balance,
            reserved_after=updated.reserved,
            reason=reason,
            ref_type=ref.ref_type if ref else None,
            ref_id=ref.ref_id if ref else None,
            idempotency_key=posting.key,
            metadata=posting.metadata,
            created_at=now,
        )
        await store.save_wallet(updated)
        await store.add_ledger(entry)
        return updated, entry


async def record_usage(
    session: AsyncSession, entry: UsageEntry, *, store_factory: StoreFactory = SqlCreditsRepository
) -> UUID:
    try:
        return await store_factory(session).insert_usage(entry)
    except UnknownCreditUserError as error:
        raise CreditUserNotFoundError from error
