from motionile.core.errors import AppError
from motionile.modules.billing.exceptions import PaymentProviderError, PaymentProviderUnavailableError
from motionile.modules.billing.razorpay.exceptions import (
    RazorpayError,
    RazorpayRateLimitedError,
    RazorpayResponseError,
    RazorpayServerError,
    RazorpayTimeoutError,
)

TRANSIENT_ERRORS = (RazorpayTimeoutError, RazorpayServerError, RazorpayRateLimitedError, RazorpayResponseError)


def is_ambiguous(error: RazorpayError) -> bool:
    return error.ambiguous or isinstance(error, RazorpayResponseError)


def provider_error(error: RazorpayError) -> AppError:
    if isinstance(error, TRANSIENT_ERRORS):
        return PaymentProviderUnavailableError()
    return PaymentProviderError("The payment provider could not process the request.")
