from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from uuid import UUID

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.alerts import raise_alert
from motionile.core.config import get_settings
from motionile.core.resources import Resources, build_resources
from motionile.core.tasks.registry import Queue, periodic_task
from motionile.modules.credits.domain import IntegrityViolation, ReminderBatch
from motionile.modules.credits.service import CreditsService
from motionile.modules.notifications import enqueue_billing_email
from motionile.modules.users import UsersService

BATCH_SIZE = 200
REMINDER_DATE_FORMAT = "%d %B %Y"

logger = structlog.get_logger(__name__)

type Transaction = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type EmailResolver = Callable[[AsyncSession, UUID], Awaitable[str | None]]
type ReminderSender = Callable[[AsyncSession, str, ReminderBatch], None]


class SweepFailedError(RuntimeError):
    def __init__(self, task_name: str, failures: int) -> None:
        super().__init__(f"{task_name} failed for {failures} item(s)")
        self.failures = failures


async def sweep_expired_lots(transaction: Transaction, service: CreditsService) -> int:
    expired = 0
    failures = 0
    after: UUID | None = None
    while True:
        async with transaction() as session:
            users = await service.users_due_for_expiry(session, after, BATCH_SIZE)
        for user_id in users:
            try:
                async with transaction() as session:
                    expired += (await service.expire_due_lots(session, user_id)).expired
            except Exception:
                logger.exception("credits.expire_lots_failed", user_id=str(user_id))
                failures += 1
        if len(users) < BATCH_SIZE:
            break
        after = users[-1]
    if failures:
        raise SweepFailedError("credits.expire_lots", failures)
    return expired


async def sweep_stale_reservations(transaction: Transaction, service: CreditsService) -> int:
    released = 0
    failures = 0
    after: UUID | None = None
    while True:
        async with transaction() as session:
            reservation_ids = await service.stale_reservation_ids(session, after, BATCH_SIZE)
        for reservation_id in reservation_ids:
            try:
                async with transaction() as session:
                    if await service.release_stale(session, reservation_id) is not None:
                        released += 1
            except Exception:
                logger.exception("credits.release_stale_failed", reservation_id=str(reservation_id))
                failures += 1
        if len(reservation_ids) < BATCH_SIZE:
            break
        after = reservation_ids[-1]
    if failures:
        raise SweepFailedError("credits.release_stale_reservations", failures)
    return released


async def remind_expiring_credits(
    transaction: Transaction, service: CreditsService, resolve_email: EmailResolver, send: ReminderSender
) -> int:
    queued = 0
    while True:
        async with transaction() as session:
            batches = await service.claim_expiry_reminders(session, BATCH_SIZE)
            for batch in batches:
                email = await resolve_email(session, batch.user_id)
                if email is not None:
                    send(session, email, batch)
                    queued += 1
        if len(batches) < BATCH_SIZE:
            return queued


async def verify_integrity(transaction: Transaction, service: CreditsService) -> list[IntegrityViolation]:
    async with transaction() as session:
        violations = await service.check_integrity(session)
    if violations:
        raise_alert(
            "credit_integrity_violation",
            user_ids=[str(violation.user_id) for violation in violations],
            violations=[
                {
                    "userId": str(violation.user_id),
                    "problems": [
                        {"invariant": problem.invariant, "expected": problem.expected, "actual": problem.actual}
                        for problem in violation.problems
                    ],
                }
                for violation in violations
            ],
        )
    return violations


async def primary_email(session: AsyncSession, user_id: UUID) -> str | None:
    return await UsersService(session).primary_verified_email(user_id)


def reminder_sender(resources: Resources) -> ReminderSender:
    def send(session: AsyncSession, email: str, batch: ReminderBatch) -> None:
        enqueue_billing_email(
            resources,
            session,
            email=email,
            template="credits_expiring",
            context={
                "credits": str(batch.credits),
                "expires_on": batch.expires_at.strftime(REMINDER_DATE_FORMAT),
            },
        )

    return send


async def run_sweep(application_name: str, sweep: Callable[[Transaction, CreditsService], Awaitable[object]]) -> None:
    settings = get_settings()
    resources = build_resources(settings, application_name=application_name)
    try:
        await sweep(resources.database.transaction, CreditsService(resources.clock, settings.billing))
    finally:
        await resources.aclose()


@periodic_task(name="credits.expire_lots", queue=Queue.BILLING, cron="*/15 * * * *")
async def expire_lots() -> None:
    await run_sweep("motionile-credits-expiry", sweep_expired_lots)


@periodic_task(name="credits.release_stale_reservations", queue=Queue.BILLING, cron="*/5 * * * *")
async def release_stale_reservations() -> None:
    await run_sweep("motionile-credits-reservations", sweep_stale_reservations)


@periodic_task(name="credits.send_expiry_reminders", queue=Queue.BILLING, cron="0 * * * *")
async def send_expiry_reminders() -> None:
    settings = get_settings()
    resources = build_resources(settings, application_name="motionile-credits-reminders")
    try:
        await remind_expiring_credits(
            resources.database.transaction,
            CreditsService(resources.clock, settings.billing),
            primary_email,
            reminder_sender(resources),
        )
    finally:
        await resources.aclose()


@periodic_task(name="credits.check_integrity", queue=Queue.BILLING, cron="30 2 * * *")
async def check_integrity() -> None:
    await run_sweep("motionile-credits-integrity", verify_integrity)
