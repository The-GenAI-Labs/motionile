import asyncio

from sqlalchemy import select
from tests.integration.billing_support import SUBSCRIPTION_CREDITS, BillingApi, create_product

from motionile.core.ids import new_id
from motionile.modules.billing.exceptions import ProductImmutableError
from motionile.modules.billing.models import Order, Product
from motionile.modules.billing.services.admin_products import UpdateProductCommand

NEW_PRICE = 29_900


async def test_a_price_change_racing_an_order_never_leaves_a_stale_snapshot(billing_api: BillingApi) -> None:
    for _ in range(6):
        code = f"pack_{new_id().hex[:12]}"
        product_id = await create_product(billing_api.database, code)

        results = await asyncio.gather(
            billing_api.services.orders.create(billing_api.primary_id, code, billing_api.keys()),
            billing_api.services.admin.products.update(
                None, UpdateProductCommand(product_id=product_id, version=1, changes={"price_paise": NEW_PRICE})
            ),
            return_exceptions=True,
        )

        order_result, patch_result = results
        assert not isinstance(order_result, BaseException), order_result
        assert isinstance(patch_result, ProductImmutableError) or not isinstance(patch_result, BaseException)
        async with billing_api.database.transaction() as session:
            product = await session.scalar(select(Product).where(Product.id == product_id))
            orders = list(await session.scalars(select(Order).where(Order.product_id == product_id)))
        assert product is not None
        assert [order.amount_paise for order in orders] == [product.price_paise]
        assert order_result.amount_paise == product.price_paise


async def test_two_concurrent_requests_with_one_key_create_one_provider_order(billing_api: BillingApi) -> None:
    key = billing_api.keys()

    first, second = await asyncio.gather(
        billing_api.services.orders.create(billing_api.primary_id, billing_api.pack_code, key),
        billing_api.services.orders.create(billing_api.primary_id, billing_api.pack_code, key),
    )

    assert first.razorpay_order_id == second.razorpay_order_id
    assert await billing_api.remote_order_count() == 1


async def test_two_concurrent_requests_with_one_key_create_one_provider_subscription(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    key = billing_api.keys()

    first, second = await asyncio.gather(
        billing_api.services.subscriptions.checkout.create(billing_api.primary_id, code, key),
        billing_api.services.subscriptions.checkout.create(billing_api.primary_id, code, key),
    )

    assert first.razorpay_subscription_id == second.razorpay_subscription_id
    key_name = billing_api.resources.redis_store.keys.key("fake_razorpay", "sequence", "sub")
    assert int(await billing_api.resources.redis_store.get(key_name) or 0) == 1


async def test_two_simultaneous_identical_charge_events_grant_once(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    started = await billing_api.activate_subscription(code)
    remote_id = started["razorpaySubscriptionId"]
    moved = await billing_api.transition(remote_id, "charged", emit=False)
    for _ in range(2):
        await billing_api.deliver(
            event="subscription.charged",
            subscriptionId=remote_id,
            paymentId=moved["razorpayPaymentId"],
            eventId=f"evt_{new_id().hex}",
        )
    queued = [event_row_id for event_row_id, _ in billing_api.recorded.dispatched]
    billing_api.recorded.dispatched.clear()

    await asyncio.gather(*[billing_api.services.processor.process(event_row_id) for event_row_id in queued])

    assert len(queued) == 2
    assert await billing_api.wallet_balance(billing_api.primary_id) == 2 * SUBSCRIPTION_CREDITS
    assert len(await billing_api.payment_rows()) == 2


async def test_a_charge_racing_a_cancellation_credits_once_and_keeps_the_cancellation(billing_api: BillingApi) -> None:
    code = await billing_api.plan_product()
    started = await billing_api.activate_subscription(code)
    remote_id = started["razorpaySubscriptionId"]
    moved = await billing_api.transition(remote_id, "charged", emit=False)
    await billing_api.deliver(
        event="subscription.charged", subscriptionId=remote_id, paymentId=moved["razorpayPaymentId"]
    )
    [(event_row_id, _)] = billing_api.recorded.dispatched
    billing_api.recorded.dispatched.clear()

    await asyncio.gather(
        billing_api.services.processor.process(event_row_id),
        billing_api.services.subscriptions.management.cancel(billing_api.primary_id),
    )

    row = await billing_api.subscription_row(started["subscriptionId"])
    assert (row.status, row.cancel_at_period_end) == ("active", True)
    assert await billing_api.wallet_balance(billing_api.primary_id) == 2 * SUBSCRIPTION_CREDITS
