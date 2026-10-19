from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from pydantic import SecretStr

from motionile.modules.billing.exceptions import (
    InvalidPaymentSignatureError,
    OrderNotFoundError,
    PaymentOrderMismatchError,
    PaymentProviderError,
)
from motionile.modules.billing.ports import StoreFactory, Transaction
from motionile.modules.billing.razorpay.api import RazorpayApi
from motionile.modules.billing.razorpay.exceptions import RazorpayError, RazorpayNotConfiguredError
from motionile.modules.billing.razorpay.models import RazorpayPayment
from motionile.modules.billing.razorpay.signatures import verify_order_payment_signature
from motionile.modules.billing.repository import SqlBillingRepository
from motionile.modules.billing.schemas import VerifiedStatus
from motionile.modules.billing.services.decisions import SettlementOutcome, SettlementResult, SettlementSource
from motionile.modules.billing.services.provider import provider_error
from motionile.modules.billing.services.settlement import SettlementService

type SecretSource = Callable[[], SecretStr]


@dataclass(frozen=True)
class VerifyCommand:
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@dataclass(frozen=True)
class VerificationResult:
    order_id: UUID
    status: VerifiedStatus
    credits_granted: int


def verification_result(order_id: UUID, settlement: SettlementResult | None) -> VerificationResult:
    if settlement is None or settlement.outcome not in {
        SettlementOutcome.SETTLED,
        SettlementOutcome.ALREADY_SETTLED,
        SettlementOutcome.DUPLICATE,
    }:
        return VerificationResult(order_id, "pending", 0)
    granted = settlement.credits_granted if settlement.outcome is not SettlementOutcome.DUPLICATE else 0
    return VerificationResult(order_id, "paid", granted)


class PaymentVerificationService:
    def __init__(
        self,
        transaction: Transaction,
        razorpay: RazorpayApi,
        settlement: SettlementService,
        key_secret: SecretSource,
        *,
        store_factory: StoreFactory = SqlBillingRepository,
    ) -> None:
        self._transaction = transaction
        self._razorpay = razorpay
        self._settlement = settlement
        self._key_secret = key_secret
        self._store_factory = store_factory

    async def verify(self, user_id: UUID, command: VerifyCommand) -> VerificationResult:
        self._require_signature(command)
        async with self._transaction() as session:
            order = await self._store_factory(session).order_by_razorpay_id_for_user(command.razorpay_order_id, user_id)
        if order is None:
            raise OrderNotFoundError
        payment = await self._fetch(command.razorpay_payment_id)
        if payment.order_id != order.razorpay_order_id:
            raise PaymentOrderMismatchError
        async with self._transaction() as session:
            if payment.is_captured:
                settlement = await self._settlement.settle(session, payment, SettlementSource.VERIFY)
                return verification_result(order.id, settlement)
            await self._settlement.record_attempt(session, payment)
        return verification_result(order.id, None)

    def _require_signature(self, command: VerifyCommand) -> None:
        try:
            secret = self._key_secret()
        except RazorpayNotConfiguredError as error:
            raise PaymentProviderError("The payment provider is not configured.") from error
        if not verify_order_payment_signature(
            command.razorpay_order_id, command.razorpay_payment_id, command.razorpay_signature, secret
        ):
            raise InvalidPaymentSignatureError

    async def _fetch(self, razorpay_payment_id: str) -> RazorpayPayment:
        try:
            return await self._razorpay.fetch_payment(razorpay_payment_id)
        except RazorpayError as error:
            raise provider_error(error) from error
