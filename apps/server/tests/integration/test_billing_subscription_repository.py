import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.integration.test_billing_repository import make_order, make_product, make_user

from motionile.core.clock import FrozenClock
from motionile.core.config import Settings
from motionile.core.ids import new_id
from motionile.core.resources import build_resources
from motionile.modules.billing.exceptions import LiveSubscriptionConflictError
from motionile.modules.billing.models import Product, ReconciliationRun
from motionile.modules.billing.records import (
    NewPayment,
    NewRefund,
    NewSubscription,
    ProductRecord,
    RunCounts,
    RunOutcome,
    SubscriptionRecord,
)
from motionile.modules.billing.repository import SqlBillingRepository
from motionile.modules.billing.states import (
    OrderStatus,
    PaymentRecordStatus,
    RefundStatus,
    RunStatus,
    SubscriptionStatus,
)
from motionile.modules.billing.transitions import transition_refund, transition_subscription
from motionile.modules.credits import CreditRef, CreditsService, GrantCommand, lot_for_reference

NOW = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)


async def make_plan(session: AsyncSession, plan_id: str | None = None) -> ProductRecord:
    product_id = new_id()
    session.add(
        Product(
            id=product_id,
            code=f"plan_{product_id.hex[:12]}",
            kind="subscription",
            plan_key=f"key_{product_id.hex[:8]}",
            interval="month",
            name="Pro",
            price_paise=99_900,
            currency="INR",
            credits_granted=500,
            razorpay_plan_id=plan_id or f"plan_{product_id.hex[:12]}",
            is_active=True,
            features=[],
        )
    )
    await session.flush()
    found = await SqlBillingRepository(session).product_by_id(product_id)
    assert found is not None
    return found


async def make_subscription(
    session: AsyncSession,
    user_id: UUID,
    product: ProductRecord,
    status: SubscriptionStatus = SubscriptionStatus.CREATED,
    **values: object,
) -> SubscriptionRecord:
    repository = SqlBillingRepository(session)
    created = await repository.insert_subscription(NewSubscription(new_id(), user_id, product.id, 120))
    if status is SubscriptionStatus.CREATED and not values:
        return created
    razorpay_id = values.pop("razorpay_subscription_id", f"sub_{created.id.hex[:12]}")
    ended = {"ended_at": NOW} if status in {SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED} else {}
    await repository.update_subscription(
        created.id, {"razorpay_subscription_id": razorpay_id, "status": status.value, **ended, **values}
    )
    reloaded = await repository.lock_subscription(created.id)
    assert reloaded is not None
    return reloaded


async def test_a_new_subscription_starts_created_without_a_provider_id(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    plan = await make_plan(rolled_back_session)

    created = await repository.insert_subscription(NewSubscription(new_id(), user_id, plan.id, 120))

    assert (created.status, created.razorpay_subscription_id, created.total_count, created.paid_count) == (
        SubscriptionStatus.CREATED,
        None,
        120,
        0,
    )
    assert (created.cancel_at_period_end, created.current_period_end, created.last_event_at) == (False, None, None)
    assert created.pending_product_id is None


async def test_subscription_lookups_include_the_owner(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    owner = await make_user(rolled_back_session)
    stranger = await make_user(rolled_back_session)
    plan = await make_plan(rolled_back_session)
    subscription = await make_subscription(
        rolled_back_session, owner, plan, SubscriptionStatus.ACTIVE, razorpay_subscription_id="sub_owned"
    )

    assert await repository.subscription_for_user(subscription.id, owner) == subscription
    assert await repository.subscription_for_user(subscription.id, stranger) is None
    assert await repository.lock_subscription_for_user(subscription.id, stranger) is None
    assert await repository.lock_subscription_by_razorpay_id_for_user("sub_owned", owner) == subscription
    assert await repository.lock_subscription_by_razorpay_id_for_user("sub_owned", stranger) is None
    assert await repository.lock_subscription_by_razorpay_id("sub_owned") == subscription
    assert await repository.live_subscription(owner) == subscription
    assert await repository.live_subscription(stranger) is None
    assert await repository.lock_live_subscription(owner) == subscription
    assert await repository.product_by_plan_id(plan.razorpay_plan_id or "") == plan
    assert await repository.product_by_plan_id("plan_missing") is None


async def test_only_one_live_subscription_per_user_and_the_transition_reports_the_conflict(
    rolled_back_session: AsyncSession,
) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    plan = await make_plan(rolled_back_session)
    first = await make_subscription(rolled_back_session, user_id, plan, SubscriptionStatus.ACTIVE)
    second = await make_subscription(
        rolled_back_session, user_id, plan, SubscriptionStatus.CREATED, razorpay_subscription_id="sub_second"
    )

    with pytest.raises(LiveSubscriptionConflictError):
        await transition_subscription(repository, second.id, SubscriptionStatus.CREATED, SubscriptionStatus.ACTIVE)

    reloaded = await repository.lock_subscription(second.id)
    assert reloaded is not None
    assert reloaded.status is SubscriptionStatus.CREATED
    assert await transition_subscription(
        repository, first.id, SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED, {"ended_at": NOW}
    )
    assert await transition_subscription(repository, second.id, SubscriptionStatus.CREATED, SubscriptionStatus.ACTIVE)


async def test_subscription_transitions_are_guarded_by_the_expected_status(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    plan = await make_plan(rolled_back_session)
    subscription = await make_subscription(rolled_back_session, user_id, plan, SubscriptionStatus.AUTHENTICATED)

    lost = await transition_subscription(
        repository, subscription.id, SubscriptionStatus.CREATED, SubscriptionStatus.AUTHENTICATED
    )
    won = await transition_subscription(
        repository,
        subscription.id,
        SubscriptionStatus.AUTHENTICATED,
        SubscriptionStatus.ACTIVE,
        {
            "paid_count": 1,
            "current_period_start": NOW,
            "current_period_end": NOW + timedelta(days=30),
            "last_event_at": NOW,
        },
    )

    assert (lost, won) == (False, True)
    reloaded = await repository.lock_subscription(subscription.id)
    assert reloaded is not None
    assert (reloaded.status, reloaded.paid_count, reloaded.last_event_at) == (SubscriptionStatus.ACTIVE, 1, NOW)
    await repository.update_subscription(subscription.id, {"cancel_at_period_end": True, "cancelled_at": NOW})
    flagged = await repository.lock_subscription(subscription.id)
    assert flagged is not None
    assert (flagged.cancel_at_period_end, flagged.cancelled_at) == (True, NOW)


async def test_an_ended_subscription_needs_an_end_time_and_does_not_block_a_new_one(
    rolled_back_session: AsyncSession,
) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    plan = await make_plan(rolled_back_session)
    subscription = await make_subscription(rolled_back_session, user_id, plan, SubscriptionStatus.ACTIVE)

    with pytest.raises(IntegrityError, match="ck_subscriptions_ended_consistent"):
        async with rolled_back_session.begin_nested():
            await repository.transition_subscription(
                subscription.id, SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED, {}
            )
    await transition_subscription(
        repository, subscription.id, SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED, {"ended_at": NOW}
    )

    assert await repository.live_subscription(user_id) is None
    replacement = await make_subscription(rolled_back_session, user_id, plan, SubscriptionStatus.ACTIVE)
    assert (await repository.live_subscription(user_id)) == replacement


async def test_due_cancellations_are_cancelling_live_subscriptions_past_their_period(
    rolled_back_session: AsyncSession,
) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    plan = await make_plan(rolled_back_session)
    due_ids: list[UUID] = []
    for status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.HALTED, SubscriptionStatus.PAUSED):
        subscription = await make_subscription(
            rolled_back_session,
            await make_user(rolled_back_session),
            plan,
            status,
            cancel_at_period_end=True,
            current_period_start=NOW - timedelta(days=31),
            current_period_end=NOW - timedelta(seconds=1),
        )
        due_ids.append(subscription.id)
    not_yet = await make_subscription(
        rolled_back_session,
        await make_user(rolled_back_session),
        plan,
        SubscriptionStatus.ACTIVE,
        cancel_at_period_end=True,
        current_period_start=NOW,
        current_period_end=NOW + timedelta(days=1),
    )
    not_cancelling = await make_subscription(
        rolled_back_session,
        await make_user(rolled_back_session),
        plan,
        SubscriptionStatus.ACTIVE,
        current_period_start=NOW - timedelta(days=31),
        current_period_end=NOW - timedelta(days=1),
    )

    page = await repository.due_cancellations(NOW, None, 100)
    first = await repository.due_cancellations(NOW, None, 2)
    rest = await repository.due_cancellations(NOW, first[-1].id, 2)

    found = {item.id for item in page}
    assert set(due_ids) <= found
    assert not_yet.id not in found
    assert not_cancelling.id not in found
    assert [item.id for item in first] == sorted(item.id for item in first)
    assert {item.id for item in first + rest} >= set(due_ids)


async def test_abandoned_and_unactivated_subscriptions_are_found_by_order_expiry_and_activity(
    rolled_back_session: AsyncSession,
) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    plan = await make_plan(rolled_back_session)
    product = await make_product(rolled_back_session)
    expired_user = await make_user(rolled_back_session)
    expired = await make_subscription(rolled_back_session, expired_user, plan, razorpay_subscription_id="sub_expired")
    fresh_user = await make_user(rolled_back_session)
    fresh = await make_subscription(rolled_back_session, fresh_user, plan, razorpay_subscription_id="sub_fresh")
    unsent = await make_subscription(rolled_back_session, await make_user(rolled_back_session), plan)
    active_user = await make_user(rolled_back_session)
    touched = await make_subscription(
        rolled_back_session, active_user, plan, SubscriptionStatus.CREATED, last_event_at=NOW
    )
    for owner, subscription, expires in (
        (expired_user, expired, NOW - timedelta(minutes=1)),
        (fresh_user, fresh, NOW + timedelta(hours=1)),
        (active_user, touched, NOW - timedelta(minutes=1)),
    ):
        order_id = await make_order(rolled_back_session, owner, product, status=OrderStatus.PENDING)
        await rolled_back_session.execute(
            text(
                "UPDATE orders SET kind = 'subscription', subscription_id = :sub, expires_at = :expires WHERE id = :id"
            ),
            {"sub": subscription.id, "expires": expires, "id": order_id},
        )

    abandoned = {item.id for item in await repository.abandoned_subscriptions(NOW, None, 100)}
    unactivated = {item.id for item in await repository.unactivated_subscriptions(None, 100)}

    assert expired.id in abandoned
    assert fresh.id not in abandoned
    assert touched.id not in abandoned
    assert {expired.id, fresh.id, touched.id} <= unactivated
    assert unsent.id not in unactivated


async def test_live_subscriptions_pages_in_id_order(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    plan = await make_plan(rolled_back_session)
    created: list[UUID] = []
    for _ in range(3):
        created.append(
            (
                await make_subscription(
                    rolled_back_session, await make_user(rolled_back_session), plan, SubscriptionStatus.ACTIVE
                )
            ).id
        )
    await make_subscription(rolled_back_session, await make_user(rolled_back_session), plan)

    pages: list[UUID] = []
    after: UUID | None = None
    while True:
        page = await repository.live_subscriptions(after, 2)
        pages.extend(item.id for item in page)
        if len(page) < 2:
            break
        after = page[-1].id

    assert [item for item in pages if item in created] == sorted(created)
    assert all(
        item.status is not SubscriptionStatus.CREATED for item in await repository.live_subscriptions(None, 1000)
    )


async def test_subscription_payments_are_counted_and_the_subscription_order_is_found(
    rolled_back_session: AsyncSession,
) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    plan = await make_plan(rolled_back_session)
    subscription = await make_subscription(rolled_back_session, user_id, plan, SubscriptionStatus.ACTIVE)
    order_id = await make_order(rolled_back_session, user_id, await make_product(rolled_back_session))
    await rolled_back_session.execute(
        text("UPDATE orders SET kind = 'subscription', subscription_id = :sub WHERE id = :id"),
        {"sub": subscription.id, "id": order_id},
    )
    assert await repository.subscription_payment_count(subscription.id) == 0

    renewal = await repository.insert_payment(
        NewPayment(
            id=new_id(),
            order_id=None,
            subscription_id=subscription.id,
            user_id=user_id,
            razorpay_payment_id="pay_renewal",
            amount_paise=99_900,
            currency="INR",
            status=PaymentRecordStatus.CAPTURED,
            captured_at=NOW,
        )
    )

    assert (renewal.order_id, renewal.subscription_id) == (None, subscription.id)
    assert await repository.subscription_payment_count(subscription.id) == 1
    order = await repository.lock_subscription_order(subscription.id)
    assert order is not None
    assert (order.id, order.subscription_id, order.kind) == (order_id, subscription.id, "subscription")
    assert await repository.lock_subscription_order(new_id()) is None


async def make_payment(
    session: AsyncSession, user_id: UUID, razorpay_id: str, *, amount: int = 10_000, created_at: datetime = NOW
) -> UUID:
    repository = SqlBillingRepository(session)
    product = await make_product(session)
    order_id = await make_order(session, user_id, product, status=OrderStatus.PAID)
    payment = await repository.insert_payment(
        NewPayment(
            id=new_id(),
            order_id=order_id,
            user_id=user_id,
            razorpay_payment_id=razorpay_id,
            amount_paise=amount,
            currency="INR",
            status=PaymentRecordStatus.CAPTURED,
            captured_at=created_at,
        )
    )
    await session.execute(
        text("UPDATE payments SET created_at = :at WHERE id = :id"), {"at": created_at, "id": payment.id}
    )
    return payment.id


async def test_refunds_are_inserted_pending_and_transition_once(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    admin_id = await make_user(rolled_back_session, "Admin")
    payment_id = await make_payment(rolled_back_session, user_id, "pay_refunds")

    refund = await repository.insert_refund(NewRefund(new_id(), payment_id, 4_000, "Duplicate", admin_id, "k-dup"))

    assert (refund.status, refund.credits_clawed_back, refund.razorpay_refund_id, refund.initiated_by) == (
        RefundStatus.PENDING,
        0,
        None,
        admin_id,
    )
    await repository.update_refund(refund.id, {"razorpay_refund_id": "rfnd_1"})
    assert await repository.refund_by_razorpay_id("rfnd_1") == await repository.refund_by_id(refund.id)
    assert await repository.refund_by_razorpay_id("rfnd_missing") is None
    assert await repository.pending_refund_totals([payment_id]) == {payment_id: 4_000}
    assert await repository.pending_refund_totals([]) == {}
    assert await transition_refund(
        repository,
        refund.id,
        RefundStatus.PENDING,
        RefundStatus.PROCESSED,
        {"processed_at": NOW, "credits_clawed_back": 7},
    )
    assert not await repository.transition_refund(refund.id, RefundStatus.PENDING, RefundStatus.FAILED, {})
    assert await repository.pending_refund_totals([payment_id]) == {}
    assert await repository.clawed_back_total(payment_id) == 7
    locked = await repository.lock_refund(refund.id)
    assert locked is not None
    assert (locked.status, locked.processed_at, locked.credits_clawed_back) == (RefundStatus.PROCESSED, NOW, 7)


async def test_refund_rules_are_enforced_by_the_schema(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    payment_id = await make_payment(rolled_back_session, user_id, "pay_rules")
    first = await repository.insert_refund(NewRefund(new_id(), payment_id, 100, "one", None, "k-one"))
    second = await repository.insert_refund(NewRefund(new_id(), payment_id, 100, "two", None, "k-two"))
    await repository.update_refund(first.id, {"razorpay_refund_id": "rfnd_same"})

    with pytest.raises(IntegrityError, match="uq_refunds_razorpay_refund_id"):
        async with rolled_back_session.begin_nested():
            await repository.update_refund(second.id, {"razorpay_refund_id": "rfnd_same"})
    with pytest.raises(IntegrityError, match="ck_refunds_amount_paise_positive"):
        async with rolled_back_session.begin_nested():
            await repository.insert_refund(NewRefund(new_id(), payment_id, 0, "zero", None, "k-zero"))
    with pytest.raises(IntegrityError, match="ck_refunds_processed_consistent"):
        async with rolled_back_session.begin_nested():
            await repository.transition_refund(second.id, RefundStatus.PENDING, RefundStatus.PROCESSED, {})


async def test_the_payment_row_lock_orders_competing_refund_checks(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    payment_id = await make_payment(rolled_back_session, user_id, "pay_lock")

    locked = await repository.lock_payment(payment_id)
    plain = await repository.payment_by_id(payment_id)

    assert locked is not None
    assert locked == plain
    assert await repository.lock_payment(new_id()) is None


async def test_captured_payments_are_listed_by_window_in_id_order(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    user_id = await make_user(rolled_back_session)
    window_start = datetime(2026, 1, 5, tzinfo=UTC)
    inside = [
        await make_payment(
            rolled_back_session, user_id, f"pay_in_{index}", created_at=window_start + timedelta(hours=index)
        )
        for index in range(3)
    ]
    await make_payment(rolled_back_session, user_id, "pay_before", created_at=window_start - timedelta(seconds=1))
    await make_payment(rolled_back_session, user_id, "pay_end", created_at=window_start + timedelta(days=1))
    failed = await make_payment(rolled_back_session, user_id, "pay_failed", created_at=window_start)
    await rolled_back_session.execute(text("UPDATE payments SET status = 'failed' WHERE id = :id"), {"id": failed})

    first = await repository.captured_payments_between(window_start, window_start + timedelta(days=1), None, 2)
    second = await repository.captured_payments_between(window_start, window_start + timedelta(days=1), first[-1].id, 2)

    assert [payment.id for payment in first + second] == sorted(inside)
    assert failed not in {payment.id for payment in first + second}


async def test_settlement_runs_are_claimed_once_per_day_and_resumed_after_a_failure(
    rolled_back_session: AsyncSession,
) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    day = datetime(2026, 1, 6, tzinfo=UTC)
    stale_before = NOW - timedelta(hours=1)

    claim = await repository.claim_settlement_run(day, day + timedelta(days=1), NOW, stale_before)
    assert claim is not None
    assert claim.resumed is False
    assert await repository.claim_settlement_run(day, day + timedelta(days=1), NOW, stale_before) is None
    await repository.finish_run(
        claim.run_id,
        RunOutcome(RunStatus.FAILED, RunCounts(checked=3), NOW, error="boom"),
    )
    resumed = await repository.claim_settlement_run(
        day, day + timedelta(days=1), NOW + timedelta(minutes=5), stale_before
    )
    assert resumed is not None
    assert (resumed.run_id, resumed.resumed) == (claim.run_id, True)
    row = await rolled_back_session.scalar(select(ReconciliationRun).where(ReconciliationRun.id == claim.run_id))
    assert row is not None
    await rolled_back_session.refresh(row)
    assert (row.status, row.error, row.finished_at, row.checked_count) == ("running", None, None, 0)
    await repository.finish_run(
        claim.run_id,
        RunOutcome(
            RunStatus.COMPLETED,
            RunCounts(checked=5, mismatch=1),
            NOW,
            summary={"missing": 1},
            report_storage_key="billing/reconciliation/settlement/2026-01-06.json",
        ),
    )
    await rolled_back_session.refresh(row)
    assert (row.status, row.mismatch_count, row.summary, row.report_storage_key) == (
        "completed",
        1,
        {"missing": 1},
        "billing/reconciliation/settlement/2026-01-06.json",
    )
    assert await repository.claim_settlement_run(day, day + timedelta(days=1), NOW, stale_before) is None
    other_day = await repository.claim_settlement_run(
        day + timedelta(days=1), day + timedelta(days=2), NOW, stale_before
    )
    assert other_day is not None


async def test_a_run_that_has_been_running_too_long_is_taken_over(rolled_back_session: AsyncSession) -> None:
    repository = SqlBillingRepository(rolled_back_session)
    day = datetime(2026, 1, 7, tzinfo=UTC)
    claim = await repository.claim_settlement_run(
        day, day + timedelta(days=1), NOW - timedelta(hours=3), NOW - timedelta(hours=4)
    )
    assert claim is not None

    fresh = await repository.claim_settlement_run(day, day + timedelta(days=1), NOW, NOW - timedelta(hours=4))
    taken = await repository.claim_settlement_run(day, day + timedelta(days=1), NOW, NOW - timedelta(hours=1))

    assert fresh is None
    assert taken is not None
    assert (taken.run_id, taken.resumed) == (claim.run_id, True)


async def test_the_credit_lot_of_a_payment_is_found_by_its_reference(
    rolled_back_session: AsyncSession, settings: Settings
) -> None:
    user_id = await make_user(rolled_back_session)
    payment_id = await make_payment(rolled_back_session, user_id, "pay_lot")
    service = CreditsService(FrozenClock(NOW), settings.billing)
    grant = await service.grant(
        rolled_back_session,
        GrantCommand(
            user_id=user_id,
            amount=100,
            source="purchase",
            key=f"payment:{payment_id}",
            ref=CreditRef("payment", payment_id),
        ),
    )

    lot = await lot_for_reference(rolled_back_session, CreditRef("payment", payment_id))

    assert lot is not None
    assert (lot.id, lot.user_id, lot.amount, lot.remaining, lot.source) == (grant.lot_id, user_id, 100, 100, "purchase")
    assert await lot_for_reference(rolled_back_session, CreditRef("payment", new_id())) is None
    assert await lot_for_reference(rolled_back_session, CreditRef("refund", payment_id)) is None


async def test_concurrent_claims_for_one_day_produce_a_single_run(settings: Settings) -> None:
    resources = build_resources(settings, application_name="motionile-claims")
    day = datetime(2026, 1, 8, tzinfo=UTC)

    async def claim() -> object:
        async with resources.database.transaction() as session:
            return await SqlBillingRepository(session).claim_settlement_run(
                day, day + timedelta(days=1), NOW, NOW - timedelta(hours=1)
            )

    try:
        results = await asyncio.gather(*[claim() for _ in range(4)])
        assert len([item for item in results if item is not None]) == 1
    finally:
        async with resources.database.transaction() as session:
            await session.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
            await session.execute(
                text("DELETE FROM billing_reconciliation_runs WHERE period_start = :day"), {"day": day}
            )
        await resources.aclose()
