from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from uuid import UUID

import structlog
from procrastinate import RetryStrategy
from procrastinate.jobs import Job
from procrastinate.retry import RetryDecision
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.config import get_settings
from motionile.core.resources import build_resources
from motionile.core.tasks.app import TASK_NAMESPACE
from motionile.core.tasks.registry import Queue, defer_after_commit, periodic_task, task
from motionile.modules.billing.services.factory import BillingServices, ServiceHooks, build_services
from motionile.modules.billing.services.products import REVALIDATION_TAG
from motionile.modules.catalog import push_revalidation

PROCESS_EVENT_TASK = "billing.process_webhook_event"
REQUEUE_TASK = "billing.requeue_stuck_webhooks"
RECONCILE_TASK = "billing.reconcile_pending_orders"
REVALIDATE_TASK = "billing.revalidate_products"
FINALIZE_TASK = "billing.finalize_subscriptions"
SYNC_TASK = "billing.sync_subscriptions"
SETTLEMENT_TASK = "billing.settlement_check"
REFUND_RECONCILE_TASK = "billing.reconcile_pending_refunds"
EXPONENTIAL_WAIT_BASE = 2

logger = structlog.get_logger(__name__)


class WebhookRetryStrategy(RetryStrategy):
    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        if job.attempts + 1 >= get_settings().billing.webhook_max_attempts:
            return None
        return super().get_retry_decision(exception=exception, job=job)


@task(name=PROCESS_EVENT_TASK, queue=Queue.BILLING, retry=WebhookRetryStrategy(exponential_wait=EXPONENTIAL_WAIT_BASE))
async def process_webhook_event(event_row_id: str, force: bool = False) -> None:
    async with worker_services("motionile-billing-webhooks") as services:
        await services.processor.process(UUID(event_row_id), force=force)


def defer_event_processing(session: AsyncSession, event_row_id: UUID, force: bool) -> None:
    defer_after_commit(session, process_webhook_event, event_row_id=str(event_row_id), force=force)


def worker_hooks() -> ServiceHooks:
    return ServiceHooks(
        dispatch=defer_event_processing,
        process_task_name=f"{TASK_NAMESPACE}:{PROCESS_EVENT_TASK}",
        revalidate=defer_product_revalidation,
    )


@asynccontextmanager
async def worker_services(application_name: str) -> AsyncGenerator[BillingServices]:
    resources = build_resources(get_settings(), application_name=application_name)
    try:
        yield build_services(resources, worker_hooks())
    finally:
        await resources.aclose()


@periodic_task(name=REQUEUE_TASK, queue=Queue.BILLING, cron="*/2 * * * *")
async def requeue_stuck_webhooks() -> None:
    async with worker_services("motionile-billing-requeue") as services:
        requeued = await services.requeuer.requeue_stuck()
    logger.info("billing.webhooks_requeued", count=requeued)


@periodic_task(name=RECONCILE_TASK, queue=Queue.BILLING, cron="*/15 * * * *")
async def reconcile_pending_orders() -> None:
    async with worker_services("motionile-billing-reconciliation") as services:
        counts = await services.reconciliation.reconcile_pending_orders()
    logger.info(
        "billing.orders_reconciled",
        checked=counts.checked,
        repaired=counts.repaired,
        mismatch=counts.mismatch,
        errors=counts.errors,
    )


@periodic_task(name=FINALIZE_TASK, queue=Queue.BILLING, cron="*/15 * * * *")
async def finalize_subscriptions() -> None:
    async with worker_services("motionile-billing-finalization") as services:
        counts = await services.subscriptions.finalizer.finalize()
    logger.info("billing.subscriptions_finalized", cancelled=counts.cancelled, expired=counts.expired)


@periodic_task(name=SYNC_TASK, queue=Queue.BILLING, cron="15 3 * * *")
async def sync_subscriptions() -> None:
    async with worker_services("motionile-billing-subscription-sync") as services:
        counts = await services.subscriptions.sync.run()
    logger.info(
        "billing.subscriptions_synced",
        checked=counts.checked,
        repaired=counts.repaired,
        mismatch=counts.mismatch,
        errors=counts.errors,
    )


@periodic_task(name=SETTLEMENT_TASK, queue=Queue.BILLING, cron="0 4 * * *")
async def settlement_check() -> None:
    async with worker_services("motionile-billing-settlement-check") as services:
        result = await services.settlement_check.run()
    if result is None:
        logger.info("billing.settlement_check_skipped")
        return
    logger.info(
        "billing.settlement_checked",
        day=result.day.isoformat(),
        checked=result.checked,
        mismatches=result.mismatches,
        report_key=result.report_key,
    )


@periodic_task(name=REFUND_RECONCILE_TASK, queue=Queue.BILLING, cron="*/15 * * * *")
async def reconcile_pending_refunds() -> None:
    async with worker_services("motionile-billing-refund-reconciliation") as services:
        counts = await services.refunds.reconcile_stale()
    logger.info("billing.refunds_reconciled", linked=counts.linked, failed=counts.failed, errors=counts.errors)


@task(name=REVALIDATE_TASK, queue=Queue.DEFAULT)
async def revalidate_products() -> None:
    await push_revalidation([REVALIDATION_TAG])


def defer_product_revalidation(session: AsyncSession) -> None:
    defer_after_commit(session, revalidate_products)
