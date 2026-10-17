from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.billing_support import PACK_CREDITS, PACK_PRICE, PROCESS_TASK_NAME, BillingApi

from motionile.modules.billing.exceptions import WebhookProcessingError
from motionile.modules.billing.records import WebhookEventRecord
from motionile.modules.billing.services.webhook_processor import ProcessingState, ProcessorPorts, WebhookProcessor
from motionile.modules.billing.services.webhook_recovery import RequeuePolicy, WebhookRequeuer, reprocess_event_with
from motionile.modules.billing.services.webhook_registry import PROCESSED, Outcome

STALE = timedelta(minutes=31)
OVERDUE = timedelta(hours=2, minutes=1)
MAX_ATTEMPTS = 3


async def run_rows(api: BillingApi) -> list[tuple[str, str, int, int, int, dict[str, Any]]]:
    async with api.database.transaction() as session:
        rows = await session.execute(
            text(
                "SELECT type, status, checked_count, repaired_count, mismatch_count, summary "
                "FROM billing_reconciliation_runs ORDER BY created_at, id"
            )
        )
        return [(row[0], row[1], row[2], row[3], row[4], row[5]) for row in rows]


async def test_reconciliation_settles_an_order_whose_webhook_and_handler_were_both_dropped(
    billing_api: BillingApi,
) -> None:
    checkout = await billing_api.checkout()
    await billing_api.pay(checkout["razorpayOrderId"], webhooks=["payment.captured", "order.paid"])
    billing_api.recorded.dispatched.clear()
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0
    billing_api.clock.advance(STALE)

    counts = await billing_api.services.reconciliation.reconcile_pending_orders()

    assert (counts.checked, counts.repaired, counts.mismatch, counts.errors) == (1, 1, 0, 0)
    order = await billing_api.order_row(checkout["orderId"])
    assert (order.status, order.paid_at is not None) == ("paid", True)
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS
    assert len(billing_api.recorded.receipts) == 1
    [(run_type, status, checked, repaired, mismatch, summary)] = await run_rows(billing_api)
    assert (run_type, status, checked, repaired, mismatch) == ("pending_orders", "completed", 1, 1, 0)
    assert summary == {"settled": 1, "expired": 0, "errors": 0}


async def test_a_late_webhook_after_reconciliation_does_not_grant_twice(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()
    await billing_api.pay(checkout["razorpayOrderId"], webhooks=["payment.captured"])
    queued = list(billing_api.recorded.dispatched)
    billing_api.recorded.dispatched.clear()
    billing_api.clock.advance(STALE)
    await billing_api.services.reconciliation.reconcile_pending_orders()

    for event_id, _ in queued:
        await billing_api.services.processor.process(event_id)

    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS
    assert len(await billing_api.ledger_rows(billing_api.primary_id)) == 1
    assert [event.status for event in await billing_api.event_rows()] == ["processed"]


async def test_reconciliation_expires_overdue_unpaid_orders_and_leaves_flagged_ones_alone(
    billing_api: BillingApi,
) -> None:
    unpaid = await billing_api.checkout()
    recent = await billing_api.checkout()
    mismatched = await billing_api.checkout()
    await billing_api.pay(mismatched["razorpayOrderId"], amountPaise=PACK_PRICE + 1)
    billing_api.clock.advance(STALE)

    first = await billing_api.services.reconciliation.reconcile_pending_orders()

    assert (first.checked, first.repaired, first.mismatch) == (3, 0, 1)
    assert (await billing_api.order_row(mismatched["orderId"])).flag_reason == "amount_mismatch"
    assert (await billing_api.order_row(unpaid["orderId"])).status == "pending"

    billing_api.clock.advance(OVERDUE)
    second = await billing_api.services.reconciliation.reconcile_pending_orders()

    assert (second.checked, second.repaired, second.mismatch) == (2, 2, 0)
    assert (await billing_api.order_row(unpaid["orderId"])).status == "expired"
    assert (await billing_api.order_row(recent["orderId"])).status == "expired"
    assert (await billing_api.order_row(mismatched["orderId"])).status == "pending"
    assert await billing_api.wallet_balance(billing_api.primary_id) == 0
    assert [(row[0], row[1]) for row in await run_rows(billing_api)] == [("pending_orders", "completed")] * 2


async def test_an_order_that_was_paid_after_it_expired_still_settles_through_a_webhook(
    billing_api: BillingApi,
) -> None:
    checkout = await billing_api.checkout()
    billing_api.clock.advance(OVERDUE)
    await billing_api.services.reconciliation.reconcile_pending_orders()
    assert (await billing_api.order_row(checkout["orderId"])).status == "expired"

    await billing_api.pay(checkout["razorpayOrderId"], webhooks=["payment.captured"])
    await billing_api.process_dispatched()

    assert (await billing_api.order_row(checkout["orderId"])).status == "paid"
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS
    assert "billing.order.settled_late" in await billing_api.audit_actions()


async def test_a_provider_failure_on_one_order_does_not_stop_the_others(billing_api: BillingApi) -> None:
    first = await billing_api.checkout()
    second = await billing_api.checkout()
    await billing_api.pay(first["razorpayOrderId"])
    await billing_api.pay(second["razorpayOrderId"])
    await billing_api.primary.post(
        "/v1/_test/razorpay/faults", json={"operation": "order_payments", "kind": "server_error"}
    )
    billing_api.clock.advance(STALE)

    counts = await billing_api.services.reconciliation.reconcile_pending_orders()

    assert (counts.checked, counts.repaired, counts.errors) == (2, 1, 1)
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS
    [(_, status, _, _, _, summary)] = await run_rows(billing_api)
    assert (status, summary["errors"]) == ("completed", 1)

    again = await billing_api.services.reconciliation.reconcile_pending_orders()

    assert again.repaired == 1
    assert await billing_api.wallet_balance(billing_api.primary_id) == 2 * PACK_CREDITS


class Handler:
    def __init__(self, api: BillingApi) -> None:
        self.api = api
        self.healthy = False
        self.calls = 0

    async def __call__(self, session: AsyncSession, event: WebhookEventRecord) -> Outcome:
        del event
        self.calls += 1
        await session.execute(text("UPDATE products SET sort_order = 99"))
        if not self.healthy:
            message = "handler exploded for customer@example.com"
            raise RuntimeError(message)
        return PROCESSED


async def failing_event(api: BillingApi, handler: Handler) -> UUID:
    api.services.registry.register_handler("test.failing", handler)
    response = await api.post_webhook({"event": "test.failing", "payload": {}}, event_id=f"evt_{api.keys()}")
    assert response.json() == {"status": "received"}
    [(event_row_id, _)] = api.recorded.dispatched
    api.recorded.dispatched.clear()
    return event_row_id


def limited_processor(api: BillingApi) -> WebhookProcessor:
    return WebhookProcessor(
        api.database.transaction,
        api.services.registry,
        api.clock,
        lambda: MAX_ATTEMPTS,
        ProcessorPorts(alert=api.recorded.alert),
    )


async def sort_orders(api: BillingApi) -> set[int]:
    async with api.database.transaction() as session:
        return {row[0] for row in await session.execute(text("SELECT sort_order FROM products"))}


async def test_a_failing_handler_is_rolled_back_marked_failed_retried_and_alerts_after_the_last_attempt(
    billing_api: BillingApi,
) -> None:
    handler = Handler(billing_api)
    event_row_id = await failing_event(billing_api, handler)
    processor = limited_processor(billing_api)

    for attempt in range(1, MAX_ATTEMPTS):
        with pytest.raises(WebhookProcessingError) as raised:
            await processor.process(event_row_id)
        assert raised.value.attempts == attempt
        [event] = await billing_api.event_rows()
        assert (event.status, event.attempts) == ("failed", attempt)
        assert event.last_error == "RuntimeError: handler exploded for customer@example.com"
        assert event.processed_at is None
        assert await sort_orders(billing_api) == {0}
        assert billing_api.recorded.alerts == []

    final = await processor.process(event_row_id)

    assert (final.state, final.attempts) == (ProcessingState.FAILED_FINAL, MAX_ATTEMPTS)
    [event] = await billing_api.event_rows()
    assert (event.status, event.attempts) == ("failed", MAX_ATTEMPTS)
    [(code, fields)] = billing_api.recorded.alerts
    assert code == "billing.webhook_failed"
    assert (fields["event_id"], fields["attempts"]) == (str(event_row_id), MAX_ATTEMPTS)
    assert handler.calls == MAX_ATTEMPTS
    assert await sort_orders(billing_api) == {0}


async def test_an_admin_can_reprocess_a_failed_event_after_the_cause_is_fixed(billing_api: BillingApi) -> None:
    handler = Handler(billing_api)
    event_row_id = await failing_event(billing_api, handler)
    processor = limited_processor(billing_api)
    for _ in range(MAX_ATTEMPTS - 1):
        with pytest.raises(WebhookProcessingError):
            await processor.process(event_row_id)
    await processor.process(event_row_id)
    handler.healthy = True

    async with billing_api.database.transaction() as session:
        reprocessed = await reprocess_event_with(session, event_row_id, billing_api.recorded.dispatch)
    assert reprocessed.id == event_row_id
    assert billing_api.recorded.dispatched == [(event_row_id, True)]
    result = await processor.process(event_row_id, force=True)

    assert result.state is ProcessingState.PROCESSED
    [event] = await billing_api.event_rows()
    assert (event.status, event.last_error, event.attempts) == ("processed", None, MAX_ATTEMPTS + 1)
    assert await sort_orders(billing_api) == {99}


async def test_processed_events_can_be_replayed_without_double_effects(billing_api: BillingApi) -> None:
    checkout = await billing_api.checkout()
    await billing_api.pay(checkout["razorpayOrderId"], webhooks=["payment.captured"])
    [(event_row_id, _)] = billing_api.recorded.dispatched
    await billing_api.process_dispatched()
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS

    async with billing_api.database.transaction() as session:
        await reprocess_event_with(session, event_row_id, billing_api.recorded.dispatch)
    await billing_api.process_dispatched()

    [event] = await billing_api.event_rows()
    assert (event.status, event.attempts) == ("processed", 2)
    assert await billing_api.wallet_balance(billing_api.primary_id) == PACK_CREDITS
    assert len(await billing_api.ledger_rows(billing_api.primary_id)) == 1


def requeuer_for(api: BillingApi) -> WebhookRequeuer:
    return WebhookRequeuer(
        api.database.transaction,
        api.clock,
        api.recorded.dispatch,
        RequeuePolicy(lambda: MAX_ATTEMPTS, PROCESS_TASK_NAME),
    )


async def insert_job(api: BillingApi, event_row_id: UUID, status: str) -> None:
    async with api.database.transaction() as session:
        await session.execute(
            text(
                "INSERT INTO procrastinate_jobs (queue_name, task_name, args, status) "
                "VALUES ('billing', :task, CAST(:args AS jsonb), CAST(:status AS procrastinate_job_status))"
            ),
            {"task": PROCESS_TASK_NAME, "args": f'{{"event_row_id": "{event_row_id}"}}', "status": status},
        )


async def test_stuck_received_events_are_requeued_unless_a_job_is_already_pending(billing_api: BillingApi) -> None:
    await billing_api.post_webhook({"event": "account.updated", "payload": {}}, event_id="evt_lost")
    await billing_api.post_webhook({"event": "account.updated", "payload": {}}, event_id="evt_waiting")
    lost, waiting = (event_id for event_id, _ in billing_api.recorded.dispatched)
    billing_api.recorded.dispatched.clear()
    await insert_job(billing_api, waiting, "todo")
    requeuer = requeuer_for(billing_api)

    assert await requeuer.requeue_stuck() == 0

    billing_api.clock.advance(timedelta(minutes=3))
    assert await requeuer.requeue_stuck() == 1
    assert billing_api.recorded.dispatched == [(lost, False)]


async def test_failed_events_are_requeued_until_their_attempts_run_out(billing_api: BillingApi) -> None:
    handler = Handler(billing_api)
    event_row_id = await failing_event(billing_api, handler)
    processor = limited_processor(billing_api)
    with pytest.raises(WebhookProcessingError):
        await processor.process(event_row_id)
    requeuer = requeuer_for(billing_api)
    billing_api.clock.advance(timedelta(minutes=3))
    async with billing_api.database.transaction() as session:
        await session.execute(text("UPDATE webhook_events SET updated_at = now() - interval '5 minutes'"))

    assert await requeuer.requeue_stuck() == 1
    assert billing_api.recorded.dispatched == [(event_row_id, False)]
    billing_api.recorded.dispatched.clear()
    for _ in range(MAX_ATTEMPTS - 1):
        await limited_processor_attempt(processor, event_row_id)
    async with billing_api.database.transaction() as session:
        await session.execute(text("UPDATE webhook_events SET updated_at = now() - interval '5 minutes'"))

    assert await requeuer.requeue_stuck() == 0


async def limited_processor_attempt(processor: WebhookProcessor, event_row_id: UUID) -> None:
    try:
        await processor.process(event_row_id)
    except WebhookProcessingError:
        return
