from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import orjson
import structlog

from motionile.core.alerts import raise_alert
from motionile.core.clock import Clock
from motionile.core.config import BillingSettings
from motionile.core.storage.base import Storage
from motionile.modules.billing.exceptions import SettlementWindowTooLargeError
from motionile.modules.billing.ports import Alert, StoreFactory, Transaction
from motionile.modules.billing.razorpay.api import MAX_LIST_COUNT, RazorpayApi
from motionile.modules.billing.razorpay.exceptions import RazorpayNotFoundError
from motionile.modules.billing.records import LocalPayment, PaymentRecord, RunClaim, RunCounts, RunOutcome
from motionile.modules.billing.repository import SqlBillingRepository
from motionile.modules.billing.services.settlement_diff import (
    DiffTally,
    DiscrepancyKind,
    JsonObject,
    compare_payment,
    extra_payment,
)
from motionile.modules.billing.services.webhook_processor import describe_failure
from motionile.modules.billing.states import RunStatus

LOCAL_PAGE_SIZE = 500
MAX_REMOTE_PAGES = 1_000
STALE_RUN_AFTER = timedelta(hours=1)
REPORT_CONTENT_TYPE = "application/json"
REPORT_SEGMENT = "settlement"
ONE_SECOND = timedelta(seconds=1)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SettlementWindow:
    day: date
    start: datetime
    end: datetime


@dataclass(frozen=True)
class SettlementCheckResult:
    run_id: UUID
    day: date
    report_key: str
    checked: int
    mismatches: int
    resumed: bool


@dataclass(frozen=True)
class SettlementCheckDependencies:
    transaction: Transaction
    razorpay: RazorpayApi
    storage: Storage
    clock: Clock
    settings: BillingSettings


def window_for(day: date) -> SettlementWindow:
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return SettlementWindow(day, start, start + timedelta(days=1))


def previous_day(now: datetime) -> date:
    return (now.astimezone(UTC) - timedelta(days=1)).date()


async def single_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


class SettlementCheck:
    def __init__(
        self,
        deps: SettlementCheckDependencies,
        *,
        store_factory: StoreFactory = SqlBillingRepository,
        alert: Alert = raise_alert,
    ) -> None:
        self._transaction = deps.transaction
        self._razorpay = deps.razorpay
        self._storage = deps.storage
        self._clock = deps.clock
        self._settings = deps.settings
        self._store_factory = store_factory
        self._alert = alert

    async def run(self, day: date | None = None) -> SettlementCheckResult | None:
        window = window_for(day or previous_day(self._clock.now()))
        claim = await self._claim(window)
        if claim is None:
            return None
        try:
            tally = await self._compare(window)
            report_key = await self._write_report(window, claim, tally)
        except Exception as error:
            await self._finish_failed(claim, error)
            raise
        await self._finish(claim, tally, report_key)
        if tally.mismatches > 0:
            self._alert(
                "billing.reconciliation_mismatch",
                run_id=str(claim.run_id),
                day=window.day.isoformat(),
                missing=tally.count(DiscrepancyKind.MISSING),
                extra=tally.count(DiscrepancyKind.EXTRA),
                mismatched=tally.count(DiscrepancyKind.MISMATCHED),
                report_key=report_key,
            )
        return SettlementCheckResult(
            claim.run_id, window.day, report_key, tally.checked, tally.mismatches, claim.resumed
        )

    async def _claim(self, window: SettlementWindow) -> RunClaim | None:
        now = self._clock.now()
        async with self._transaction() as session:
            return await self._store_factory(session).claim_settlement_run(
                window.start, window.end, now, now - STALE_RUN_AFTER
            )

    async def _compare(self, window: SettlementWindow) -> DiffTally:
        tally = DiffTally()
        local = await self._local_window(window)
        seen: set[str] = set()
        for page_number in range(MAX_REMOTE_PAGES):
            page = await self._razorpay.list_payments(
                from_ts=window.start,
                to_ts=window.end - ONE_SECOND,
                count=MAX_LIST_COUNT,
                skip=page_number * MAX_LIST_COUNT,
            )
            for remote in page:
                seen.add(remote.id)
                tally.examined()
                counterpart = local.get(remote.id) or await self._local_payment(remote.id)
                discrepancy = compare_payment(remote, counterpart)
                if discrepancy is not None:
                    tally.add(discrepancy)
            if len(page) < MAX_LIST_COUNT:
                await self._verify_extras(local, seen, tally)
                return tally
        raise SettlementWindowTooLargeError(MAX_REMOTE_PAGES)

    async def _verify_extras(self, local: dict[str, LocalPayment], seen: set[str], tally: DiffTally) -> None:
        for razorpay_id, candidate in local.items():
            if razorpay_id in seen:
                continue
            tally.examined()
            try:
                remote = await self._razorpay.fetch_payment(razorpay_id)
            except RazorpayNotFoundError:
                tally.add(extra_payment(candidate))
                continue
            discrepancy = compare_payment(remote, candidate)
            if discrepancy is not None:
                tally.add(discrepancy)

    async def _local_window(self, window: SettlementWindow) -> dict[str, LocalPayment]:
        found: dict[str, LocalPayment] = {}
        after: UUID | None = None
        while True:
            async with self._transaction() as session:
                store = self._store_factory(session)
                page = await store.captured_payments_between(window.start, window.end, after, LOCAL_PAGE_SIZE)
                pending = await store.pending_refund_totals([payment.id for payment in page])
            for payment in page:
                found[payment.razorpay_payment_id] = LocalPayment(payment, pending.get(payment.id, 0))
            if len(page) < LOCAL_PAGE_SIZE:
                return found
            after = page[-1].id

    async def _local_payment(self, razorpay_payment_id: str) -> LocalPayment | None:
        async with self._transaction() as session:
            store = self._store_factory(session)
            payment: PaymentRecord | None = await store.payment_by_razorpay_id(razorpay_payment_id)
            if payment is None:
                return None
            pending = await store.pending_refund_totals([payment.id])
        return LocalPayment(payment, pending.get(payment.id, 0))

    async def _write_report(self, window: SettlementWindow, claim: RunClaim, tally: DiffTally) -> str:
        key = f"{self._settings.report_storage_prefix}/{REPORT_SEGMENT}/{window.day.isoformat()}.json"
        document: JsonObject = {
            "date": window.day.isoformat(),
            "periodStart": window.start.isoformat(),
            "periodEnd": window.end.isoformat(),
            "generatedAt": self._clock.now().isoformat(),
            "runId": str(claim.run_id),
            "counts": {
                "checked": tally.checked,
                "mismatches": tally.mismatches,
                **tally.summary(),
            },
            "truncated": tally.truncated,
            "mismatches": [item.as_json() for item in tally.listed],
        }
        await self._storage.put(
            key,
            single_chunk(orjson.dumps(document)),
            content_type=REPORT_CONTENT_TYPE,
            metadata={"run": str(claim.run_id)},
        )
        return key

    async def _finish(self, claim: RunClaim, tally: DiffTally, report_key: str) -> None:
        outcome = RunOutcome(
            status=RunStatus.COMPLETED,
            counts=RunCounts(checked=tally.checked, repaired=0, mismatch=tally.mismatches),
            finished_at=self._clock.now(),
            summary=tally.summary(),
            report_storage_key=report_key,
        )
        async with self._transaction() as session:
            await self._store_factory(session).finish_run(claim.run_id, outcome)

    async def _finish_failed(self, claim: RunClaim, error: Exception) -> None:
        logger.exception("billing.settlement_check_failed", run_id=str(claim.run_id))
        outcome = RunOutcome(
            status=RunStatus.FAILED,
            counts=RunCounts(),
            finished_at=self._clock.now(),
            error=describe_failure(error),
        )
        async with self._transaction() as session:
            await self._store_factory(session).finish_run(claim.run_id, outcome)
