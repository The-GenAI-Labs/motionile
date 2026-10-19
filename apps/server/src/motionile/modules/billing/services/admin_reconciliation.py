from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.pagination import CursorCodec
from motionile.core.storage.base import Storage
from motionile.modules.billing.admin_activity_repository import BillingActivityStore, SqlBillingActivityRepository
from motionile.modules.billing.admin_records import RecordPage, RunFilter, RunRow
from motionile.modules.billing.exceptions import ReconciliationReportNotFoundError, ReconciliationRunNotFoundError
from motionile.modules.billing.ports import Transaction
from motionile.modules.billing.services.admin_paging import decode_cursor, record_page

type ActivityStoreOf = Callable[[AsyncSession], BillingActivityStore]


@dataclass
class ReportDownload:
    filename: str
    size_bytes: int
    chunks: AsyncIterator[bytes]


class ReconciliationAdminService:
    def __init__(
        self,
        transaction: Transaction,
        codec: CursorCodec,
        storage: Storage,
        *,
        store_factory: ActivityStoreOf = SqlBillingActivityRepository,
    ) -> None:
        self._transaction = transaction
        self._codec = codec
        self._storage = storage
        self._store_factory = store_factory

    async def list(self, query: RunFilter, cursor: str | None, limit: int) -> RecordPage[RunRow]:
        position = decode_cursor(self._codec, cursor)
        async with self._transaction() as session:
            rows = await self._store_factory(session).list_runs(query, position, limit)
        return record_page(rows, limit, self._codec, lambda row: (row.created_at, row.id))

    async def get(self, run_id: UUID) -> RunRow:
        async with self._transaction() as session:
            row = await self._store_factory(session).run_row(run_id)
        if row is None:
            raise ReconciliationRunNotFoundError
        return row

    async def report(self, run_id: UUID) -> ReportDownload:
        run = await self.get(run_id)
        if run.report_storage_key is None:
            raise ReconciliationReportNotFoundError
        info = await self._storage.head(run.report_storage_key)
        if info is None:
            raise ReconciliationReportNotFoundError
        return ReportDownload(
            filename=f"reconciliation-{run.type}-{run.id}.json",
            size_bytes=info.size_bytes,
            chunks=self._storage.get(run.report_storage_key),
        )
