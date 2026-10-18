import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.pagination import Cursor, CursorCodec
from motionile.modules.billing.admin_activity_repository import BillingActivityStore, SqlBillingActivityRepository
from motionile.modules.billing.admin_records import RecordPage
from motionile.modules.billing.exceptions import AdminUserNotFoundError
from motionile.modules.billing.ports import Transaction
from motionile.modules.billing.services.admin_paging import decode_cursor
from motionile.modules.credits import AdjustCommand, AdjustResult, CreditsService, LedgerRecord, LotRecord, WalletView

type ActivityStoreOf = Callable[[AsyncSession], BillingActivityStore]

LEDGER_KEY_PREFIX = "admin-adjust:"


@dataclass(frozen=True)
class AdminAdjustCommand:
    admin_id: UUID
    user_id: UUID
    delta: int
    reason: str
    key: str
    expires_at: datetime | None = None


@dataclass(frozen=True)
class UserCredits:
    user_id: UUID
    wallet: WalletView
    lots: RecordPage[LotRecord]


def adjustment_ledger_key(admin_id: UUID, user_id: UUID, key: str) -> str:
    digest = hashlib.sha256(f"{admin_id}:{user_id}:{key}".encode()).hexdigest()
    return f"{LEDGER_KEY_PREFIX}{digest}"


class CreditsAdminService:
    def __init__(
        self,
        transaction: Transaction,
        codec: CursorCodec,
        ledger: CreditsService,
        *,
        store_factory: ActivityStoreOf = SqlBillingActivityRepository,
    ) -> None:
        self._transaction = transaction
        self._codec = codec
        self._credits = ledger
        self._store_factory = store_factory

    def _token(self, cursor: Cursor | None) -> str | None:
        return self._codec.encode(cursor) if cursor is not None else None

    async def wallet(self, user_id: UUID, cursor: str | None, limit: int) -> UserCredits:
        position = decode_cursor(self._codec, cursor)
        async with self._transaction() as session:
            await self._require_user(session, user_id)
            view = await self._credits.wallet(session, user_id)
            page = await self._credits.lots(session, user_id, position, limit)
        return UserCredits(user_id=user_id, wallet=view, lots=RecordPage(page.items, self._token(page.next_cursor)))

    async def ledger(self, user_id: UUID, cursor: str | None, limit: int) -> RecordPage[LedgerRecord]:
        position = decode_cursor(self._codec, cursor)
        async with self._transaction() as session:
            await self._require_user(session, user_id)
            page = await self._credits.ledger(session, user_id, position, limit)
        return RecordPage(page.items, self._token(page.next_cursor))

    async def adjust(self, command: AdminAdjustCommand) -> AdjustResult:
        async with self._transaction() as session:
            await self._require_user(session, command.user_id)
            return await self._credits.adjust(
                session,
                AdjustCommand(
                    user_id=command.user_id,
                    delta=command.delta,
                    reason=command.reason,
                    actor_id=command.admin_id,
                    key=adjustment_ledger_key(command.admin_id, command.user_id, command.key),
                    expires_at=command.expires_at,
                ),
            )

    async def _require_user(self, session: AsyncSession, user_id: UUID) -> None:
        if not await self._store_factory(session).user_exists(user_id):
            raise AdminUserNotFoundError
