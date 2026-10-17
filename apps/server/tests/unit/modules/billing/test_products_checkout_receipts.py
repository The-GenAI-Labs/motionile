import json
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fakeredis.aioredis import FakeRedis
from hypothesis import given
from hypothesis import strategies as st
from tests.unit.modules.billing.conftest import BillingHarness, pack_product

from motionile.core.redis import RedisKeyBuilder, RedisStore
from motionile.modules.billing.records import ProductRecord
from motionile.modules.billing.schemas import ProductResponse
from motionile.modules.billing.services.checkout import CHECKOUT_NAME, build_checkout
from motionile.modules.billing.services.customers import CustomerProfile
from motionile.modules.billing.services.products import (
    CACHE_CONTROL,
    ProductsService,
    cache_key,
    etag_for,
    etag_matches,
    group_products,
    invalidate_product_cache,
)
from motionile.modules.billing.services.receipts import (
    PaymentReceipt,
    format_amount,
    group_indian,
    receipt_context,
)
from motionile.modules.notifications import Notification
from motionile.modules.notifications.rendering import render_email


@pytest.fixture
async def redis() -> AsyncIterator[RedisStore]:
    client = FakeRedis()
    yield RedisStore(client, RedisKeyBuilder("test"))
    await client.aclose()


def plan(code: str, interval: str, order: int = 0) -> ProductRecord:
    return replace(pack_product(code=code, kind="subscription"), interval=interval, sort_order=order, plan_key="pro")


@pytest.mark.parametrize(
    ("paise", "expected"),
    [
        (5, "₹0.05"),
        (100, "₹1.00"),
        (19_900, "₹199.00"),
        (19_999, "₹199.99"),
        (123_456, "₹1,234.56"),
        (199_900, "₹1,999.00"),
        (10_000_000, "₹1,00,000.00"),
        (1_000_000_000, "₹1,00,00,000.00"),
    ],
)
def test_rupee_amounts_use_indian_grouping(paise: int, expected: str) -> None:
    assert format_amount(paise, "INR") == expected


def test_other_currencies_are_prefixed_with_their_code() -> None:
    assert format_amount(123_456, "USD") == "USD 1,234.56"


@given(st.integers(min_value=0, max_value=10**15))
def test_formatting_is_exact_for_every_amount(paise: int) -> None:
    formatted = format_amount(paise, "INR")

    digits = formatted.removeprefix("₹").replace(",", "")
    assert Decimal(digits) * 100 == paise
    assert digits.count(".") == 1
    assert len(digits.split(".")[1]) == 2


@pytest.mark.parametrize(
    ("digits", "expected"),
    [("1", "1"), ("999", "999"), ("1000", "1,000"), ("100000", "1,00,000"), ("12345678", "1,23,45,678")],
)
def test_indian_grouping(digits: str, expected: str) -> None:
    assert group_indian(digits) == expected


def test_the_receipt_context_describes_the_purchase() -> None:
    receipt = PaymentReceipt(
        user_id=pack_product().id,
        product_name="Starter",
        amount_paise=19_900,
        currency="INR",
        credits=100,
        paid_at=datetime(2026, 10, 18, 9, 30, tzinfo=UTC),
        order_reference="0199f6a8-1b2c-7d3e-8f40-5a6b7c8d9e0f",
    )

    context = receipt_context(receipt)

    assert context == {
        "product": "Starter",
        "amount": "₹199.00 incl. GST",
        "credits": "100",
        "date": "18 October 2026",
        "order": "0199f6a8-1b2c-7d3e-8f40-5a6b7c8d9e0f",
    }
    rendered = render_email(
        Notification(destination="asha@example.com", channel="email", template="payment_receipt", context=context)
    )
    assert "Payment received" in rendered.subject
    assert "₹199.00 incl. GST" in rendered.text
    assert "18 October 2026" in rendered.text


async def test_checkout_data_comes_from_the_stored_order_only(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    customer = CustomerProfile("cust_1", "Asha", "asha@example.com", None)

    checkout = build_checkout(order=order, product_name="Starter", key_id="rzp_test_1", customer=customer)

    assert checkout.model_dump(by_alias=True) == {
        "orderId": order.id,
        "keyId": "rzp_test_1",
        "razorpayOrderId": order.razorpay_order_id,
        "amountPaise": order.amount_paise,
        "currency": "INR",
        "name": CHECKOUT_NAME,
        "description": "Starter",
        "customerId": "cust_1",
        "prefill": {"name": "Asha", "email": "asha@example.com", "contact": None},
    }


async def test_checkout_data_needs_a_provider_order(billing_harness: BillingHarness) -> None:
    order = await billing_harness.local_order()

    with pytest.raises(ValueError, match="provider"):
        build_checkout(order=order, product_name="Starter", key_id="k", customer=CustomerProfile("c", None, None, None))


def test_etags_are_strong_stable_and_content_addressed() -> None:
    first = etag_for(b'{"a": 1}')

    assert first == etag_for(b'{"a": 1}')
    assert first != etag_for(b'{"a": 2}')
    assert first.startswith('"')
    assert first.endswith('"')
    assert not first.startswith("W/")
    assert len(first) == 34


@pytest.mark.parametrize(
    ("header", "matches"),
    [
        (None, False),
        ("", False),
        ('"abc"', True),
        ('W/"abc"', True),
        ('"zzz", "abc"', True),
        ('"zzz","abc"', True),
        ("*", True),
        ('"zzz"', False),
        ("abc", False),
    ],
)
def test_if_none_match_handling(header: str | None, matches: bool) -> None:
    assert etag_matches(header, '"abc"') is matches


def test_the_cache_policy_allows_shared_caches_to_serve_stale_content_while_revalidating() -> None:
    assert CACHE_CONTROL == "public, max-age=60, s-maxage=300, stale-while-revalidate=600"


def test_products_are_grouped_by_kind_in_the_given_order() -> None:
    records = [
        pack_product(code="pack_a"),
        plan("pro_monthly", "month"),
        pack_product(code="pack_b"),
        plan("pro_yearly", "year"),
    ]

    grouped = group_products(records)

    assert [item.code for item in grouped.credit_packs] == ["pack_a", "pack_b"]
    assert [(item.code, item.interval, item.plan_key) for item in grouped.subscriptions] == [
        ("pro_monthly", "month", "pro"),
        ("pro_yearly", "year", "pro"),
    ]
    assert set(grouped.credit_packs[0].model_dump(by_alias=True)) == {
        "code",
        "name",
        "description",
        "pricePaise",
        "currency",
        "interval",
        "planKey",
        "creditsGranted",
        "features",
        "sortOrder",
    }


def test_non_text_features_are_dropped() -> None:
    response = ProductResponse.model_validate(
        {
            "code": "pack_a",
            "name": "A",
            "description": None,
            "price_paise": 100,
            "currency": "INR",
            "interval": None,
            "plan_key": None,
            "credits_granted": 1,
            "features": ["one", 2, None, "three"],
            "sort_order": 0,
        }
    )

    assert response.features == ["one", "three"]


async def test_the_listing_is_cached_until_invalidated(billing_harness: BillingHarness, redis: RedisStore) -> None:
    billing_harness.billing.add_product(pack_product(code="pack_extra", active=False))
    service = ProductsService(billing_harness.world.transaction, redis, store_factory=billing_harness.billing)

    first = await service.listing()
    body = json.loads(first.body)
    assert [item["code"] for item in body["creditPacks"]] == ["pack_starter"]
    assert body["subscriptions"] == []
    billing_harness.billing.products.clear()

    assert await service.listing() == first
    assert await redis.get(cache_key(redis)) == first.body

    await invalidate_product_cache(redis)

    assert json.loads((await service.listing()).body) == {"creditPacks": [], "subscriptions": []}


async def test_only_active_products_are_listed(billing_harness: BillingHarness, redis: RedisStore) -> None:
    billing_harness.billing.add_product(pack_product(code="pack_retired", active=False))
    service = ProductsService(billing_harness.world.transaction, redis, store_factory=billing_harness.billing)

    codes = [item["code"] for item in json.loads((await service.listing()).body)["creditPacks"]]

    assert codes == ["pack_starter"]
