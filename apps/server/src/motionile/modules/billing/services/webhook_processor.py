from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

import structlog
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.alerts import raise_alert
from motionile.core.clock import Clock
from motionile.modules.billing.exceptions import WebhookProcessingError
from motionile.modules.billing.ports import Alert, Savepoint, StoreFactory, Transaction, begin_savepoint
from motionile.modules.billing.records import WebhookEventRecord
from motionile.modules.billing.repository import SqlBillingRepository
from motionile.modules.billing.services.webhook_registry import UNHANDLED_EVENT, HandlerRegistry, Outcome, ignored
from motionile.modules.billing.states import REPROCESSABLE_EVENT_STATUSES, WebhookEventStatus
from motionile.modules.billing.transitions import transition_event

ERROR_LIMIT = 2000
MESSAGE_LIMIT = 500
VALIDATION_ERROR_LIMIT = 10
SETTLED_STATUSES = frozenset({WebhookEventStatus.PROCESSED, WebhookEventStatus.IGNORED})
STARTABLE_STATUSES = REPROCESSABLE_EVENT_STATUSES | {WebhookEventStatus.RECEIVED}

logger = structlog.get_logger(__name__)

type MaxAttempts = Callable[[], int]


class ProcessingState(StrEnum):
    PROCESSED = "processed"
    IGNORED = "ignored"
    SKIPPED = "skipped"
    MISSING = "missing"
    FAILED_FINAL = "failed_final"


@dataclass(frozen=True)
class ProcessingResult:
    state: ProcessingState
    attempts: int = 0


def describe_failure(error: BaseException) -> str:
    if isinstance(error, ValidationError):
        problems = error.errors(include_input=False, include_url=False, include_context=False)
        shown = "; ".join(
            f"{'.'.join(str(part) for part in problem['loc'])}: {problem['msg']}"
            for problem in problems[:VALIDATION_ERROR_LIMIT]
        )
        return f"ValidationError: {shown}"[:ERROR_LIMIT]
    message = (str(error).splitlines() or [""])[0][:MESSAGE_LIMIT]
    name = type(error).__name__
    return (f"{name}: {message}" if message else name)[:ERROR_LIMIT]


@dataclass(frozen=True)
class Attempt:
    result: ProcessingResult
    error: Exception | None = None


@dataclass(frozen=True)
class ProcessorPorts:
    store_factory: StoreFactory = SqlBillingRepository
    savepoint: Savepoint = begin_savepoint
    alert: Alert = raise_alert


class WebhookProcessor:
    def __init__(
        self,
        transaction: Transaction,
        registry: HandlerRegistry,
        clock: Clock,
        max_attempts: MaxAttempts,
        ports: ProcessorPorts | None = None,
    ) -> None:
        resolved = ports or ProcessorPorts()
        self._transaction = transaction
        self._registry = registry
        self._clock = clock
        self._max_attempts = max_attempts
        self._store_factory = resolved.store_factory
        self._savepoint = resolved.savepoint
        self._alert = resolved.alert

    async def process(self, event_row_id: UUID, *, force: bool = False) -> ProcessingResult:
        try:
            async with self._transaction() as session:
                attempt = await self._attempt(session, event_row_id, force=force)
        except Exception as error:
            return self._conclude(event_row_id, error, await self._record_failure(event_row_id, error))
        if attempt.error is not None:
            return self._conclude(event_row_id, attempt.error, attempt.result.attempts)
        return attempt.result

    async def _attempt(self, session: AsyncSession, event_row_id: UUID, *, force: bool) -> Attempt:
        store = self._store_factory(session)
        event = await store.lock_event(event_row_id)
        if event is None:
            return Attempt(ProcessingResult(ProcessingState.MISSING))
        if event.status not in STARTABLE_STATUSES or (event.status in SETTLED_STATUSES and not force):
            return Attempt(ProcessingResult(ProcessingState.SKIPPED, event.attempts))
        attempts = event.attempts + 1
        await transition_event(store, event.id, event.status, WebhookEventStatus.PROCESSING, {"attempts": attempts})
        try:
            async with self._savepoint(session):
                outcome = await self._dispatch(session, event)
        except Exception as error:
            await transition_event(
                store,
                event.id,
                WebhookEventStatus.PROCESSING,
                WebhookEventStatus.FAILED,
                {"last_error": describe_failure(error)},
            )
            return Attempt(ProcessingResult(ProcessingState.FAILED_FINAL, attempts), error)
        await transition_event(
            store,
            event.id,
            WebhookEventStatus.PROCESSING,
            WebhookEventStatus.IGNORED if outcome.ignored else WebhookEventStatus.PROCESSED,
            {"ignored_reason": outcome.ignored_reason, "last_error": None, "processed_at": self._clock.now()},
        )
        return Attempt(
            ProcessingResult(ProcessingState.IGNORED if outcome.ignored else ProcessingState.PROCESSED, attempts)
        )

    async def _dispatch(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        handler = self._registry.handler_for(event.event_type)
        if handler is None:
            return ignored(UNHANDLED_EVENT)
        return await handler(session, event)

    async def _record_failure(self, event_row_id: UUID, error: Exception) -> int:
        async with self._transaction() as session:
            store = self._store_factory(session)
            event = await store.lock_event(event_row_id)
            if event is None:
                return 0
            attempts = event.attempts + 1
            await transition_event(store, event.id, event.status, WebhookEventStatus.PROCESSING, {"attempts": attempts})
            await transition_event(
                store,
                event.id,
                WebhookEventStatus.PROCESSING,
                WebhookEventStatus.FAILED,
                {"last_error": describe_failure(error)},
            )
            return attempts

    def _conclude(self, event_row_id: UUID, error: Exception, attempts: int) -> ProcessingResult:
        logger.warning(
            "billing.webhook_attempt_failed",
            event_row_id=str(event_row_id),
            attempts=attempts,
            error=type(error).__name__,
        )
        if attempts >= self._max_attempts():
            self._alert(
                "billing.webhook_failed",
                event_id=str(event_row_id),
                attempts=attempts,
                error_type=type(error).__name__,
            )
            return ProcessingResult(ProcessingState.FAILED_FINAL, attempts)
        raise WebhookProcessingError(str(event_row_id), attempts) from error
