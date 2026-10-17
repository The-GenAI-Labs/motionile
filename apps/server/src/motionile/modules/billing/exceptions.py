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
