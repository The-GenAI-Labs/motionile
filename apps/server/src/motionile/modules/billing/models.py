from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CHAR, BigInteger, CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from motionile.core.db import Base, TimestampMixin, UUIDPrimaryKeyMixin

LIVE_SUBSCRIPTION_STATUSES = "('authenticated', 'active', 'pending', 'halted', 'paused')"


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("code", name="uq_products_code"),
        UniqueConstraint("razorpay_plan_id", name="uq_products_razorpay_plan_id"),
        CheckConstraint("kind IN ('subscription', 'credit_pack')", name="kind"),
        CheckConstraint("price_paise > 0", name="price_paise_positive"),
        CheckConstraint("credits_granted > 0", name="credits_granted_positive"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("interval IS NULL OR interval IN ('month', 'year')", name="interval"),
        CheckConstraint(
            "(kind = 'subscription' AND interval IS NOT NULL AND plan_key IS NOT NULL) "
            "OR (kind = 'credit_pack' AND interval IS NULL AND plan_key IS NULL AND razorpay_plan_id IS NULL)",
            name="shape",
        ),
        CheckConstraint(
            "kind <> 'subscription' OR NOT is_active OR razorpay_plan_id IS NOT NULL",
            name="active_subscription_has_plan",
        ),
        CheckConstraint("code ~ '^[a-z0-9]+(_[a-z0-9]+)*$' AND char_length(code) <= 60", name="code_format"),
        CheckConstraint("plan_key IS NULL OR plan_key ~ '^[a-z0-9]+(_[a-z0-9]+)*$'", name="plan_key_format"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 80", name="name_length"),
        CheckConstraint("description IS NULL OR char_length(description) <= 500", name="description_length"),
        CheckConstraint("jsonb_typeof(features) = 'array'", name="features_array"),
        CheckConstraint("version >= 1", name="version_positive"),
        CheckConstraint("supersedes_product_id IS NULL OR supersedes_product_id <> id", name="not_own_predecessor"),
        Index("ix_products_kind_sort_order", "kind", "sort_order", postgresql_where=text("is_active")),
        Index(
            "ix_products_plan_key_interval_active",
            "plan_key",
            "interval",
            unique=True,
            postgresql_where=text("is_active AND kind = 'subscription'"),
        ),
        Index("ix_products_supersedes_product_id", "supersedes_product_id"),
    )

    code: Mapped[str]
    kind: Mapped[str]
    plan_key: Mapped[str | None]
    name: Mapped[str]
    description: Mapped[str | None]
    price_paise: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(CHAR(3), server_default=text("'INR'"))
    interval: Mapped[str | None]
    credits_granted: Mapped[int] = mapped_column(BigInteger)
    razorpay_plan_id: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    is_sample: Mapped[bool] = mapped_column(server_default=text("false"))
    supersedes_product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    sort_order: Mapped[int] = mapped_column(server_default="0")
    features: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    version: Mapped[int] = mapped_column(server_default="1")


class BillingCustomer(TimestampMixin, Base):
    __tablename__ = "billing_customers"
    __table_args__ = (UniqueConstraint("razorpay_customer_id", name="uq_billing_customers_razorpay_customer_id"),)

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    razorpay_customer_id: Mapped[str]


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("razorpay_subscription_id", name="uq_subscriptions_razorpay_subscription_id"),
        CheckConstraint(
            "status IN ('created', 'authenticated', 'active', 'pending', 'halted', 'paused', "
            "'cancelled', 'completed', 'expired')",
            name="status",
        ),
        CheckConstraint(
            "current_period_end IS NULL OR current_period_start IS NULL OR current_period_end > current_period_start",
            name="period_order",
        ),
        CheckConstraint("total_count > 0", name="total_count_positive"),
        CheckConstraint("paid_count >= 0", name="paid_count_non_negative"),
        CheckConstraint(
            "(status IN ('cancelled', 'completed', 'expired')) = (ended_at IS NOT NULL)", name="ended_consistent"
        ),
        CheckConstraint("status = 'created' OR razorpay_subscription_id IS NOT NULL", name="live_has_razorpay_id"),
        Index(
            "ix_subscriptions_user_id_live",
            "user_id",
            unique=True,
            postgresql_where=text(f"status IN {LIVE_SUBSCRIPTION_STATUSES}"),
        ),
        Index("ix_subscriptions_user_id_created_at", "user_id", "created_at"),
        Index("ix_subscriptions_product_id", "product_id"),
        Index("ix_subscriptions_pending_product_id", "pending_product_id"),
        Index(
            "ix_subscriptions_status_current_period_end",
            "status",
            "current_period_end",
            postgresql_where=text(f"status IN {LIVE_SUBSCRIPTION_STATUSES}"),
        ),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    pending_product_id: Mapped[UUID | None] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    razorpay_subscription_id: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default=text("'created'"))
    total_count: Mapped[int]
    paid_count: Mapped[int] = mapped_column(server_default="0")
    current_period_start: Mapped[datetime | None]
    current_period_end: Mapped[datetime | None]
    next_charge_at: Mapped[datetime | None]
    cancel_at_period_end: Mapped[bool] = mapped_column(server_default=text("false"))
    cancelled_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]
    last_event_at: Mapped[datetime | None]


class Order(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("razorpay_order_id", name="uq_orders_razorpay_order_id"),
        UniqueConstraint("receipt", name="uq_orders_receipt"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_orders_user_id_idempotency_key"),
        CheckConstraint("status IN ('created', 'pending', 'paid', 'failed', 'expired', 'cancelled')", name="status"),
        CheckConstraint("kind IN ('credit_pack', 'subscription')", name="kind"),
        CheckConstraint("(kind = 'subscription') = (subscription_id IS NOT NULL)", name="subscription_consistent"),
        CheckConstraint("amount_paise > 0", name="amount_paise_positive"),
        CheckConstraint("credits_granted > 0", name="credits_granted_positive"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        CheckConstraint("(status = 'paid') = (paid_at IS NOT NULL)", name="paid_consistent"),
        CheckConstraint("(flagged_at IS NULL) = (flag_reason IS NULL)", name="flag_consistent"),
        CheckConstraint(
            "flag_reason IS NULL OR flag_reason IN ('amount_mismatch', 'currency_mismatch', 'duplicate_payment')",
            name="flag_reason",
        ),
        CheckConstraint("char_length(receipt) <= 40", name="receipt_length"),
        Index("ix_orders_user_id_created_at", "user_id", "created_at"),
        Index("ix_orders_product_id", "product_id"),
        Index("ix_orders_subscription_id", "subscription_id"),
        Index(
            "ix_orders_status_created_at",
            "status",
            "created_at",
            postgresql_where=text("status IN ('created', 'pending') AND flagged_at IS NULL"),
        ),
        Index("ix_orders_flagged_at", "flagged_at", postgresql_where=text("flagged_at IS NOT NULL")),
    )

    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    product_id: Mapped[UUID] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    product_version: Mapped[int]
    kind: Mapped[str]
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(CHAR(3), server_default=text("'INR'"))
    credits_granted: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(server_default=text("'created'"))
    razorpay_order_id: Mapped[str | None]
    subscription_id: Mapped[UUID | None] = mapped_column(ForeignKey("subscriptions.id", ondelete="RESTRICT"))
    receipt: Mapped[str]
    idempotency_key: Mapped[str]
    failure_reason: Mapped[str | None]
    flagged_at: Mapped[datetime | None]
    flag_reason: Mapped[str | None]
    expires_at: Mapped[datetime]
    paid_at: Mapped[datetime | None]


class Payment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("razorpay_payment_id", name="uq_payments_razorpay_payment_id"),
        CheckConstraint(
            "status IN ('authorized', 'captured', 'failed', 'refunded', 'partially_refunded')", name="status"
        ),
        CheckConstraint("num_nonnulls(order_id, subscription_id) >= 1", name="has_parent"),
        CheckConstraint("amount_paise > 0", name="amount_paise_positive"),
        CheckConstraint("credits_granted >= 0", name="credits_granted_non_negative"),
        CheckConstraint("refunded_paise BETWEEN 0 AND amount_paise", name="refunded_paise_range"),
        CheckConstraint("fee_paise IS NULL OR fee_paise >= 0", name="fee_paise_non_negative"),
        CheckConstraint("tax_paise IS NULL OR tax_paise >= 0", name="tax_paise_non_negative"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency_format"),
        Index("ix_payments_order_id", "order_id"),
        Index("ix_payments_subscription_id", "subscription_id"),
        Index("ix_payments_user_id_created_at", "user_id", "created_at"),
        Index("ix_payments_created_at", "created_at"),
    )

    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    subscription_id: Mapped[UUID | None] = mapped_column(ForeignKey("subscriptions.id", ondelete="RESTRICT"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    razorpay_payment_id: Mapped[str]
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(CHAR(3), server_default=text("'INR'"))
    status: Mapped[str]
    method: Mapped[str | None]
    fee_paise: Mapped[int | None] = mapped_column(BigInteger)
    tax_paise: Mapped[int | None] = mapped_column(BigInteger)
    credits_granted: Mapped[int] = mapped_column(BigInteger, server_default="0")
    refunded_paise: Mapped[int] = mapped_column(BigInteger, server_default="0")
    error_code: Mapped[str | None]
    error_description: Mapped[str | None]
    captured_at: Mapped[datetime | None]


class Refund(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        UniqueConstraint("razorpay_refund_id", name="uq_refunds_razorpay_refund_id"),
        CheckConstraint("status IN ('pending', 'processed', 'failed')", name="status"),
        CheckConstraint("amount_paise > 0", name="amount_paise_positive"),
        CheckConstraint("credits_clawed_back >= 0", name="credits_clawed_back_non_negative"),
        CheckConstraint("(status = 'processed') = (processed_at IS NOT NULL)", name="processed_consistent"),
        CheckConstraint("char_length(reason) BETWEEN 1 AND 500", name="reason_length"),
        Index("ix_refunds_payment_id", "payment_id"),
        Index("ix_refunds_initiated_by", "initiated_by"),
    )

    payment_id: Mapped[UUID] = mapped_column(ForeignKey("payments.id", ondelete="RESTRICT"))
    razorpay_refund_id: Mapped[str | None]
    amount_paise: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(server_default=text("'pending'"))
    reason: Mapped[str]
    initiated_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    credits_clawed_back: Mapped[int] = mapped_column(BigInteger, server_default="0")
    failure_reason: Mapped[str | None]
    processed_at: Mapped[datetime | None]


class WebhookEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "event_id", name="uq_webhook_events_provider_event_id"),
        CheckConstraint("status IN ('received', 'processing', 'processed', 'failed', 'ignored')", name="status"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("provider ~ '^[a-z][a-z0-9_]{1,39}$'", name="provider_format"),
        CheckConstraint("last_error IS NULL OR char_length(last_error) <= 2000", name="last_error_length"),
        CheckConstraint("ignored_reason IS NULL OR char_length(ignored_reason) <= 200", name="ignored_reason_length"),
        Index(
            "ix_webhook_events_status_received_at",
            "status",
            "received_at",
            postgresql_where=text("status IN ('received', 'failed')"),
        ),
        Index("ix_webhook_events_provider_event_type_received_at", "provider", "event_type", "received_at"),
        Index("ix_webhook_events_received_at", "received_at"),
    )

    provider: Mapped[str]
    event_id: Mapped[str]
    event_type: Mapped[str]
    event_created_at: Mapped[datetime | None]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(server_default=text("'received'"))
    attempts: Mapped[int] = mapped_column(server_default="0")
    last_error: Mapped[str | None]
    ignored_reason: Mapped[str | None]
    received_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    processed_at: Mapped[datetime | None]


class ReconciliationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "billing_reconciliation_runs"
    __table_args__ = (
        CheckConstraint("type IN ('pending_orders', 'subscriptions', 'settlement')", name="type"),
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="status"),
        CheckConstraint(
            "(period_start IS NULL) = (period_end IS NULL) AND (period_start IS NULL OR period_end > period_start)",
            name="period",
        ),
        CheckConstraint(
            "checked_count >= 0 AND repaired_count >= 0 AND mismatch_count >= 0", name="counts_non_negative"
        ),
        CheckConstraint("(status = 'running') = (finished_at IS NULL)", name="finished_consistent"),
        CheckConstraint("jsonb_typeof(summary) = 'object'", name="summary_object"),
        CheckConstraint(
            "report_storage_key IS NULL OR char_length(report_storage_key) <= 512", name="report_storage_key_length"
        ),
        CheckConstraint("error IS NULL OR char_length(error) <= 2000", name="error_length"),
        Index(
            "uq_billing_reconciliation_runs_settlement_period",
            "period_start",
            unique=True,
            postgresql_where=text("type = 'settlement'"),
        ),
        Index("ix_billing_reconciliation_runs_type_created_at", "type", "created_at"),
        Index(
            "ix_billing_reconciliation_runs_mismatches",
            "created_at",
            postgresql_where=text("mismatch_count > 0"),
        ),
    )

    type: Mapped[str]
    period_start: Mapped[datetime | None]
    period_end: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(server_default=text("'running'"))
    checked_count: Mapped[int] = mapped_column(server_default="0")
    repaired_count: Mapped[int] = mapped_column(server_default="0")
    mismatch_count: Mapped[int] = mapped_column(server_default="0")
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    report_storage_key: Mapped[str | None]
    error: Mapped[str | None]
    started_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    finished_at: Mapped[datetime | None]
