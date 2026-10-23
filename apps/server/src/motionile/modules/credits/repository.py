from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from uuid import UUID

from sqlalchemy import Date, cast, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor, keyset_page
from motionile.modules.credits.domain import (
    BalanceTotals,
    DailyUsage,
    LedgerDayTotal,
    LedgerRecord,
    LotRecord,
    ReservationRecord,
    UsageEntry,
    UsageRow,
    WalletAudit,
    WalletRecord,
)
from motionile.modules.credits.exceptions import (
    ActiveReservationExistsError,
    LotReferenceExistsError,
    UnknownCreditUserError,
)
from motionile.modules.credits.models import (
    CreditLedgerEntry,
    CreditLot,
    CreditReservation,
    CreditWallet,
    UsageRecord,
)

CONSUMPTION_ORDER = (CreditLot.expires_at.asc().nulls_last(), CreditLot.created_at.asc(), CreditLot.id.asc())
FRESH_ROWS = {"populate_existing": True}
WALLET_USER_FOREIGN_KEY = "fk_credit_wallets_user_id_users"
USAGE_USER_FOREIGN_KEY = "fk_usage_records_user_id_users"
ACTIVE_REFERENCE_INDEX = "uq_credit_reservations_active_ref"
LOT_REFERENCE_INDEX = "uq_credit_lots_source_ref"

WALLET_AUDITS = text(
    """
    WITH ledger AS (
        SELECT user_id, SUM(delta) AS delta_sum, SUM(reserved_delta) AS reserved_sum
        FROM credit_ledger GROUP BY user_id
    ), latest AS (
        SELECT DISTINCT ON (user_id) user_id, balance_after, reserved_after
        FROM credit_ledger ORDER BY user_id, created_at DESC, id DESC
    ), lots AS (
        SELECT user_id, SUM(remaining) AS remaining_sum, COUNT(*) FILTER (WHERE remaining < 0) AS negative_lots
        FROM credit_lots GROUP BY user_id
    ), holds AS (
        SELECT user_id, SUM(amount) AS active_sum
        FROM credit_reservations WHERE status = 'active' GROUP BY user_id
    ), audited AS (
        SELECT
            w.user_id,
            w.balance,
            w.reserved,
            COALESCE(ledger.delta_sum, 0) AS ledger_delta_sum,
            COALESCE(ledger.reserved_sum, 0) AS ledger_reserved_sum,
            COALESCE(lots.remaining_sum, 0) AS lot_remaining_sum,
            COALESCE(holds.active_sum, 0) AS active_reservation_sum,
            COALESCE(latest.balance_after, 0) AS latest_balance_after,
            COALESCE(latest.reserved_after, 0) AS latest_reserved_after,
            COALESCE(lots.negative_lots, 0) AS negative_lots
        FROM credit_wallets w
        LEFT JOIN ledger ON ledger.user_id = w.user_id
        LEFT JOIN latest ON latest.user_id = w.user_id
        LEFT JOIN lots ON lots.user_id = w.user_id
        LEFT JOIN holds ON holds.user_id = w.user_id
    )
    SELECT * FROM audited
    WHERE balance <> ledger_delta_sum
        OR balance <> lot_remaining_sum
        OR reserved <> ledger_reserved_sum
        OR reserved <> active_reservation_sum
        OR balance <> latest_balance_after
        OR reserved <> latest_reserved_after
        OR balance < 0
        OR reserved < 0
        OR reserved > balance
        OR negative_lots > 0
    ORDER BY user_id
    """
)


class CreditsStore(Protocol):
    async def ensure_wallet(self, user_id: UUID) -> None: ...
    async def wallet(self, user_id: UUID) -> WalletRecord | None: ...
    async def lock_wallet(self, user_id: UUID) -> WalletRecord | None: ...
    async def save_wallet(self, wallet: WalletRecord) -> None: ...
    async def ledger_by_key(self, key: str) -> LedgerRecord | None: ...
    async def add_ledger(self, entry: LedgerRecord) -> None: ...
    async def lot_owner(self, lot_id: UUID) -> UUID | None: ...
    async def lot_by_reference(self, ref_type: str, ref_id: UUID) -> LotRecord | None: ...
    async def lock_lot(self, lot_id: UUID) -> LotRecord | None: ...
    async def lock_open_lots(self, user_id: UUID) -> list[LotRecord]: ...
    async def lock_expired_lots(self, user_id: UUID, now: datetime) -> list[LotRecord]: ...
    async def add_lot(self, lot: LotRecord) -> None: ...
    async def save_lot(self, lot: LotRecord) -> None: ...
    async def reservation_owner(self, reservation_id: UUID) -> UUID | None: ...
    async def reservation(self, reservation_id: UUID) -> ReservationRecord | None: ...
    async def lock_reservation(self, reservation_id: UUID) -> ReservationRecord | None: ...
    async def active_reservation_for(self, ref_type: str, ref_id: UUID) -> ReservationRecord | None: ...
    async def active_reservation_of(self, user_id: UUID, ref_type: str, ref_id: UUID) -> ReservationRecord | None: ...
    async def add_reservation(self, reservation: ReservationRecord) -> None: ...
    async def save_reservation(self, reservation: ReservationRecord) -> None: ...
    async def expired_lot_remaining(self, user_id: UUID, now: datetime) -> int: ...
    async def expiring_lots(self, user_id: UUID, after: datetime, before: datetime) -> list[LotRecord]: ...
    async def users_with_expirable_lots(self, now: datetime, after: UUID | None, limit: int) -> list[UUID]: ...
    async def stale_reservations(self, now: datetime, after: UUID | None, limit: int) -> list[ReservationRecord]: ...
    async def claim_expiry_reminders(self, now: datetime, before: datetime, limit: int) -> list[LotRecord]: ...
    async def ledger_page(self, user_id: UUID, cursor: Cursor | None, limit: int) -> list[LedgerRecord]: ...
    async def lot_page(self, user_id: UUID, cursor: Cursor | None, limit: int) -> list[LotRecord]: ...
    async def ledger_daily_totals(self, start: date, end: date) -> list[LedgerDayTotal]: ...
    async def balance_totals(self) -> BalanceTotals: ...
    async def usage_page(self, user_id: UUID, cursor: Cursor | None, limit: int) -> list[UsageRow]: ...
    async def usage_daily(self, user_id: UUID, start: date, end: date) -> list[DailyUsage]: ...
    async def insert_usage(self, entry: UsageEntry) -> UUID: ...
    async def wallet_audits(self) -> list[WalletAudit]: ...


def wallet_record(model: CreditWallet) -> WalletRecord:
    return WalletRecord(user_id=model.user_id, balance=model.balance, reserved=model.reserved, version=model.version)


def lot_record(model: CreditLot) -> LotRecord:
    return LotRecord(
        id=model.id,
        user_id=model.user_id,
        source=model.source,
        amount=model.amount,
        remaining=model.remaining,
        expires_at=model.expires_at,
        ref_type=model.ref_type,
        ref_id=model.ref_id,
        created_at=model.created_at,
        expiry_reminder_sent_at=model.expiry_reminder_sent_at,
        expired_at=model.expired_at,
    )


def reservation_record(model: CreditReservation) -> ReservationRecord:
    return ReservationRecord(
        id=model.id,
        user_id=model.user_id,
        amount=model.amount,
        status=model.status,
        ref_type=model.ref_type,
        ref_id=model.ref_id,
        committed_amount=model.committed_amount,
        idempotency_key=model.idempotency_key,
        expires_at=model.expires_at,
        settled_at=model.settled_at,
        created_at=model.created_at,
    )


def ledger_record(model: CreditLedgerEntry) -> LedgerRecord:
    return LedgerRecord(
        id=model.id,
        user_id=model.user_id,
        delta=model.delta,
        reserved_delta=model.reserved_delta,
        balance_after=model.balance_after,
        reserved_after=model.reserved_after,
        reason=model.reason,
        ref_type=model.ref_type,
        ref_id=model.ref_id,
        idempotency_key=model.idempotency_key,
        metadata=dict(model.metadata_),
        created_at=model.created_at,
    )


def violates(error: IntegrityError, name: str) -> bool:
    return name in str(error.orig)


class SqlCreditsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def ensure_wallet(self, user_id: UUID) -> None:
        statement = (
            pg_insert(CreditWallet)
            .values(user_id=user_id)
            .on_conflict_do_nothing(index_elements=[CreditWallet.user_id])
        )
        try:
            async with self.session.begin_nested():
                await self.session.execute(statement)
        except IntegrityError as error:
            if violates(error, WALLET_USER_FOREIGN_KEY):
                raise UnknownCreditUserError(user_id) from error
            raise

    async def wallet(self, user_id: UUID) -> WalletRecord | None:
        model = await self.session.scalar(
            select(CreditWallet).where(CreditWallet.user_id == user_id).execution_options(**FRESH_ROWS)
        )
        return wallet_record(model) if model is not None else None

    async def lock_wallet(self, user_id: UUID) -> WalletRecord | None:
        model = await self.session.scalar(
            select(CreditWallet)
            .where(CreditWallet.user_id == user_id)
            .with_for_update()
            .execution_options(**FRESH_ROWS)
        )
        return wallet_record(model) if model is not None else None

    async def save_wallet(self, wallet: WalletRecord) -> None:
        await self.session.execute(
            update(CreditWallet)
            .where(CreditWallet.user_id == wallet.user_id)
            .values(balance=wallet.balance, reserved=wallet.reserved, version=wallet.version)
            .execution_options(synchronize_session=False)
        )

    async def ledger_by_key(self, key: str) -> LedgerRecord | None:
        model = await self.session.scalar(
            select(CreditLedgerEntry).where(CreditLedgerEntry.idempotency_key == key).execution_options(**FRESH_ROWS)
        )
        return ledger_record(model) if model is not None else None

    async def add_ledger(self, entry: LedgerRecord) -> None:
        await self.session.execute(
            pg_insert(CreditLedgerEntry).values(
                id=entry.id,
                user_id=entry.user_id,
                delta=entry.delta,
                reserved_delta=entry.reserved_delta,
                balance_after=entry.balance_after,
                reserved_after=entry.reserved_after,
                reason=entry.reason,
                ref_type=entry.ref_type,
                ref_id=entry.ref_id,
                idempotency_key=entry.idempotency_key,
                metadata=entry.metadata,
                created_at=entry.created_at,
            )
        )

    async def lot_owner(self, lot_id: UUID) -> UUID | None:
        return await self.session.scalar(select(CreditLot.user_id).where(CreditLot.id == lot_id))

    async def lot_by_reference(self, ref_type: str, ref_id: UUID) -> LotRecord | None:
        model = await self.session.scalar(
            select(CreditLot)
            .where(CreditLot.ref_type == ref_type, CreditLot.ref_id == ref_id)
            .order_by(CreditLot.created_at, CreditLot.id)
            .limit(1)
            .execution_options(**FRESH_ROWS)
        )
        return lot_record(model) if model is not None else None

    async def lock_lot(self, lot_id: UUID) -> LotRecord | None:
        model = await self.session.scalar(
            select(CreditLot).where(CreditLot.id == lot_id).with_for_update().execution_options(**FRESH_ROWS)
        )
        return lot_record(model) if model is not None else None

    async def lock_open_lots(self, user_id: UUID) -> list[LotRecord]:
        models = await self.session.scalars(
            select(CreditLot)
            .where(CreditLot.user_id == user_id, CreditLot.remaining > 0)
            .order_by(*CONSUMPTION_ORDER)
            .with_for_update()
            .execution_options(**FRESH_ROWS)
        )
        return [lot_record(model) for model in models]

    async def lock_expired_lots(self, user_id: UUID, now: datetime) -> list[LotRecord]:
        models = await self.session.scalars(
            select(CreditLot)
            .where(CreditLot.user_id == user_id, CreditLot.remaining > 0, CreditLot.expires_at <= now)
            .order_by(*CONSUMPTION_ORDER)
            .with_for_update()
            .execution_options(**FRESH_ROWS)
        )
        return [lot_record(model) for model in models]

    async def add_lot(self, lot: LotRecord) -> None:
        statement = pg_insert(CreditLot).values(
            id=lot.id,
            user_id=lot.user_id,
            source=lot.source,
            amount=lot.amount,
            remaining=lot.remaining,
            expires_at=lot.expires_at,
            ref_type=lot.ref_type,
            ref_id=lot.ref_id,
            created_at=lot.created_at,
        )
        try:
            async with self.session.begin_nested():
                await self.session.execute(statement)
        except IntegrityError as error:
            if violates(error, LOT_REFERENCE_INDEX):
                raise LotReferenceExistsError from error
            raise

    async def save_lot(self, lot: LotRecord) -> None:
        await self.session.execute(
            update(CreditLot)
            .where(CreditLot.id == lot.id)
            .values(remaining=lot.remaining, expired_at=lot.expired_at)
            .execution_options(synchronize_session=False)
        )

    async def reservation_owner(self, reservation_id: UUID) -> UUID | None:
        return await self.session.scalar(
            select(CreditReservation.user_id).where(CreditReservation.id == reservation_id)
        )

    async def reservation(self, reservation_id: UUID) -> ReservationRecord | None:
        model = await self.session.scalar(
            select(CreditReservation).where(CreditReservation.id == reservation_id).execution_options(**FRESH_ROWS)
        )
        return reservation_record(model) if model is not None else None

    async def lock_reservation(self, reservation_id: UUID) -> ReservationRecord | None:
        model = await self.session.scalar(
            select(CreditReservation)
            .where(CreditReservation.id == reservation_id)
            .with_for_update()
            .execution_options(**FRESH_ROWS)
        )
        return reservation_record(model) if model is not None else None

    async def active_reservation_for(self, ref_type: str, ref_id: UUID) -> ReservationRecord | None:
        model = await self.session.scalar(
            select(CreditReservation)
            .where(
                CreditReservation.ref_type == ref_type,
                CreditReservation.ref_id == ref_id,
                CreditReservation.status == "active",
            )
            .execution_options(**FRESH_ROWS)
        )
        return reservation_record(model) if model is not None else None

    async def active_reservation_of(self, user_id: UUID, ref_type: str, ref_id: UUID) -> ReservationRecord | None:
        model = await self.session.scalar(
            select(CreditReservation)
            .where(
                CreditReservation.user_id == user_id,
                CreditReservation.ref_type == ref_type,
                CreditReservation.ref_id == ref_id,
                CreditReservation.status == "active",
            )
            .execution_options(**FRESH_ROWS)
        )
        return reservation_record(model) if model is not None else None

    async def add_reservation(self, reservation: ReservationRecord) -> None:
        statement = pg_insert(CreditReservation).values(
            id=reservation.id,
            user_id=reservation.user_id,
            amount=reservation.amount,
            status=reservation.status,
            ref_type=reservation.ref_type,
            ref_id=reservation.ref_id,
            idempotency_key=reservation.idempotency_key,
            expires_at=reservation.expires_at,
            created_at=reservation.created_at,
        )
        try:
            async with self.session.begin_nested():
                await self.session.execute(statement)
        except IntegrityError as error:
            if violates(error, ACTIVE_REFERENCE_INDEX):
                raise ActiveReservationExistsError from error
            raise

    async def save_reservation(self, reservation: ReservationRecord) -> None:
        await self.session.execute(
            update(CreditReservation)
            .where(CreditReservation.id == reservation.id)
            .values(
                status=reservation.status,
                committed_amount=reservation.committed_amount,
                settled_at=reservation.settled_at,
            )
            .execution_options(synchronize_session=False)
        )

    async def expired_lot_remaining(self, user_id: UUID, now: datetime) -> int:
        total = await self.session.scalar(
            select(func.coalesce(func.sum(CreditLot.remaining), 0)).where(
                CreditLot.user_id == user_id, CreditLot.remaining > 0, CreditLot.expires_at <= now
            )
        )
        return int(total or 0)

    async def expiring_lots(self, user_id: UUID, after: datetime, before: datetime) -> list[LotRecord]:
        models = await self.session.scalars(
            select(CreditLot)
            .where(
                CreditLot.user_id == user_id,
                CreditLot.remaining > 0,
                CreditLot.expires_at > after,
                CreditLot.expires_at <= before,
            )
            .order_by(*CONSUMPTION_ORDER)
            .execution_options(**FRESH_ROWS)
        )
        return [lot_record(model) for model in models]

    async def users_with_expirable_lots(self, now: datetime, after: UUID | None, limit: int) -> list[UUID]:
        statement = (
            select(CreditLot.user_id)
            .join(CreditWallet, CreditWallet.user_id == CreditLot.user_id)
            .where(CreditLot.remaining > 0, CreditLot.expires_at <= now, CreditWallet.balance > CreditWallet.reserved)
            .distinct()
            .order_by(CreditLot.user_id)
            .limit(limit)
        )
        if after is not None:
            statement = statement.where(CreditLot.user_id > after)
        return list(await self.session.scalars(statement))

    async def stale_reservations(self, now: datetime, after: UUID | None, limit: int) -> list[ReservationRecord]:
        statement = (
            select(CreditReservation)
            .where(CreditReservation.status == "active", CreditReservation.expires_at <= now)
            .order_by(CreditReservation.id)
            .limit(limit)
            .execution_options(**FRESH_ROWS)
        )
        if after is not None:
            statement = statement.where(CreditReservation.id > after)
        return [reservation_record(model) for model in await self.session.scalars(statement)]

    async def claim_expiry_reminders(self, now: datetime, before: datetime, limit: int) -> list[LotRecord]:
        candidates = (
            select(CreditLot.id)
            .where(
                CreditLot.remaining > 0,
                CreditLot.expires_at > now,
                CreditLot.expires_at <= before,
                CreditLot.expiry_reminder_sent_at.is_(None),
            )
            .order_by(CreditLot.expires_at, CreditLot.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self.session.scalars(
            update(CreditLot)
            .where(CreditLot.id.in_(candidates.scalar_subquery()))
            .values(expiry_reminder_sent_at=now)
            .returning(CreditLot)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        return [lot_record(model) for model in result]

    async def ledger_page(self, user_id: UUID, cursor: Cursor | None, limit: int) -> list[LedgerRecord]:
        statement = keyset_page(
            select(CreditLedgerEntry).where(CreditLedgerEntry.user_id == user_id),
            created_at=CreditLedgerEntry.created_at,
            id_=CreditLedgerEntry.id,
            cursor=cursor,
            limit=limit,
        ).execution_options(**FRESH_ROWS)
        return [ledger_record(model) for model in await self.session.scalars(statement)]

    async def lot_page(self, user_id: UUID, cursor: Cursor | None, limit: int) -> list[LotRecord]:
        statement = keyset_page(
            select(CreditLot).where(CreditLot.user_id == user_id),
            created_at=CreditLot.created_at,
            id_=CreditLot.id,
            cursor=cursor,
            limit=limit,
        ).execution_options(**FRESH_ROWS)
        return [lot_record(model) for model in await self.session.scalars(statement)]

    async def ledger_daily_totals(self, start: date, end: date) -> list[LedgerDayTotal]:
        day = cast(func.timezone("UTC", CreditLedgerEntry.created_at), Date)
        lower = datetime.combine(start, time.min).replace(tzinfo=UTC)
        upper = datetime.combine(end + timedelta(days=1), time.min).replace(tzinfo=UTC)
        granted = func.coalesce(func.sum(CreditLedgerEntry.delta).filter(CreditLedgerEntry.delta > 0), 0)
        removed = func.coalesce(-func.sum(CreditLedgerEntry.delta).filter(CreditLedgerEntry.delta < 0), 0)
        rows = await self.session.execute(
            select(day.label("day"), CreditLedgerEntry.reason, granted, removed)
            .where(
                CreditLedgerEntry.created_at >= lower,
                CreditLedgerEntry.created_at < upper,
                CreditLedgerEntry.delta != 0,
            )
            .group_by(day, CreditLedgerEntry.reason)
            .order_by(day, CreditLedgerEntry.reason)
        )
        return [LedgerDayTotal(day=row[0], reason=row[1], granted=int(row[2]), removed=int(row[3])) for row in rows]

    async def balance_totals(self) -> BalanceTotals:
        row = (
            await self.session.execute(
                select(
                    func.count(),
                    func.coalesce(func.sum(CreditWallet.balance), 0),
                    func.coalesce(func.sum(CreditWallet.reserved), 0),
                )
            )
        ).one()
        return BalanceTotals(wallets=int(row[0]), balance=int(row[1]), reserved=int(row[2]))

    async def usage_page(self, user_id: UUID, cursor: Cursor | None, limit: int) -> list[UsageRow]:
        statement = keyset_page(
            select(UsageRecord).where(UsageRecord.user_id == user_id),
            created_at=UsageRecord.created_at,
            id_=UsageRecord.id,
            cursor=cursor,
            limit=limit,
        ).execution_options(**FRESH_ROWS)
        return [
            UsageRow(
                id=model.id,
                stage=model.stage,
                credits=model.credits,
                job_id=model.job_id,
                publication_id=model.publication_id,
                created_at=model.created_at,
            )
            for model in await self.session.scalars(statement)
        ]

    async def usage_daily(self, user_id: UUID, start: date, end: date) -> list[DailyUsage]:
        day = cast(func.timezone("UTC", UsageRecord.created_at), Date)
        lower = datetime.combine(start, time.min).replace(tzinfo=UTC)
        upper = datetime.combine(end + timedelta(days=1), time.min).replace(tzinfo=UTC)
        rows = await self.session.execute(
            select(day.label("day"), func.coalesce(func.sum(UsageRecord.credits), 0), func.count())
            .where(UsageRecord.user_id == user_id, UsageRecord.created_at >= lower, UsageRecord.created_at < upper)
            .group_by(day)
            .order_by(day)
        )
        return [DailyUsage(date=row[0], credits=int(row[1]), records=int(row[2])) for row in rows]

    async def insert_usage(self, entry: UsageEntry) -> UUID:
        statement = (
            pg_insert(UsageRecord)
            .values(
                id=new_id(),
                user_id=entry.user_id,
                job_id=entry.job_id,
                publication_id=entry.publication_id,
                stage=entry.stage,
                provider=entry.provider,
                model=entry.model,
                input_tokens=entry.input_tokens,
                output_tokens=entry.output_tokens,
                audio_characters=entry.audio_characters,
                render_ms=entry.render_ms,
                cost_micros_usd=entry.cost_micros_usd,
                credits=entry.credits,
                idempotency_key=entry.key,
            )
            .on_conflict_do_nothing(index_elements=[UsageRecord.idempotency_key])
            .returning(UsageRecord.id)
        )
        try:
            async with self.session.begin_nested():
                inserted = await self.session.scalar(statement)
        except IntegrityError as error:
            if violates(error, USAGE_USER_FOREIGN_KEY):
                raise UnknownCreditUserError(entry.user_id) from error
            raise
        if inserted is not None:
            return inserted
        existing = await self.session.scalars(select(UsageRecord.id).where(UsageRecord.idempotency_key == entry.key))
        return existing.one()

    async def wallet_audits(self) -> list[WalletAudit]:
        rows = await self.session.execute(WALLET_AUDITS)
        return [
            WalletAudit(
                user_id=row.user_id,
                balance=int(row.balance),
                reserved=int(row.reserved),
                ledger_delta_sum=int(row.ledger_delta_sum),
                ledger_reserved_sum=int(row.ledger_reserved_sum),
                lot_remaining_sum=int(row.lot_remaining_sum),
                active_reservation_sum=int(row.active_reservation_sum),
                latest_balance_after=int(row.latest_balance_after),
                latest_reserved_after=int(row.latest_reserved_after),
                negative_lots=int(row.negative_lots),
            )
            for row in rows
        ]
