import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.unit.modules.billing.conftest import PACK_PRICE, BillingHarness, pack_product

from motionile.core.errors import UnauthorizedError
from motionile.core.idempotency import IdempotencyKeyReusedError
from motionile.core.ids import new_id
from motionile.modules.billing.exceptions import (
    OrderNotFoundError,
    OrderNotPayableError,
    PaymentProviderError,
    PaymentProviderRejectedError,
    PaymentProviderUnavailableError,
    ProductNotFoundError,
    ProductNotPurchasableError,
)
from motionile.modules.billing.razorpay.fake_store import EntityKind, FaultKind, FaultOperation
from motionile.modules.billing.razorpay.models import RazorpayOrder
from motionile.modules.billing.services.customers import CustomerService
from motionile.modules.billing.services.orders import OrderDependencies, OrderService
from motionile.modules.billing.states import OrderStatus
from motionile.modules.users import PrimaryContacts

KEY_ID = "rzp_test_key"
CONTACTS = PrimaryContacts(name="Asha Rao", email="asha@example.com", phone="+919876543210")


async def known_contacts(session: AsyncSession, user_id: UUID) -> PrimaryContacts | None:
    del session, user_id
    return CONTACTS


async def unknown_user(session: AsyncSession, user_id: UUID) -> PrimaryContacts | None:
    del session, user_id
    return None


def customers_for(harness: BillingHarness) -> CustomerService:
    return CustomerService(
        harness.world.transaction, harness.razorpay, contacts=known_contacts, store_factory=harness.billing
    )


def service_for(harness: BillingHarness) -> OrderService:
    return OrderService(
        OrderDependencies(
            harness.world.transaction,
            harness.razorpay,
            customers_for(harness),
            harness.clock,
            harness.settings,
            lambda: KEY_ID,
        ),
        store_factory=harness.billing,
    )


def remote_orders(harness: BillingHarness) -> list[str]:
    return [entity_id for kind, entity_id in harness.razorpay_store.entities if kind is EntityKind.ORDER]


async def test_creating_an_order_returns_checkout_data_from_the_stored_order(billing_harness: BillingHarness) -> None:
    service = service_for(billing_harness)

    checkout = await service.create(billing_harness.user_id, "pack_starter", "key-1")

    [order] = billing_harness.billing.orders.values()
    assert order.status is OrderStatus.PENDING
    assert checkout.order_id == order.id
    assert checkout.razorpay_order_id == order.razorpay_order_id
    assert checkout.key_id == KEY_ID
    assert (checkout.amount_paise, checkout.currency) == (PACK_PRICE, "INR")
    assert checkout.name == "Motionile"
    assert checkout.description == "Starter"
    assert checkout.customer_id == billing_harness.billing.customers[billing_harness.user_id].razorpay_customer_id
    assert checkout.prefill.model_dump() == {
        "name": "Asha Rao",
        "email": "asha@example.com",
        "contact": "+919876543210",
    }
    assert order.receipt == str(order.id)
    assert (order.amount_paise, order.currency, order.credits_granted, order.product_version) == (
        PACK_PRICE,
        "INR",
        100,
        1,
    )
    assert order.expires_at == billing_harness.clock.now() + timedelta(
        seconds=billing_harness.settings.order_expiry_seconds
    )


async def test_the_provider_order_carries_the_amount_receipt_and_notes(billing_harness: BillingHarness) -> None:
    service = service_for(billing_harness)

    await service.create(billing_harness.user_id, "pack_starter", "key-1")

    [order] = billing_harness.billing.orders.values()
    assert order.razorpay_order_id is not None
    remote = await billing_harness.razorpay.fetch_order(order.razorpay_order_id)
    assert (remote.amount, remote.currency, remote.receipt) == (PACK_PRICE, "INR", str(order.id))
    assert remote.notes == {"userId": str(billing_harness.user_id), "orderId": str(order.id)}


async def test_repeating_the_request_returns_the_same_order_without_a_second_provider_order(
    billing_harness: BillingHarness,
) -> None:
    service = service_for(billing_harness)
    first = await service.create(billing_harness.user_id, "pack_starter", "key-1")

    second = await service.create(billing_harness.user_id, "pack_starter", "key-1")

    assert second == first
    assert len(billing_harness.billing.orders) == 1
    assert len(remote_orders(billing_harness)) == 1


async def test_the_same_key_for_another_product_is_a_conflict(billing_harness: BillingHarness) -> None:
    billing_harness.billing.add_product(pack_product(code="pack_creator"))
    service = service_for(billing_harness)
    await service.create(billing_harness.user_id, "pack_starter", "key-1")

    with pytest.raises(IdempotencyKeyReusedError):
        await service.create(billing_harness.user_id, "pack_creator", "key-1")


async def test_two_users_may_reuse_the_same_key(billing_harness: BillingHarness) -> None:
    service = service_for(billing_harness)

    first = await service.create(billing_harness.user_id, "pack_starter", "key-1")
    second = await service.create(new_id(), "pack_starter", "key-1")

    assert first.order_id != second.order_id
    assert len(remote_orders(billing_harness)) == 2


async def test_an_unknown_product_is_not_found(billing_harness: BillingHarness) -> None:
    with pytest.raises(ProductNotFoundError):
        await service_for(billing_harness).create(billing_harness.user_id, "missing_pack", "key-1")

    assert billing_harness.billing.orders == {}


async def test_an_inactive_product_looks_like_an_unknown_one(billing_harness: BillingHarness) -> None:
    billing_harness.billing.add_product(pack_product(code="pack_retired", active=False))

    with pytest.raises(ProductNotFoundError):
        await service_for(billing_harness).create(billing_harness.user_id, "pack_retired", "key-1")


async def test_a_subscription_product_cannot_be_bought_as_a_credit_pack(billing_harness: BillingHarness) -> None:
    billing_harness.billing.add_product(pack_product(code="pro_monthly", kind="subscription"))

    with pytest.raises(ProductNotPurchasableError):
        await service_for(billing_harness).create(billing_harness.user_id, "pro_monthly", "key-1")

    assert billing_harness.billing.orders == {}


async def test_a_timeout_after_the_provider_created_the_order_is_recovered_by_receipt(
    billing_harness: BillingHarness,
) -> None:
    await billing_harness.razorpay_store.add_fault(FaultOperation.CREATE_ORDER, FaultKind.TIMEOUT_AFTER_CREATE, 1)

    checkout = await service_for(billing_harness).create(billing_harness.user_id, "pack_starter", "key-1")

    [order] = billing_harness.billing.orders.values()
    assert order.status is OrderStatus.PENDING
    assert len(remote_orders(billing_harness)) == 1
    assert checkout.razorpay_order_id == remote_orders(billing_harness)[0]


async def test_a_timeout_before_creation_leaves_the_order_created_and_a_retry_completes_it(
    billing_harness: BillingHarness,
) -> None:
    service = service_for(billing_harness)
    await billing_harness.razorpay_store.add_fault(FaultOperation.CREATE_ORDER, FaultKind.TIMEOUT_BEFORE_CREATE, 1)

    with pytest.raises(PaymentProviderUnavailableError) as raised:
        await service.create(billing_harness.user_id, "pack_starter", "key-1")

    assert raised.value.status_code == 503
    assert raised.value.code == "payment_provider_unavailable"
    [stalled] = billing_harness.billing.orders.values()
    assert (stalled.status, stalled.razorpay_order_id) == (OrderStatus.CREATED, None)
    assert remote_orders(billing_harness) == []

    checkout = await service.create(billing_harness.user_id, "pack_starter", "key-1")

    assert checkout.order_id == stalled.id
    assert billing_harness.billing.orders[stalled.id].status is OrderStatus.PENDING
    assert len(remote_orders(billing_harness)) == 1


async def test_a_server_error_is_treated_as_ambiguous_and_leaves_the_order_retryable(
    billing_harness: BillingHarness,
) -> None:
    service = service_for(billing_harness)
    await billing_harness.razorpay_store.add_fault(FaultOperation.CREATE_ORDER, FaultKind.SERVER_ERROR, 1)

    with pytest.raises(PaymentProviderUnavailableError):
        await service.create(billing_harness.user_id, "pack_starter", "key-1")

    [stalled] = billing_harness.billing.orders.values()
    assert stalled.status is OrderStatus.CREATED
    assert (await service.create(billing_harness.user_id, "pack_starter", "key-1")).order_id == stalled.id


async def test_a_failing_receipt_lookup_after_a_timeout_stays_retryable(billing_harness: BillingHarness) -> None:
    service = service_for(billing_harness)
    await billing_harness.razorpay_store.add_fault(FaultOperation.CREATE_ORDER, FaultKind.TIMEOUT_AFTER_CREATE, 1)
    await billing_harness.razorpay_store.add_fault(FaultOperation.FIND_ORDER_BY_RECEIPT, FaultKind.SERVER_ERROR, 1)

    with pytest.raises(PaymentProviderUnavailableError):
        await service.create(billing_harness.user_id, "pack_starter", "key-1")

    checkout = await service.create(billing_harness.user_id, "pack_starter", "key-1")

    assert len(remote_orders(billing_harness)) == 1
    assert checkout.razorpay_order_id == remote_orders(billing_harness)[0]


async def test_a_definite_provider_rejection_fails_the_order(billing_harness: BillingHarness) -> None:
    cheap = replace(billing_harness.product, price_paise=50)
    billing_harness.billing.products[cheap.id] = cheap
    service = service_for(billing_harness)

    with pytest.raises(PaymentProviderRejectedError):
        await service.create(billing_harness.user_id, "pack_starter", "key-1")

    [failed] = billing_harness.billing.orders.values()
    assert failed.status is OrderStatus.FAILED
    assert failed.failure_reason is not None
    assert "BAD_REQUEST_ERROR" in failed.failure_reason
    with pytest.raises(OrderNotPayableError):
        await service.create(billing_harness.user_id, "pack_starter", "key-1")


async def test_a_paid_order_cannot_be_reopened_by_repeating_the_key(billing_harness: BillingHarness) -> None:
    service = service_for(billing_harness)
    await service.create(billing_harness.user_id, "pack_starter", "key-1")
    [order] = billing_harness.billing.orders.values()
    billing_harness.billing.orders[order.id] = replace(
        order, status=OrderStatus.PAID, paid_at=billing_harness.clock.now()
    )

    with pytest.raises(OrderNotPayableError):
        await service.create(billing_harness.user_id, "pack_starter", "key-1")


async def test_a_provider_order_with_a_different_amount_is_refused(
    billing_harness: BillingHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_create = billing_harness.razorpay.create_order

    async def tampered(
        *, amount: int, currency: str, receipt: str, notes: Mapping[str, str] | None = None
    ) -> RazorpayOrder:
        return await real_create(amount=amount + 100, currency=currency, receipt=receipt, notes=notes)

    monkeypatch.setattr(billing_harness.razorpay, "create_order", tampered)

    with pytest.raises(PaymentProviderError):
        await service_for(billing_harness).create(billing_harness.user_id, "pack_starter", "key-1")


async def test_reading_an_order_requires_ownership(billing_harness: BillingHarness) -> None:
    service = service_for(billing_harness)
    checkout = await service.create(billing_harness.user_id, "pack_starter", "key-1")

    view = await service.get(billing_harness.user_id, checkout.order_id)

    assert (view.product_code, view.product_name, view.order.id) == ("pack_starter", "Starter", checkout.order_id)
    with pytest.raises(OrderNotFoundError):
        await service.get(new_id(), checkout.order_id)
    with pytest.raises(OrderNotFoundError):
        await service.get(billing_harness.user_id, new_id())


async def test_a_customer_is_created_once_even_for_concurrent_first_purchases(billing_harness: BillingHarness) -> None:
    customers = customers_for(billing_harness)

    profiles = await asyncio.gather(*(customers.ensure(billing_harness.user_id) for _ in range(5)))

    assert len(billing_harness.billing.customers) == 1
    assert len({profile.razorpay_customer_id for profile in profiles}) == 1


async def test_an_existing_customer_is_reused(billing_harness: BillingHarness) -> None:
    customers = customers_for(billing_harness)
    first = await customers.ensure(billing_harness.user_id)
    await billing_harness.razorpay_store.add_fault(FaultOperation.CREATE_CUSTOMER, FaultKind.SERVER_ERROR, 5)

    second = await customers.ensure(billing_harness.user_id)

    assert second == first


async def test_a_customer_failure_is_reported_as_a_provider_problem(billing_harness: BillingHarness) -> None:
    await billing_harness.razorpay_store.add_fault(FaultOperation.CREATE_CUSTOMER, FaultKind.SERVER_ERROR, 1)

    with pytest.raises(PaymentProviderUnavailableError):
        await service_for(billing_harness).create(billing_harness.user_id, "pack_starter", "key-1")

    assert billing_harness.billing.customers == {}
    [stalled] = billing_harness.billing.orders.values()
    assert stalled.status is OrderStatus.CREATED
    assert remote_orders(billing_harness) == []


async def test_a_missing_user_cannot_become_a_customer(billing_harness: BillingHarness) -> None:
    customers = CustomerService(
        billing_harness.world.transaction,
        billing_harness.razorpay,
        contacts=unknown_user,
        store_factory=billing_harness.billing,
    )

    with pytest.raises(UnauthorizedError):
        await customers.ensure(billing_harness.user_id)


async def test_a_user_without_a_name_gets_a_default_customer_name(billing_harness: BillingHarness) -> None:
    async def anonymous(session: AsyncSession, user_id: UUID) -> PrimaryContacts | None:
        del session, user_id
        return PrimaryContacts(name=None, email=None, phone=None)

    customers = CustomerService(
        billing_harness.world.transaction,
        billing_harness.razorpay,
        contacts=anonymous,
        store_factory=billing_harness.billing,
    )

    profile = await customers.ensure(billing_harness.user_id)

    stored = await billing_harness.razorpay_store.get(EntityKind.CUSTOMER, profile.razorpay_customer_id)
    assert stored is not None
    assert stored["name"] == "Motionile customer"
    assert (profile.name, profile.email, profile.contact) == (None, None, None)
