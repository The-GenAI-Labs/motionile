import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from motionile.core.pagination import Cursor
from motionile.modules.credits.exceptions import CreditInvariantError, InvalidUsageRecordError

type LotSource = Literal["purchase", "subscription", "admin", "promo"]
type LedgerRefType = Literal["payment", "refund", "reservation", "lot", "admin", "promo"]
type JsonObject = dict[str, Any]

LOT_REF_TYPES: frozenset[str] = frozenset({"payment", "admin", "promo"})
GRANT_REASON_BY_SOURCE: dict[str, str] = {
    "purchase": "purchase",
    "subscription": "subscription_grant",
    "promo": "promo_grant",
    "admin": "admin_adjust",
}
GRANT_REASONS: frozenset[str] = frozenset(GRANT_REASON_BY_SOURCE.values())
STAGE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
REASON_TEXT_LIMIT = 500
MAX_USAGE_RANGE_DAYS = 366
MODEL_NAME_LIMIT = 100
COUNTER_LIMIT = 2_147_483_647
MAX_KEY_LENGTH = 200


@dataclass(frozen=True)
class CreditRef:
    ref_type: LedgerRefType
    ref_id: UUID


@dataclass(frozen=True)
class WalletRecord:
    user_id: UUID
    balance: int
    reserved: int
    version: int


@dataclass(frozen=True)
class LotRecord:
    id: UUID
    user_id: UUID
    source: str
    amount: int
    remaining: int
    expires_at: datetime | None
    ref_type: str | None
    ref_id: UUID | None
    created_at: datetime
    expiry_reminder_sent_at: datetime | None = None
    expired_at: datetime | None = None


@dataclass(frozen=True)
class ReservationRecord:
    id: UUID
    user_id: UUID
    amount: int
    status: str
    ref_type: str
    ref_id: UUID
    committed_amount: int | None
    idempotency_key: str
    expires_at: datetime
    settled_at: datetime | None
    created_at: datetime


@dataclass(frozen=True)
class LedgerRecord:
    id: UUID
    user_id: UUID
    delta: int
    reserved_delta: int
    balance_after: int
    reserved_after: int
    reason: str
    ref_type: str | None
    ref_id: UUID | None
    idempotency_key: str
    metadata: JsonObject
    created_at: datetime


@dataclass(frozen=True)
class UsageRow:
    id: UUID
    stage: str
    credits: int
    job_id: UUID | None
    publication_id: UUID | None
    created_at: datetime


@dataclass(frozen=True)
class DailyUsage:
    date: date
    credits: int
    records: int


@dataclass(frozen=True)
class LedgerDayTotal:
    day: date
    reason: str
    granted: int
    removed: int


@dataclass(frozen=True)
class BalanceTotals:
    wallets: int
    balance: int
    reserved: int


@dataclass(frozen=True)
class Page[ItemT]:
    items: list[ItemT]
    next_cursor: Cursor | None


@dataclass(frozen=True)
class Allocation:
    lot_id: UUID
    amount: int


@dataclass(frozen=True)
class ExpiringLot:
    source: str
    remaining: int
    expires_at: datetime


@dataclass(frozen=True)
class WalletView:
    balance: int
    reserved: int
    available: int
    expiring_soon: tuple[ExpiringLot, ...]


@dataclass(frozen=True)
class GrantCommand:
    user_id: UUID
    amount: int
    source: LotSource
    key: str
    expires_at: datetime | None = None
    ref: CreditRef | None = None


@dataclass(frozen=True)
class GrantResult:
    lot_id: UUID
    ledger_id: UUID
    amount: int
    balance_after: int
    expires_at: datetime | None


@dataclass(frozen=True)
class ReserveCommand:
    user_id: UUID
    amount: int
    ref_type: str
    ref_id: UUID
    key: str
    ttl: timedelta | None = None


@dataclass(frozen=True)
class ReservationResult:
    id: UUID
    user_id: UUID
    amount: int
    expires_at: datetime
    reserved_after: int


@dataclass(frozen=True)
class CommitResult:
    reservation_id: UUID
    charged: int
    released: int
    allocations: tuple[Allocation, ...]
    balance_after: int
    reserved_after: int


@dataclass(frozen=True)
class ReleaseResult:
    reservation_id: UUID
    released: int
    reserved_after: int


@dataclass(frozen=True)
class ClawbackCommand:
    lot_id: UUID
    amount: int
    reason: str
    ref: CreditRef
    key: str


@dataclass(frozen=True)
class ClawbackResult:
    lot_id: UUID
    requested: int
    clawed_back: int
    balance_after: int | None


@dataclass(frozen=True)
class AdjustCommand:
    user_id: UUID
    delta: int
    reason: str
    actor_id: UUID
    key: str
    expires_at: datetime | None = None


@dataclass(frozen=True)
class AdjustResult:
    user_id: UUID
    delta: int
    action_id: UUID
    lot_id: UUID | None
    allocations: tuple[Allocation, ...]
    balance_after: int


@dataclass(frozen=True)
class ExpiryResult:
    user_id: UUID
    expired: int


@dataclass(frozen=True)
class ReminderBatch:
    user_id: UUID
    credits: int
    expires_at: datetime


@dataclass(frozen=True)
class IntegrityProblem:
    invariant: str
    expected: int
    actual: int


@dataclass(frozen=True)
class WalletAudit:
    user_id: UUID
    balance: int
    reserved: int
    ledger_delta_sum: int
    ledger_reserved_sum: int
    lot_remaining_sum: int
    active_reservation_sum: int
    latest_balance_after: int
    latest_reserved_after: int
    negative_lots: int

    def problems(self) -> tuple[IntegrityProblem, ...]:
        found: list[IntegrityProblem] = []
        if self.balance != self.ledger_delta_sum:
            found.append(IntegrityProblem("balance_equals_ledger_delta_sum", self.ledger_delta_sum, self.balance))
        if self.balance != self.lot_remaining_sum:
            found.append(IntegrityProblem("balance_equals_lot_remaining_sum", self.lot_remaining_sum, self.balance))
        if self.reserved != self.ledger_reserved_sum:
            found.append(
                IntegrityProblem("reserved_equals_ledger_reserved_sum", self.ledger_reserved_sum, self.reserved)
            )
        if self.reserved != self.active_reservation_sum:
            found.append(
                IntegrityProblem("reserved_equals_active_reservations", self.active_reservation_sum, self.reserved)
            )
        if self.balance != self.latest_balance_after:
            found.append(
                IntegrityProblem("balance_equals_latest_balance_after", self.latest_balance_after, self.balance)
            )
        if self.reserved != self.latest_reserved_after:
            found.append(
                IntegrityProblem("reserved_equals_latest_reserved_after", self.latest_reserved_after, self.reserved)
            )
        if self.balance < 0:
            found.append(IntegrityProblem("balance_non_negative", 0, self.balance))
        if self.reserved < 0 or self.reserved > self.balance:
            found.append(
                IntegrityProblem("reserved_within_balance", min(self.balance, max(self.reserved, 0)), self.reserved)
            )
        if self.negative_lots > 0:
            found.append(IntegrityProblem("lots_non_negative", 0, self.negative_lots))
        return tuple(found)


@dataclass(frozen=True)
class IntegrityViolation:
    user_id: UUID
    problems: tuple[IntegrityProblem, ...]


@dataclass(frozen=True)
class UsageEntry:
    user_id: UUID
    stage: str
    provider: str
    key: str
    model: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    audio_characters: int = 0
    render_ms: int = 0
    cost_micros_usd: int = 0
    credits: int = 0
    job_id: UUID | None = None
    publication_id: UUID | None = None

    def __post_init__(self) -> None:
        counters = (
            self.input_tokens,
            self.output_tokens,
            self.audio_characters,
            self.render_ms,
            self.cost_micros_usd,
            self.credits,
        )
        valid_shape = (
            STAGE_PATTERN.fullmatch(self.stage) is not None
            and STAGE_PATTERN.fullmatch(self.provider) is not None
            and (self.model is None or len(self.model) <= MODEL_NAME_LIMIT)
            and 0 < len(self.key) <= MAX_KEY_LENGTH
        )
        if not valid_shape or any(value < 0 for value in counters):
            raise InvalidUsageRecordError
        if any(value > COUNTER_LIMIT for value in counters[:4]):
            raise InvalidUsageRecordError


def consumption_order(lot: LotRecord) -> tuple[bool, datetime, datetime, str]:
    return (lot.expires_at is None, lot.expires_at or lot.created_at, lot.created_at, str(lot.id))


def allocate(lots: Sequence[LotRecord], amount: int) -> tuple[Allocation, ...]:
    remaining = amount
    allocations: list[Allocation] = []
    for lot in lots:
        if remaining == 0:
            break
        take = min(lot.remaining, remaining)
        if take > 0:
            allocations.append(Allocation(lot.id, take))
            remaining -= take
    if remaining > 0:
        raise CreditInvariantError
    return tuple(allocations)
