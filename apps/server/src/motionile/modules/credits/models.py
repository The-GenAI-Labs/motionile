from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from motionile.core.db import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

LEDGER_REASON_DELTAS = " AND ".join(
    (
        "(reason <> 'purchase' OR (delta > 0 AND reserved_delta = 0))",
        "(reason <> 'subscription_grant' OR (delta > 0 AND reserved_delta = 0))",
        "(reason <> 'promo_grant' OR (delta > 0 AND reserved_delta = 0))",
        "(reason <> 'admin_adjust' OR (delta <> 0 AND reserved_delta = 0))",
        "(reason <> 'reserve' OR (delta = 0 AND reserved_delta > 0))",
        "(reason <> 'commit' OR (delta <= 0 AND reserved_delta < 0))",
        "(reason <> 'release' OR (delta = 0 AND reserved_delta < 0))",
        "(reason <> 'refund_clawback' OR (delta < 0 AND reserved_delta = 0))",
        "(reason <> 'expiry' OR (delta < 0 AND reserved_delta = 0))",
    )
)


class CreditWallet(TimestampMixin, Base):
    __tablename__ = "credit_wallets"
    __table_args__ = (
        CheckConstraint("balance >= 0", name="balance_non_negative"),
        CheckConstraint("reserved >= 0 AND reserved <= balance", name="reserved_range"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    balance: Mapped[int] = mapped_column(BigInteger, server_default="0")
    reserved: Mapped[int] = mapped_column(BigInteger, server_default="0")
    version: Mapped[int] = mapped_column(server_default="0")


class CreditLot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "credit_lots"
    __table_args__ = (
        CheckConstraint("source IN ('purchase', 'subscription', 'admin', 'promo')", name="source"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("remaining BETWEEN 0 AND amount", name="remaining_range"),
        CheckConstraint("ref_type IS NULL OR ref_type IN ('payment', 'admin', 'promo')", name="ref_type"),
        CheckConstraint("(ref_type IS NULL) = (ref_id IS NULL)", name="ref_consistent"),
        CheckConstraint("expired_at IS NULL OR remaining = 0", name="expired_consistent"),
        Index(
            "uq_credit_lots_source_ref",
            "source",
            "ref_type",
            "ref_id",
            unique=True,
            postgresql_where=text("ref_id IS NOT NULL"),
        ),
        Index(
            "ix_credit_lots_user_id_consumption",
            "user_id",
            "expires_at",
            "created_at",
            "id",
            postgresql_where=text("remaining > 0"),
        ),
        Index(
            "ix_credit_lots_expires_at",
            "expires_at",
            postgresql_where=text("remaining > 0 AND expires_at IS NOT NULL"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    source: Mapped[str]
    amount: Mapped[int] = mapped_column(BigInteger)
    remaining: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime | None]
    ref_type: Mapped[str | None]
    ref_id: Mapped[UUID | None]
    expiry_reminder_sent_at: Mapped[datetime | None]
    expired_at: Mapped[datetime | None]


class CreditReservation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "credit_reservations"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_credit_reservations_idempotency_key"),
        CheckConstraint("status IN ('active', 'committed', 'released', 'expired')", name="status"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("committed_amount IS NULL OR committed_amount BETWEEN 0 AND amount", name="committed_range"),
        CheckConstraint("(status = 'committed') = (committed_amount IS NOT NULL)", name="committed_consistent"),
        CheckConstraint("(status = 'active') = (settled_at IS NULL)", name="settled_consistent"),
        CheckConstraint("ref_type ~ '^[a-z][a-z0-9_]{1,39}$'", name="ref_type_format"),
        Index(
            "uq_credit_reservations_active_ref",
            "ref_type",
            "ref_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_credit_reservations_user_id_created_at", "user_id", "created_at"),
        Index("ix_credit_reservations_expires_at", "expires_at", postgresql_where=text("status = 'active'")),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(server_default=text("'active'"))
    ref_type: Mapped[str]
    ref_id: Mapped[UUID]
    committed_amount: Mapped[int | None] = mapped_column(BigInteger)
    idempotency_key: Mapped[str]
    expires_at: Mapped[datetime]
    settled_at: Mapped[datetime | None]


class CreditLedgerEntry(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "credit_ledger"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_credit_ledger_idempotency_key"),
        CheckConstraint(
            "reason IN ('purchase', 'subscription_grant', 'promo_grant', 'admin_adjust', 'reserve', 'commit', "
            "'release', 'refund_clawback', 'expiry')",
            name="reason",
        ),
        CheckConstraint("delta <> 0 OR reserved_delta <> 0", name="moves_credits"),
        CheckConstraint(LEDGER_REASON_DELTAS, name="reason_deltas"),
        CheckConstraint(
            "balance_after >= 0 AND reserved_after >= 0 AND reserved_after <= balance_after", name="after_range"
        ),
        CheckConstraint(
            "ref_type IS NULL OR ref_type IN ('payment', 'refund', 'reservation', 'lot', 'admin', 'promo')",
            name="ref_type",
        ),
        CheckConstraint("(ref_type IS NULL) = (ref_id IS NULL)", name="ref_consistent"),
        CheckConstraint("jsonb_typeof(metadata) = 'object'", name="metadata_object"),
        Index("ix_credit_ledger_user_id_created_at_id", "user_id", "created_at", "id"),
        Index("ix_credit_ledger_ref_type_ref_id", "ref_type", "ref_id"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    delta: Mapped[int] = mapped_column(BigInteger)
    reserved_delta: Mapped[int] = mapped_column(BigInteger, server_default="0")
    balance_after: Mapped[int] = mapped_column(BigInteger)
    reserved_after: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str]
    ref_type: Mapped[str | None]
    ref_id: Mapped[UUID | None]
    idempotency_key: Mapped[str]
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))


class UsageRecord(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "usage_records"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_usage_records_idempotency_key"),
        CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND audio_characters >= 0 AND render_ms >= 0 "
            "AND cost_micros_usd >= 0 AND credits >= 0",
            name="counters_non_negative",
        ),
        CheckConstraint("stage ~ '^[a-z][a-z0-9_]{1,39}$'", name="stage_format"),
        CheckConstraint("provider ~ '^[a-z][a-z0-9_]{1,39}$'", name="provider_format"),
        CheckConstraint("model IS NULL OR char_length(model) <= 100", name="model_length"),
        Index("ix_usage_records_user_id_created_at", "user_id", "created_at"),
        Index("ix_usage_records_job_id", "job_id"),
        Index("ix_usage_records_publication_id", "publication_id"),
        Index("ix_usage_records_provider_created_at", "provider", "created_at"),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    job_id: Mapped[UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    publication_id: Mapped[UUID | None]
    stage: Mapped[str]
    provider: Mapped[str]
    model: Mapped[str | None]
    input_tokens: Mapped[int] = mapped_column(server_default="0")
    output_tokens: Mapped[int] = mapped_column(server_default="0")
    audio_characters: Mapped[int] = mapped_column(server_default="0")
    render_ms: Mapped[int] = mapped_column(server_default="0")
    cost_micros_usd: Mapped[int] = mapped_column(BigInteger, server_default="0")
    credits: Mapped[int] = mapped_column(BigInteger, server_default="0")
    idempotency_key: Mapped[str]
