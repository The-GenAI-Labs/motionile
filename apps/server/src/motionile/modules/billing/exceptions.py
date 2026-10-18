from http import HTTPStatus

from motionile.core.errors import (
    AppError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    PayloadTooLargeError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationAppError,
)

PROVIDER_RETRY_AFTER_SECONDS = "5"


class ProductNotFoundError(NotFoundError):
    default_code = "product_not_found"
    title = "Product not found"


class ProductNotPurchasableError(ValidationAppError):
    default_code = "product_not_purchasable"
    title = "Product cannot be bought this way"


class OrderNotFoundError(NotFoundError):
    default_code = "order_not_found"
    title = "Order not found"


class OrderNotPayableError(ConflictError):
    default_code = "order_not_payable"
    title = "Order can no longer be paid"


class InvalidPaymentSignatureError(BadRequestError):
    default_code = "invalid_payment_signature"
    title = "Invalid payment signature"


class PaymentOrderMismatchError(BadRequestError):
    default_code = "payment_order_mismatch"
    title = "Payment does not belong to the order"


class PaymentProviderUnavailableError(ServiceUnavailableError):
    default_code = "payment_provider_unavailable"
    title = "Payment provider unavailable"

    def __init__(self, detail: str | None = None) -> None:
        super().__init__(
            detail or "The payment provider is not reachable right now. Retry with the same Idempotency-Key.",
            headers={"Retry-After": PROVIDER_RETRY_AFTER_SECONDS},
        )


class PaymentProviderRejectedError(ValidationAppError):
    default_code = "payment_provider_rejected"
    title = "Payment provider rejected the order"


class PaymentProviderError(AppError):
    status_code = HTTPStatus.BAD_GATEWAY
    default_code = "payment_provider_error"
    title = "Payment provider error"


class InvalidWebhookSignatureError(UnauthorizedError):
    default_code = "invalid_webhook_signature"
    title = "Invalid webhook signature"


class InvalidWebhookPayloadError(BadRequestError):
    default_code = "invalid_webhook_payload"
    title = "Invalid webhook payload"


class WebhookEventIdMissingError(BadRequestError):
    default_code = "webhook_event_id_missing"
    title = "Webhook event id missing"


class WebhookTooLargeError(PayloadTooLargeError):
    default_code = "webhook_too_large"
    title = "Webhook body too large"


class WebhookEventNotFoundError(NotFoundError):
    default_code = "webhook_event_not_found"
    title = "Webhook event not found"


class WebhookEventNotReprocessableError(ConflictError):
    default_code = "webhook_event_not_reprocessable"
    title = "Webhook event cannot be reprocessed"


class WebhookProcessingError(Exception):
    def __init__(self, event_id: str, attempts: int) -> None:
        super().__init__(f"webhook event {event_id} failed on attempt {attempts}")
        self.event_id = event_id
        self.attempts = attempts


class SettlementError(Exception):
    pass


class UnexpectedOrderStateError(SettlementError):
    def __init__(self, order_id: str, expected: str) -> None:
        super().__init__(f"order {order_id} was not {expected} while its row was locked")


class SubscriptionNotFoundError(NotFoundError):
    default_code = "subscription_not_found"
    title = "Subscription not found"


class SubscriptionExistsError(ConflictError):
    default_code = "subscription_exists"
    title = "You already have a subscription"


class SubscriptionNotChangeableError(ConflictError):
    default_code = "subscription_not_changeable"
    title = "Subscription cannot be changed"


class PaymentNotFoundError(NotFoundError):
    default_code = "payment_not_found"
    title = "Payment not found"


class PaymentNotRefundableError(ConflictError):
    default_code = "payment_not_refundable"
    title = "Payment cannot be refunded"


class RefundExceedsRefundableError(ValidationAppError):
    default_code = "refund_exceeds_refundable"
    title = "Refund exceeds the refundable amount"

    def __init__(self, refundable_paise: int) -> None:
        super().__init__(
            f"At most {refundable_paise} paise can still be refunded for this payment.",
            extensions={"refundablePaise": max(refundable_paise, 0)},
        )


class RefundRejectedError(ValidationAppError):
    default_code = "refund_rejected"
    title = "Payment provider rejected the refund"


class LiveSubscriptionConflictError(Exception):
    def __init__(self) -> None:
        super().__init__("the user already has a live subscription")


class SettlementCheckError(Exception):
    pass


class SettlementWindowTooLargeError(SettlementCheckError):
    def __init__(self, pages: int) -> None:
        super().__init__(f"the settlement window needs more than {pages} pages of payments")


class SweepFailedError(RuntimeError):
    def __init__(self, task_name: str, failures: int) -> None:
        super().__init__(f"{task_name} failed for {failures} item(s)")
        self.failures = failures
