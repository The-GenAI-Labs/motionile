import pytest
from pydantic import SecretStr
from tests.fakes.settings import make_settings
from tests.unit.modules.billing.conftest import PACK_CREDITS, PACK_PRICE, BillingHarness

from motionile.core.ids import new_id
from motionile.modules.billing.exceptions import (
    InvalidPaymentSignatureError,
    OrderNotFoundError,
    PaymentOrderMismatchError,
    PaymentProviderError,
    PaymentProviderUnavailableError,
)
from motionile.modules.billing.razorpay.credentials import razorpay_credentials
from motionile.modules.billing.razorpay.exceptions import RazorpayNotConfiguredError
from motionile.modules.billing.razorpay.fake_entities import PaymentSpec, new_entity_id, payment_entity
from motionile.modules.billing.razorpay.fake_simulator import PaymentOutcome
from motionile.modules.billing.razorpay.fake_store import EntityKind, FaultKind, FaultOperation
from motionile.modules.billing.razorpay.signatures import sign_order_payment
from motionile.modules.billing.records import OrderRecord
from motionile.modules.billing.services.verification import (
    PaymentVerificationService,
    VerificationResult,
    VerifyCommand,
)
from motionile.modules.billing.states import OrderStatus, PaymentRecordStatus

KEY_SECRET = razorpay_credentials(make_settings()).key_secret


def service_for(harness: BillingHarness, secret: SecretStr = KEY_SECRET) -> PaymentVerificationService:
    return PaymentVerificationService(
        harness.world.transaction,
        harness.razorpay,
        harness.settlement,
        lambda: secret,
        store_factory=harness.billing,
    )


def command_for(order: OrderRecord, payment_id: str, *, signature: str | None = None) -> VerifyCommand:
    assert order.razorpay_order_id is not None
    return VerifyCommand(
        razorpay_order_id=order.razorpay_order_id,
        razorpay_payment_id=payment_id,
        razorpay_signature=signature or sign_order_payment(order.razorpay_order_id, payment_id, KEY_SECRET),
    )


async def test_a_captured_payment_is_confirmed_with_the_provider_and_settled(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)

    result = await service_for(billing_harness).verify(billing_harness.user_id, command_for(order, payment.id))

    assert result == VerificationResult(order.id, "paid", PACK_CREDITS)
    assert billing_harness.balance() == PACK_CREDITS
    assert billing_harness.billing.orders[order.id].status is OrderStatus.PAID


async def test_verifying_twice_returns_the_same_result_and_grants_once(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    service = service_for(billing_harness)

    first = await service.verify(billing_harness.user_id, command_for(order, payment.id))
    second = await service.verify(billing_harness.user_id, command_for(order, payment.id))

    assert first == second
    assert billing_harness.balance() == PACK_CREDITS
    assert len(billing_harness.credits_store.ledger) == 1


async def test_a_wrong_signature_is_rejected_before_anything_is_read(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    tampered = command_for(order, payment.id, signature="0" * 64)

    with pytest.raises(InvalidPaymentSignatureError) as raised:
        await service_for(billing_harness).verify(billing_harness.user_id, tampered)

    assert (raised.value.status_code, raised.value.code) == (400, "invalid_payment_signature")
    assert billing_harness.balance() == 0
    assert billing_harness.billing.payments == {}


@pytest.mark.parametrize("signature", ["", "not-hex", "A" * 64, "0" * 63])
async def test_malformed_signatures_are_rejected(billing_harness: BillingHarness, signature: str) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    command = VerifyCommand(order.razorpay_order_id or "", payment.id, signature)

    with pytest.raises(InvalidPaymentSignatureError):
        await service_for(billing_harness).verify(billing_harness.user_id, command)


async def test_a_signature_made_with_another_secret_is_rejected(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    forged = sign_order_payment(order.razorpay_order_id or "", payment.id, SecretStr("another-secret"))

    with pytest.raises(InvalidPaymentSignatureError):
        await service_for(billing_harness).verify(
            billing_harness.user_id, command_for(order, payment.id, signature=forged)
        )


async def test_someone_elses_order_is_not_found_even_with_a_valid_signature(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)

    with pytest.raises(OrderNotFoundError):
        await service_for(billing_harness).verify(new_id(), command_for(order, payment.id))

    assert billing_harness.balance() == 0
    assert billing_harness.billing.orders[order.id].status is OrderStatus.PENDING


async def test_an_unknown_provider_order_is_not_found(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    command = VerifyCommand("order_unknown", payment.id, sign_order_payment("order_unknown", payment.id, KEY_SECRET))

    with pytest.raises(OrderNotFoundError):
        await service_for(billing_harness).verify(billing_harness.user_id, command)


async def test_a_payment_that_belongs_to_another_order_is_refused(billing_harness: BillingHarness) -> None:
    mine = await billing_harness.open_order()
    other = await billing_harness.open_order(user_id=new_id())
    other_payment = await billing_harness.pay(other)

    with pytest.raises(PaymentOrderMismatchError):
        await service_for(billing_harness).verify(billing_harness.user_id, command_for(mine, other_payment.id))

    assert billing_harness.balance() == 0
    assert billing_harness.balance(other.user_id) == 0


async def test_an_authorized_payment_is_recorded_but_not_credited(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order, PaymentOutcome.AUTHORIZED)

    result = await service_for(billing_harness).verify(billing_harness.user_id, command_for(order, payment.id))

    assert result == VerificationResult(order.id, "pending", 0)
    [recorded] = billing_harness.billing.payments.values()
    assert recorded.status is PaymentRecordStatus.AUTHORIZED
    assert billing_harness.balance() == 0
    assert billing_harness.billing.orders[order.id].status is OrderStatus.PENDING


async def test_a_failed_payment_keeps_the_order_pending(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order, PaymentOutcome.FAILURE)
    command = command_for(order, payment.id)

    result = await service_for(billing_harness).verify(billing_harness.user_id, command)

    assert result == VerificationResult(order.id, "pending", 0)
    [recorded] = billing_harness.billing.payments.values()
    assert recorded.status is PaymentRecordStatus.FAILED
    assert billing_harness.billing.orders[order.id].status is OrderStatus.PENDING
    assert billing_harness.balance() == 0


async def test_a_mismatched_capture_is_held_for_review(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order, amount=PACK_PRICE - 1)

    result = await service_for(billing_harness).verify(billing_harness.user_id, command_for(order, payment.id))

    assert result == VerificationResult(order.id, "pending", 0)
    assert billing_harness.billing.orders[order.id].flag_reason == "amount_mismatch"
    assert billing_harness.balance() == 0


async def test_a_provider_timeout_while_fetching_the_payment_is_retryable(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order)
    await billing_harness.razorpay_store.add_fault(FaultOperation.FETCH_PAYMENT, FaultKind.TIMEOUT_BEFORE_CREATE, 1)
    service = service_for(billing_harness)

    with pytest.raises(PaymentProviderUnavailableError):
        await service.verify(billing_harness.user_id, command_for(order, payment.id))

    assert billing_harness.balance() == 0
    assert (await service.verify(billing_harness.user_id, command_for(order, payment.id))).status == "paid"


async def test_missing_credentials_are_reported_as_a_provider_error(billing_harness: BillingHarness) -> None:
    def unconfigured() -> SecretStr:
        raise RazorpayNotConfiguredError

    service = PaymentVerificationService(
        billing_harness.world.transaction,
        billing_harness.razorpay,
        billing_harness.settlement,
        unconfigured,
        store_factory=billing_harness.billing,
    )
    order = await billing_harness.open_order()

    with pytest.raises(PaymentProviderError):
        await service.verify(billing_harness.user_id, command_for(order, "pay_x"))


async def add_duplicate_capture(harness: BillingHarness, order: OrderRecord) -> str:
    payment_id = await new_entity_id(harness.razorpay_store, "pay")
    entity = payment_entity(
        payment_id,
        harness.clock.now(),
        PaymentSpec(amount=PACK_PRICE, currency="INR", status="captured", order_id=order.razorpay_order_id),
    )
    await harness.razorpay_store.put(EntityKind.PAYMENT, payment_id, entity)
    return payment_id


async def test_verifying_a_payment_held_for_review_keeps_answering_pending(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    payment = await billing_harness.pay(order, amount=PACK_PRICE + 1)
    service = service_for(billing_harness)

    first = await service.verify(billing_harness.user_id, command_for(order, payment.id))
    second = await service.verify(billing_harness.user_id, command_for(order, payment.id))

    assert first == second == VerificationResult(order.id, "pending", 0)
    assert billing_harness.balance() == 0
    assert billing_harness.billing.orders[order.id].status is not OrderStatus.PAID


async def test_a_mismatched_payment_does_not_report_paid_after_another_payment_paid_the_order(
    billing_harness: BillingHarness,
) -> None:
    order = await billing_harness.open_order()
    wrong = await billing_harness.pay(order, amount=PACK_PRICE - 1)
    service = service_for(billing_harness)
    await service.verify(billing_harness.user_id, command_for(order, wrong.id))
    right = await billing_harness.simulator.pay_order(order.razorpay_order_id or "", PaymentOutcome.SUCCESS)
    paid = await service.verify(billing_harness.user_id, command_for(order, right.payment["id"]))

    again = await service.verify(billing_harness.user_id, command_for(order, wrong.id))

    assert paid.status == "paid"
    assert again == VerificationResult(order.id, "pending", 0)
    assert billing_harness.balance() == PACK_CREDITS


async def test_a_duplicate_payment_keeps_answering_with_no_credits(billing_harness: BillingHarness) -> None:
    order = await billing_harness.open_order()
    first = await billing_harness.pay(order)
    service = service_for(billing_harness)
    await service.verify(billing_harness.user_id, command_for(order, first.id))
    payment_id = await add_duplicate_capture(billing_harness, order)
    once = await service.verify(billing_harness.user_id, command_for(order, payment_id))

    twice = await service.verify(billing_harness.user_id, command_for(order, payment_id))

    assert once == twice == VerificationResult(order.id, "paid", 0)
    assert billing_harness.balance() == PACK_CREDITS
