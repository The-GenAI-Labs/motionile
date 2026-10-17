from typing import ClassVar

MAX_DESCRIPTION_LENGTH = 300


class RazorpayError(Exception):
    ambiguous: ClassVar[bool] = False


class RazorpayNotConfiguredError(RazorpayError):
    def __init__(self) -> None:
        super().__init__("Razorpay credentials are not configured")


class RazorpayInvalidIdentifierError(RazorpayError, ValueError):
    def __init__(self) -> None:
        super().__init__("Razorpay identifiers may contain only letters, digits and underscores")


class RazorpayResponseError(RazorpayError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"Razorpay returned an unusable response: {reason}")


class RazorpayTimeoutError(RazorpayError):
    ambiguous: ClassVar[bool] = True

    def __init__(self, reason: str = "the request did not complete") -> None:
        super().__init__(f"Razorpay request outcome is unknown: {reason}")


class RazorpayApiError(RazorpayError):
    def __init__(
        self,
        status_code: int,
        *,
        code: str | None = None,
        description: str | None = None,
        field: str | None = None,
    ) -> None:
        shortened = description[:MAX_DESCRIPTION_LENGTH] if description else None
        detail = ": ".join(part for part in (code, shortened) if part)
        super().__init__(f"Razorpay responded with {status_code}" + (f" ({detail})" if detail else ""))
        self.status_code = status_code
        self.code = code
        self.description = shortened
        self.field = field


class RazorpayAuthenticationError(RazorpayApiError):
    pass


class RazorpayBadRequestError(RazorpayApiError):
    pass


class RazorpayNotFoundError(RazorpayApiError):
    pass


class RazorpayRateLimitedError(RazorpayApiError):
    def __init__(
        self,
        status_code: int,
        *,
        code: str | None = None,
        description: str | None = None,
        field: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(status_code, code=code, description=description, field=field)
        self.retry_after_seconds = retry_after_seconds


class RazorpayServerError(RazorpayApiError):
    ambiguous: ClassVar[bool] = True


class RazorpayUnexpectedStatusError(RazorpayApiError):
    pass
