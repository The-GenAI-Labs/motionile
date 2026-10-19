from http import HTTPStatus
from uuid import UUID

from motionile.core.errors import AppError, ConflictError, NotFoundError, ValidationAppError


class InvalidCreditAmountError(ValidationAppError):
    default_code = "invalid_credit_amount"
    title = "Invalid credit amount"


class InvalidCreditReferenceError(ValidationAppError):
    default_code = "invalid_credit_reference"
    title = "Invalid credit reference"


class InvalidIdempotencyKeyError(ValidationAppError):
    default_code = "invalid_idempotency_key"
    title = "Invalid idempotency key"


class InvalidCreditExpiryError(ValidationAppError):
    default_code = "invalid_credit_expiry"
    title = "Invalid credit expiry"


class InvalidAdjustmentReasonError(ValidationAppError):
    default_code = "invalid_adjustment_reason"
    title = "Invalid adjustment reason"


class InvalidUsageRecordError(ValidationAppError):
    default_code = "invalid_usage_record"
    title = "Invalid usage record"


class InvalidUsageRangeError(ValidationAppError):
    default_code = "invalid_usage_range"
    title = "Invalid usage range"


class CommitExceedsReservationError(ValidationAppError):
    default_code = "commit_exceeds_reservation"
    title = "Commit exceeds reservation"


class InsufficientCreditsError(AppError):
    status_code = HTTPStatus.PAYMENT_REQUIRED
    default_code = "insufficient_credits"
    title = "Insufficient credits"

    def __init__(self, *, available: int, required: int) -> None:
        super().__init__(
            "The wallet does not hold enough available credits.",
            extensions={"available": available, "required": required},
        )
        self.available = available
        self.required = required


class ReservationAlreadyActiveError(ConflictError):
    default_code = "reservation_already_active"
    title = "Reservation already active"


class ReservationNotActiveError(ConflictError):
    default_code = "reservation_not_active"
    title = "Reservation not active"


class AdjustmentExceedsAvailableError(ConflictError):
    default_code = "adjustment_exceeds_available"
    title = "Adjustment exceeds available credits"


class DuplicateLotReferenceError(ConflictError):
    default_code = "credit_lot_exists"
    title = "Credit lot already exists"


class IdempotencyKeyConflictError(ConflictError):
    default_code = "idempotency_key_conflict"
    title = "Idempotency key conflict"


class ReservationNotFoundError(NotFoundError):
    default_code = "reservation_not_found"
    title = "Reservation not found"


class LotNotFoundError(NotFoundError):
    default_code = "credit_lot_not_found"
    title = "Credit lot not found"


class CreditUserNotFoundError(NotFoundError):
    default_code = "credit_user_not_found"
    title = "User not found"


class CreditInvariantError(AppError):
    default_code = "credit_invariant_violation"
    title = "Credit invariant violated"


class UnknownCreditUserError(Exception):
    def __init__(self, user_id: UUID) -> None:
        super().__init__(f"no user {user_id}")
        self.user_id = user_id


class ActiveReservationExistsError(Exception):
    pass


class LotReferenceExistsError(Exception):
    pass
