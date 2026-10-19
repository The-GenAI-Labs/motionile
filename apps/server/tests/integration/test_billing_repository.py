from datetime import UTC, datetime, timedelta
from typing import TypedDict, Unpack
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.modules.billing.models import Order, Payment, Product, ReconciliationRun, Refund
from motionile.modules.billing.records import (
    NewOrder,
    NewPayment,
    NewWebhookEvent,
    ProductRecord,
    RequeueQuery,
    RunCounts,
    RunOutcome,
    SampleProductSpec,
)
from motionile.modules.billing.repository import SqlBillingRepository
from motionile.modules.billing.states import (
    OrderStatus,
    PaymentRecordStatus,
    RunStatus,
    WebhookEventStatus,
)
from motionile.modules.billing.transitions import transition_event, transition_order, transition_payment
from motionile.modules.users import User

NOW = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
PROCESS_TASK = "motionile:billing.process_webhook_event"


async def make_user(session: AsyncSession, name: str | None = "Repository") -> UUID:
    user_id = new_id()
    session.add(User(id=user_id, name=name, status="active"))
    await session.flush()
    return user_id


async def make_product(
    session: AsyncSession, *, code: str | None = None, active: bool = True, sort_order: int = 0
) -> ProductRecord:
    product_id = new_id()
    session.add(
        Product(
            id=product_id,
            code=code or f"pack_{product_id.hex[:12]}",
            kind="credit_pack",
            name="Starter",
            price_paise=19_900,
            currency="INR",
            credits_granted=100,
            is_active=active,
            sort_order=sort_order,
            features=["100 credits", 7],
            version=3,
        )
    )
    await session.flush()
    found = await SqlBillingRepository(session).product_by_id(product_id)
    assert found is not None
    return found


class OrderOptions(TypedDict, total=False):
    key: str
    created_at: datetime
    status: OrderStatus
    razorpay_order_id: str


async def make_order(
    session: AsyncSession, user_id: UUID, product: ProductRecord, **options: Unpack[OrderOptions]
) -> UUID:
    order_id = new_id()
    created_at = options.get("created_at")
    status = options.get("status", OrderStatus.CREATED)
    session.add(
        Order(
            id=order_id,
            user_id=user_id,
            product_id=product.id,
            product_version=product.version,
            kind=product.kind,
            amount_paise=product.price_paise,
            currency=product.currency,
            credits_granted=product.credits_granted,
            status=status.value,
            paid_at=NOW if status is OrderStatus.PAID else None,
            razorpay_order_id=options.get("razorpay_order_id"),
            receipt=str(order_id),
            idempotency_key=options.get("key", f"key-{order_id.hex}"),
            expires_at=NOW + timedelta(hours=2),
            **({"created_at": created_at} if created_at is not None else {}),
        )
    )
    await session.flush()
    return order_id


async def test_products_are_listed_active_only_in_kind_then_sort_order(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    second = await make_product(rolled_back_session, sort_order=20)
    first = await make_product(rolled_back_session, sort_order=10)
    hidden = await make_product(rolled_back_session, active=False)

    listed = [
        product.id for product in await repository.active_products() if product.id in {second.id, first.id, hidden.id}
    ]

    assert listed == [first.id, second.id]
    assert first.features == ("100 credits",)
    assert first.version == 3
    assert (await repository.product_by_code(first.code)) == first
    assert await repository.product_by_code("missing") is None
    assert await repository.product_by_id(new_id()) is None


async def test_inserting_an_order_snapshots_the_product_and_sets_the_receipt(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    product = await make_product(rolled_back_session)
    order_id = new_id()

    created = await repository.insert_order(NewOrder(order_id, user_id, product, "key-1", NOW + timedelta(hours=2)))

    assert created is not None
    assert (created.id, created.receipt, created.status) == (order_id, str(order_id), OrderStatus.CREATED)
    assert (created.amount_paise, created.currency, created.credits_granted, created.product_version) == (
        19_900,
        "INR",
        100,
        3,
    )
    assert (created.kind, created.razorpay_order_id, created.paid_at, created.flagged_at) == (
        "credit_pack",
        None,
        None,
        None,
    )
    assert created.expires_at == NOW + timedelta(hours=2)
    assert await repository.order_for_key(user_id, "key-1") == created


async def test_the_idempotency_key_is_unique_per_user_without_raising(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    first_user = await make_user(rolled_back_session)
    second_user = await make_user(rolled_back_session)
    product = await make_product(rolled_back_session)
    expires = NOW + timedelta(hours=2)
    assert await repository.insert_order(NewOrder(new_id(), first_user, product, "same", expires)) is not None

    assert await repository.insert_order(NewOrder(new_id(), first_user, product, "same", expires)) is None
    assert await repository.insert_order(NewOrder(new_id(), second_user, product, "same", expires)) is not None
    assert await repository.order_for_key(first_user, "other") is None


async def test_order_lookups_always_include_the_owner(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    owner = await make_user(rolled_back_session)
    stranger = await make_user(rolled_back_session)
    product = await make_product(rolled_back_session)
    order_id = await make_order(
        rolled_back_session, owner, product, status=OrderStatus.PENDING, razorpay_order_id="order_a"
    )

    view = await repository.order_view(order_id, owner)

    assert view is not None
    assert (view.product_code, view.product_name, view.order.id) == (product.code, "Starter", order_id)
    assert await repository.order_view(order_id, stranger) is None
    assert await repository.order_by_razorpay_id_for_user("order_a", owner) is not None
    assert await repository.order_by_razorpay_id_for_user("order_a", stranger) is None
    locked = await repository.lock_order_by_razorpay_id("order_a")
    assert locked is not None
    assert locked.id == order_id
    assert (await repository.lock_order(order_id)) == locked
    assert await repository.lock_order(new_id()) is None


async def test_order_transitions_are_guarded_by_the_expected_status(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    product = await make_product(rolled_back_session)
    order_id = await make_order(rolled_back_session, user_id, product)

    assert not await transition_order(repository, order_id, OrderStatus.PENDING, OrderStatus.EXPIRED)
    untouched = await repository.lock_order(order_id)
    assert untouched is not None
    assert untouched.status is OrderStatus.CREATED
    assert await transition_order(
        repository, order_id, OrderStatus.CREATED, OrderStatus.PENDING, {"razorpay_order_id": "order_x"}
    )
    paid_at = NOW + timedelta(minutes=5)
    assert await transition_order(repository, order_id, OrderStatus.PENDING, OrderStatus.PAID, {"paid_at": paid_at})
    paid = await repository.lock_order(order_id)
    assert paid is not None
    assert (paid.status, paid.razorpay_order_id, paid.paid_at) == (OrderStatus.PAID, "order_x", paid_at)
    assert not await transition_order(repository, order_id, OrderStatus.PENDING, OrderStatus.PAID, {"paid_at": paid_at})


async def test_flagging_keeps_the_first_reason(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    order_id = await make_order(rolled_back_session, user_id, await make_product(rolled_back_session))

    assert await repository.flag_order(order_id, "amount_mismatch", NOW)
    assert not await repository.flag_order(order_id, "duplicate_payment", NOW + timedelta(hours=1))

    flagged = await repository.lock_order(order_id)
    assert flagged is not None
    assert (flagged.flag_reason, flagged.flagged_at) == ("amount_mismatch", NOW)


async def test_a_flag_reason_outside_the_documented_set_is_rejected(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    order_id = await make_order(rolled_back_session, user_id, await make_product(rolled_back_session))

    with pytest.raises(IntegrityError, match="ck_orders_flag_reason"):
        async with rolled_back_session.begin_nested():
            await repository.flag_order(order_id, "other", NOW)
    assert await repository.flag_order(order_id, "duplicate_payment", NOW)


async def test_reconciliation_candidates_are_old_unflagged_open_orders_in_keyset_order(
    rolled_back_session: AsyncSession,
) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    product = await make_product(rolled_back_session)
    old = NOW - timedelta(hours=1)
    ids = [
        await make_order(rolled_back_session, user_id, product, created_at=old + timedelta(minutes=index))
        for index in range(5)
    ]
    pending = await make_order(
        rolled_back_session, user_id, product, status=OrderStatus.PENDING, created_at=old - timedelta(minutes=1)
    )
    await make_order(rolled_back_session, user_id, product, status=OrderStatus.PAID, created_at=old)
    await make_order(rolled_back_session, user_id, product, status=OrderStatus.EXPIRED, created_at=old)
    flagged = await make_order(rolled_back_session, user_id, product, created_at=old)
    await repository.flag_order(flagged, "amount_mismatch", NOW)
    await make_order(rolled_back_session, user_id, product, created_at=NOW)

    first = await repository.reconcilable_orders(NOW - timedelta(minutes=30), None, 4)
    second = await repository.reconcilable_orders(
        NOW - timedelta(minutes=30), Cursor(first[-1].created_at, first[-1].id), 4
    )

    assert [order.id for order in first] == [pending, ids[0], ids[1], ids[2]]
    assert [order.id for order in second] == [ids[3], ids[4]]


async def test_payments_are_unique_by_provider_id_and_transition_with_a_guard(
    rolled_back_session: AsyncSession,
) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    order_id = await make_order(rolled_back_session, user_id, await make_product(rolled_back_session))
    payment = await repository.insert_payment(
        NewPayment(
            new_id(),
            order_id,
            user_id,
            "pay_1",
            19_900,
            "INR",
            PaymentRecordStatus.AUTHORIZED,
            method="upi",
            fee_paise=398,
            tax_paise=71,
        )
    )

    assert (payment.status, payment.credits_granted, payment.refunded_paise, payment.method) == (
        PaymentRecordStatus.AUTHORIZED,
        0,
        0,
        "upi",
    )
    assert await repository.payment_by_razorpay_id("pay_1") == payment
    assert await repository.payment_by_razorpay_id("pay_2") is None
    captured_at = NOW
    assert await transition_payment(
        repository,
        payment.id,
        PaymentRecordStatus.AUTHORIZED,
        PaymentRecordStatus.CAPTURED,
        {"captured_at": captured_at},
    )
    assert not await transition_payment(
        repository, payment.id, PaymentRecordStatus.AUTHORIZED, PaymentRecordStatus.FAILED
    )
    await repository.set_payment_credits(payment.id, 100)
    stored = await repository.payment_by_razorpay_id("pay_1")
    assert stored is not None
    assert (stored.status, stored.captured_at, stored.credits_granted) == (
        PaymentRecordStatus.CAPTURED,
        captured_at,
        100,
    )
    with pytest.raises(IntegrityError, match="uq_payments_razorpay_payment_id"):
        async with rolled_back_session.begin_nested():
            await repository.insert_payment(
                NewPayment(new_id(), order_id, user_id, "pay_1", 1, "INR", PaymentRecordStatus.FAILED)
            )


def new_event(event_id: str = "evt_1", *, received_at: datetime = NOW) -> NewWebhookEvent:
    return NewWebhookEvent(
        id=new_id(),
        provider="razorpay",
        event_id=event_id,
        event_type="payment.captured",
        event_created_at=NOW,
        payload={"event": "payment.captured", "payload": {"payment": {"entity": {"id": "pay_1"}}}},
        received_at=received_at,
    )


async def test_events_deduplicate_on_provider_and_event_id(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    event = new_event()

    assert await repository.insert_event(event)
    assert not await repository.insert_event(new_event())

    stored = await repository.event_by_provider_id("razorpay", "evt_1")
    assert stored is not None
    assert (stored.id, stored.status, stored.attempts, stored.event_created_at) == (
        event.id,
        WebhookEventStatus.RECEIVED,
        0,
        NOW,
    )
    assert stored.payload["payload"]["payment"]["entity"]["id"] == "pay_1"
    assert await repository.event_by_provider_id("razorpay", "evt_2") is None
    assert await repository.event_by_provider_id("other", "evt_1") is None


async def test_event_transitions_are_guarded_and_write_their_columns(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    event = new_event()
    await repository.insert_event(event)

    assert await transition_event(
        repository, event.id, WebhookEventStatus.RECEIVED, WebhookEventStatus.PROCESSING, {"attempts": 1}
    )
    assert not await transition_event(
        repository, event.id, WebhookEventStatus.RECEIVED, WebhookEventStatus.PROCESSING, {"attempts": 2}
    )
    assert await transition_event(
        repository,
        event.id,
        WebhookEventStatus.PROCESSING,
        WebhookEventStatus.FAILED,
        {"last_error": "RuntimeError: boom"},
    )
    stored = await repository.lock_event(event.id)
    assert stored is not None
    assert (stored.status, stored.attempts, stored.last_error) == (WebhookEventStatus.FAILED, 1, "RuntimeError: boom")
    assert await repository.lock_event(new_id()) is None


async def insert_job(session: AsyncSession, event_row_id: UUID, status: str) -> None:
    await session.execute(
        text(
            "INSERT INTO procrastinate_jobs (queue_name, task_name, args, status) "
            "VALUES ('billing', :task, CAST(:args AS jsonb), CAST(:status AS procrastinate_job_status))"
        ),
        {"task": PROCESS_TASK, "args": f'{{"event_row_id": "{event_row_id}", "force": false}}', "status": status},
    )


async def test_requeue_candidates_skip_events_that_already_have_a_pending_job(
    rolled_back_session: AsyncSession,
) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    stale = NOW - timedelta(minutes=10)
    stuck, queued, fresh, done, failed_retryable, failed_exhausted, failed_queued = (
        new_event(f"evt_{name}", received_at=stale if name != "fresh" else NOW)
        for name in ("stuck", "queued", "fresh", "done", "retryable", "exhausted", "failed_queued")
    )
    for event in (stuck, queued, fresh, done, failed_retryable, failed_exhausted, failed_queued):
        await repository.insert_event(event)
    await insert_job(rolled_back_session, queued.id, "todo")
    await insert_job(rolled_back_session, failed_queued.id, "doing")
    await insert_job(rolled_back_session, stuck.id, "succeeded")
    for event, attempts in ((failed_retryable, 2), (failed_exhausted, 10), (failed_queued, 2)):
        await transition_event(
            repository, event.id, WebhookEventStatus.RECEIVED, WebhookEventStatus.PROCESSING, {"attempts": attempts}
        )
        await transition_event(repository, event.id, WebhookEventStatus.PROCESSING, WebhookEventStatus.FAILED)
    await transition_event(repository, done.id, WebhookEventStatus.RECEIVED, WebhookEventStatus.PROCESSING)
    await transition_event(repository, done.id, WebhookEventStatus.PROCESSING, WebhookEventStatus.PROCESSED)
    await rolled_back_session.execute(text("UPDATE webhook_events SET updated_at = :old"), {"old": stale})

    found = await repository.requeue_candidates(
        RequeueQuery(
            provider="razorpay",
            stale_before=NOW - timedelta(minutes=2),
            max_attempts=10,
            task_name=PROCESS_TASK,
            limit=50,
        )
    )

    assert set(found) == {stuck.id, failed_retryable.id}


async def test_reconciliation_runs_start_running_and_finish_once(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    run_id = new_id()
    await repository.start_run(run_id, "pending_orders", NOW)
    outcome = RunOutcome(
        status=RunStatus.COMPLETED,
        counts=RunCounts(checked=4, repaired=2, mismatch=1),
        finished_at=NOW + timedelta(seconds=3),
        summary={"settled": 1, "expired": 1, "errors": 0},
    )

    assert await repository.finish_run(run_id, outcome)
    assert not await repository.finish_run(run_id, outcome)

    run = await rolled_back_session.scalar(select(ReconciliationRun).where(ReconciliationRun.id == run_id))
    assert run is not None
    await rolled_back_session.refresh(run)
    assert (run.type, run.status, run.checked_count, run.repaired_count, run.mismatch_count) == (
        "pending_orders",
        "completed",
        4,
        2,
        1,
    )
    assert run.summary == {"settled": 1, "expired": 1, "errors": 0}
    assert run.finished_at == NOW + timedelta(seconds=3)


async def test_a_failed_run_keeps_a_truncated_error(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    run_id = new_id()
    await repository.start_run(run_id, "pending_orders", NOW)

    await repository.finish_run(run_id, RunOutcome(RunStatus.FAILED, RunCounts(), NOW, error="x" * 5_000))

    run = await rolled_back_session.scalar(select(ReconciliationRun).where(ReconciliationRun.id == run_id))
    assert run is not None
    await rolled_back_session.refresh(run)
    assert run.status == "failed"
    assert run.error is not None
    assert len(run.error) == 2_000


async def test_the_timeline_merges_orders_payments_and_refunds_newest_first_with_keyset_paging(
    rolled_back_session: AsyncSession,
) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    stranger = await make_user(rolled_back_session)
    product = await make_product(rolled_back_session)
    base = NOW - timedelta(days=1)
    order_id = await make_order(
        rolled_back_session, user_id, product, status=OrderStatus.PENDING, created_at=base, razorpay_order_id="order_t"
    )
    await make_order(rolled_back_session, user_id, product, created_at=base + timedelta(minutes=1))
    payment_id = new_id()
    rolled_back_session.add(
        Payment(
            id=payment_id,
            order_id=order_id,
            user_id=user_id,
            razorpay_payment_id="pay_t",
            amount_paise=19_900,
            currency="INR",
            status="captured",
            credits_granted=100,
            created_at=base + timedelta(minutes=2),
        )
    )
    await rolled_back_session.flush()
    refund_id = new_id()
    rolled_back_session.add(
        Refund(
            id=refund_id,
            payment_id=payment_id,
            amount_paise=5_000,
            status="pending",
            reason="requested",
            idempotency_key="k-history",
            created_at=base + timedelta(minutes=3),
        )
    )
    stranger_order = await make_order(rolled_back_session, stranger, product, status=OrderStatus.PENDING)
    await rolled_back_session.flush()

    page = await repository.history(user_id, None, 10)

    assert [(row.kind, row.id) for row in page] == [
        ("refund", refund_id),
        ("payment", payment_id),
        ("order", order_id),
    ]
    refund, payment, order = page
    assert (refund.title, refund.credits_granted, refund.order_id, refund.payment_id, refund.currency) == (
        "Refund for Starter",
        None,
        order_id,
        payment_id,
        "INR",
    )
    assert (payment.title, payment.credits_granted, payment.order_id, payment.payment_id) == (
        "Payment for Starter",
        100,
        order_id,
        payment_id,
    )
    assert (order.title, order.status, order.amount_paise, order.payment_id) == ("Starter", "pending", 19_900, None)
    assert stranger_order not in {row.id for row in page}
    first = await repository.history(user_id, None, 1)
    second = await repository.history(user_id, Cursor(first[0].created_at, first[0].id), 1)
    assert [row.id for row in first] == [refund_id, payment_id]
    assert [row.id for row in second] == [payment_id, order_id]


async def test_saving_sample_products_is_an_idempotent_upsert_that_never_touches_prices(
    rolled_back_session: AsyncSession,
) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    spec = SampleProductSpec(
        code="pack_sample",
        kind="credit_pack",
        name="Sample",
        description="first",
        price_paise=19_900,
        credits_granted=100,
        sort_order=1,
        features=("a",),
    )
    created = await repository.save_sample_product(spec)
    renamed = await repository.save_sample_product(
        SampleProductSpec(
            code="pack_sample",
            kind="credit_pack",
            name="Renamed",
            description="second",
            price_paise=1,
            credits_granted=1,
            sort_order=2,
            features=("b",),
        )
    )

    assert created is not None
    assert renamed is not None
    assert (renamed.id, renamed.name, renamed.description, renamed.sort_order, renamed.features) == (
        created.id,
        "Renamed",
        "second",
        2,
        ("b",),
    )
    assert (renamed.price_paise, renamed.credits_granted, renamed.is_sample, renamed.is_active) == (
        19_900,
        100,
        True,
        True,
    )


async def test_a_non_sample_product_is_left_alone_by_the_sample_upsert(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    real = await make_product(rolled_back_session, code="pack_real")

    result = await repository.save_sample_product(
        SampleProductSpec("pack_real", "credit_pack", "Hijack", "x", 1, 1, 1, ())
    )

    assert result is None
    assert await repository.product_by_id(real.id) == real


async def test_subscription_samples_start_inactive_and_activate_with_their_plan(
    rolled_back_session: AsyncSession,
) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    spec = SampleProductSpec(
        code="pro_sample",
        kind="subscription",
        name="Pro",
        description="plan",
        price_paise=49_900,
        credits_granted=300,
        sort_order=1,
        features=(),
        interval="month",
        plan_key="pro_sample",
    )
    plan = await repository.save_sample_product(spec)

    assert plan is not None
    assert (plan.is_active, plan.razorpay_plan_id) == (False, None)
    assert await repository.activate_product_with_plan(plan.id, "plan_1")
    assert await repository.activate_product_with_plan(plan.id, "plan_1")
    assert not await repository.activate_product_with_plan(plan.id, "plan_2")
    activated = await repository.product_by_id(plan.id)
    assert activated is not None
    assert (activated.is_active, activated.razorpay_plan_id) == (True, "plan_1")
