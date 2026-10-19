from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

CREATE_PRODUCT_GUARD = """
CREATE FUNCTION forbid_used_product_financial_change() RETURNS trigger
LANGUAGE plpgsql AS $guard$
BEGIN
    IF NEW.kind IS NOT DISTINCT FROM OLD.kind
        AND NEW.price_paise IS NOT DISTINCT FROM OLD.price_paise
        AND NEW.currency IS NOT DISTINCT FROM OLD.currency
        AND NEW.interval IS NOT DISTINCT FROM OLD.interval
        AND NEW.credits_granted IS NOT DISTINCT FROM OLD.credits_granted
        AND (OLD.razorpay_plan_id IS NULL OR NEW.razorpay_plan_id IS NOT DISTINCT FROM OLD.razorpay_plan_id)
    THEN
        RETURN NEW;
    END IF;
    IF EXISTS (SELECT 1 FROM orders WHERE product_id = OLD.id)
        OR EXISTS (
            SELECT 1 FROM subscriptions WHERE product_id = OLD.id OR pending_product_id = OLD.id
        )
    THEN
        RAISE EXCEPTION 'product % is financially immutable once an order or subscription references it', OLD.code
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END
$guard$
"""

CREATE_PRODUCT_TRIGGER = """
CREATE TRIGGER trg_products_financial_immutable
BEFORE UPDATE ON products
FOR EACH ROW EXECUTE FUNCTION forbid_used_product_financial_change()
"""

LIVE_SUBSCRIPTION_STATUSES = "('authenticated', 'active', 'pending', 'halted', 'paused')"

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

BILLING_PERMISSIONS = (
    ("billing.read", "Read products, orders, payments, subscriptions, refunds and webhook events"),
    ("billing.products.manage", "Create, edit, version and activate products"),
    ("billing.refunds.create", "Refund payments"),
    ("billing.credits.adjust", "Grant or remove credits for a user"),
    ("billing.webhooks.manage", "Replay and inspect webhook events"),
)
INSERT_ADMIN_BILLING_PERMISSIONS = (
    "INSERT INTO role_permissions (role_id, permission_id) "
    "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
    "WHERE roles.key = 'admin' AND permissions.key LIKE 'billing.%' "
    "AND permissions.key NOT IN ('billing.refunds.create', 'billing.credits.adjust')"
)


def timestamps() -> list[sa.Column[datetime]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def created_at() -> sa.Column[datetime]:
    return sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def create_products() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("plan_key", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price_paise", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.CHAR(3), server_default=sa.text("'INR'"), nullable=False),
        sa.Column("interval", sa.Text(), nullable=True),
        sa.Column("credits_granted", sa.BigInteger(), nullable=False),
        sa.Column("razorpay_plan_id", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_sample", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("supersedes_product_id", sa.Uuid(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "features", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        *timestamps(),
        sa.CheckConstraint("kind IN ('subscription', 'credit_pack')", name=op.f("ck_products_kind")),
        sa.CheckConstraint("price_paise > 0", name=op.f("ck_products_price_paise_positive")),
        sa.CheckConstraint("credits_granted > 0", name=op.f("ck_products_credits_granted_positive")),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_products_currency_format")),
        sa.CheckConstraint("interval IS NULL OR interval IN ('month', 'year')", name=op.f("ck_products_interval")),
        sa.CheckConstraint(
            "(kind = 'subscription' AND interval IS NOT NULL AND plan_key IS NOT NULL) "
            "OR (kind = 'credit_pack' AND interval IS NULL AND plan_key IS NULL AND razorpay_plan_id IS NULL)",
            name=op.f("ck_products_shape"),
        ),
        sa.CheckConstraint(
            "kind <> 'subscription' OR NOT is_active OR razorpay_plan_id IS NOT NULL",
            name=op.f("ck_products_active_subscription_has_plan"),
        ),
        sa.CheckConstraint(
            "code ~ '^[a-z0-9]+(_[a-z0-9]+)*$' AND char_length(code) <= 60", name=op.f("ck_products_code_format")
        ),
        sa.CheckConstraint(
            "plan_key IS NULL OR plan_key ~ '^[a-z0-9]+(_[a-z0-9]+)*$'", name=op.f("ck_products_plan_key_format")
        ),
        sa.CheckConstraint("char_length(name) BETWEEN 1 AND 80", name=op.f("ck_products_name_length")),
        sa.CheckConstraint(
            "description IS NULL OR char_length(description) <= 500", name=op.f("ck_products_description_length")
        ),
        sa.CheckConstraint("jsonb_typeof(features) = 'array'", name=op.f("ck_products_features_array")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_products_version_positive")),
        sa.CheckConstraint(
            "supersedes_product_id IS NULL OR supersedes_product_id <> id", name=op.f("ck_products_not_own_predecessor")
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_product_id"],
            ["products.id"],
            name=op.f("fk_products_supersedes_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("code", name=op.f("uq_products_code")),
        sa.UniqueConstraint("razorpay_plan_id", name=op.f("uq_products_razorpay_plan_id")),
    )
    op.create_index(
        op.f("ix_products_kind_sort_order"),
        "products",
        ["kind", "sort_order"],
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        op.f("ix_products_plan_key_interval_active"),
        "products",
        ["plan_key", "interval"],
        unique=True,
        postgresql_where=sa.text("is_active AND kind = 'subscription'"),
    )
    op.create_index(op.f("ix_products_supersedes_product_id"), "products", ["supersedes_product_id"])


def create_billing_customers() -> None:
    op.create_table(
        "billing_customers",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("razorpay_customer_id", sa.Text(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_billing_customers_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_billing_customers")),
        sa.UniqueConstraint("razorpay_customer_id", name=op.f("uq_billing_customers_razorpay_customer_id")),
    )


def create_subscriptions() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("pending_product_id", sa.Uuid(), nullable=True),
        sa.Column("razorpay_subscription_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'created'"), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("paid_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_charge_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('created', 'authenticated', 'active', 'pending', 'halted', 'paused', "
            "'cancelled', 'completed', 'expired')",
            name=op.f("ck_subscriptions_status"),
        ),
        sa.CheckConstraint(
            "current_period_end IS NULL OR current_period_start IS NULL OR current_period_end > current_period_start",
            name=op.f("ck_subscriptions_period_order"),
        ),
        sa.CheckConstraint("total_count > 0", name=op.f("ck_subscriptions_total_count_positive")),
        sa.CheckConstraint("paid_count >= 0", name=op.f("ck_subscriptions_paid_count_non_negative")),
        sa.CheckConstraint(
            "(status IN ('cancelled', 'completed', 'expired')) = (ended_at IS NOT NULL)",
            name=op.f("ck_subscriptions_ended_consistent"),
        ),
        sa.CheckConstraint(
            "status = 'created' OR razorpay_subscription_id IS NOT NULL",
            name=op.f("ck_subscriptions_live_has_razorpay_id"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_subscriptions_user_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name=op.f("fk_subscriptions_product_id_products"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["pending_product_id"],
            ["products.id"],
            name=op.f("fk_subscriptions_pending_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
        sa.UniqueConstraint("razorpay_subscription_id", name=op.f("uq_subscriptions_razorpay_subscription_id")),
    )
    op.create_index(
        op.f("ix_subscriptions_user_id_live"),
        "subscriptions",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN {LIVE_SUBSCRIPTION_STATUSES}"),
    )
    op.create_index(op.f("ix_subscriptions_user_id_created_at"), "subscriptions", ["user_id", "created_at"])
    op.create_index(op.f("ix_subscriptions_product_id"), "subscriptions", ["product_id"])
    op.create_index(op.f("ix_subscriptions_pending_product_id"), "subscriptions", ["pending_product_id"])
    op.create_index(
        op.f("ix_subscriptions_status_current_period_end"),
        "subscriptions",
        ["status", "current_period_end"],
        postgresql_where=sa.text(f"status IN {LIVE_SUBSCRIPTION_STATUSES}"),
    )


def create_orders() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("product_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.CHAR(3), server_default=sa.text("'INR'"), nullable=False),
        sa.Column("credits_granted", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'created'"), nullable=False),
        sa.Column("razorpay_order_id", sa.Text(), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("receipt", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("flagged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("flag_reason", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('created', 'pending', 'paid', 'failed', 'expired', 'cancelled')",
            name=op.f("ck_orders_status"),
        ),
        sa.CheckConstraint("kind IN ('credit_pack', 'subscription')", name=op.f("ck_orders_kind")),
        sa.CheckConstraint(
            "(kind = 'subscription') = (subscription_id IS NOT NULL)", name=op.f("ck_orders_subscription_consistent")
        ),
        sa.CheckConstraint("amount_paise > 0", name=op.f("ck_orders_amount_paise_positive")),
        sa.CheckConstraint("credits_granted > 0", name=op.f("ck_orders_credits_granted_positive")),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_orders_currency_format")),
        sa.CheckConstraint("(status = 'paid') = (paid_at IS NOT NULL)", name=op.f("ck_orders_paid_consistent")),
        sa.CheckConstraint("(flagged_at IS NULL) = (flag_reason IS NULL)", name=op.f("ck_orders_flag_consistent")),
        sa.CheckConstraint(
            "flag_reason IS NULL OR flag_reason IN ('amount_mismatch', 'currency_mismatch', 'duplicate_payment')",
            name=op.f("ck_orders_flag_reason"),
        ),
        sa.CheckConstraint("char_length(receipt) <= 40", name=op.f("ck_orders_receipt_length")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_orders_user_id_users"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"], name=op.f("fk_orders_product_id_products"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_orders_subscription_id_subscriptions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint("razorpay_order_id", name=op.f("uq_orders_razorpay_order_id")),
        sa.UniqueConstraint("receipt", name=op.f("uq_orders_receipt")),
        sa.UniqueConstraint("user_id", "idempotency_key", name=op.f("uq_orders_user_id_idempotency_key")),
    )
    op.create_index(op.f("ix_orders_user_id_created_at"), "orders", ["user_id", "created_at"])
    op.create_index(op.f("ix_orders_product_id"), "orders", ["product_id"])
    op.create_index(op.f("ix_orders_subscription_id"), "orders", ["subscription_id"])
    op.create_index(
        op.f("ix_orders_status_created_at"),
        "orders",
        ["status", "created_at"],
        postgresql_where=sa.text("status IN ('created', 'pending') AND flagged_at IS NULL"),
    )
    op.create_index(
        op.f("ix_orders_flagged_at"),
        "orders",
        ["flagged_at"],
        postgresql_where=sa.text("flagged_at IS NOT NULL"),
    )


def create_payments() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("subscription_id", sa.Uuid(), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("razorpay_payment_id", sa.Text(), nullable=False),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.CHAR(3), server_default=sa.text("'INR'"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=True),
        sa.Column("fee_paise", sa.BigInteger(), nullable=True),
        sa.Column("tax_paise", sa.BigInteger(), nullable=True),
        sa.Column("credits_granted", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("refunded_paise", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_description", sa.Text(), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('authorized', 'captured', 'failed', 'refunded', 'partially_refunded')",
            name=op.f("ck_payments_status"),
        ),
        sa.CheckConstraint("num_nonnulls(order_id, subscription_id) >= 1", name=op.f("ck_payments_has_parent")),
        sa.CheckConstraint("amount_paise > 0", name=op.f("ck_payments_amount_paise_positive")),
        sa.CheckConstraint("credits_granted >= 0", name=op.f("ck_payments_credits_granted_non_negative")),
        sa.CheckConstraint("refunded_paise BETWEEN 0 AND amount_paise", name=op.f("ck_payments_refunded_paise_range")),
        sa.CheckConstraint("fee_paise IS NULL OR fee_paise >= 0", name=op.f("ck_payments_fee_paise_non_negative")),
        sa.CheckConstraint("tax_paise IS NULL OR tax_paise >= 0", name=op.f("ck_payments_tax_paise_non_negative")),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_payments_currency_format")),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_payments_order_id_orders"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_payments_subscription_id_subscriptions"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_payments_user_id_users"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_payments")),
        sa.UniqueConstraint("razorpay_payment_id", name=op.f("uq_payments_razorpay_payment_id")),
    )
    op.create_index(op.f("ix_payments_order_id"), "payments", ["order_id"])
    op.create_index(op.f("ix_payments_subscription_id"), "payments", ["subscription_id"])
    op.create_index(op.f("ix_payments_user_id_created_at"), "payments", ["user_id", "created_at"])
    op.create_index(op.f("ix_payments_created_at"), "payments", ["created_at"])


def create_refunds() -> None:
    op.create_table(
        "refunds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("razorpay_refund_id", sa.Text(), nullable=True),
        sa.Column("amount_paise", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("initiated_by", sa.Uuid(), nullable=True),
        sa.Column("credits_clawed_back", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint("status IN ('pending', 'processed', 'failed')", name=op.f("ck_refunds_status")),
        sa.CheckConstraint("amount_paise > 0", name=op.f("ck_refunds_amount_paise_positive")),
        sa.CheckConstraint("credits_clawed_back >= 0", name=op.f("ck_refunds_credits_clawed_back_non_negative")),
        sa.CheckConstraint(
            "(status = 'processed') = (processed_at IS NOT NULL)", name=op.f("ck_refunds_processed_consistent")
        ),
        sa.CheckConstraint("char_length(reason) BETWEEN 1 AND 500", name=op.f("ck_refunds_reason_length")),
        sa.CheckConstraint(
            "char_length(idempotency_key) BETWEEN 1 AND 200", name=op.f("ck_refunds_idempotency_key_length")
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"], ["payments.id"], name=op.f("fk_refunds_payment_id_payments"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["initiated_by"], ["users.id"], name=op.f("fk_refunds_initiated_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refunds")),
        sa.UniqueConstraint("razorpay_refund_id", name=op.f("uq_refunds_razorpay_refund_id")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_refunds_idempotency_key")),
    )
    op.create_index(op.f("ix_refunds_payment_id"), "refunds", ["payment_id"])
    op.create_index(op.f("ix_refunds_initiated_by"), "refunds", ["initiated_by"])


def create_webhook_events() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("event_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'received'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("ignored_reason", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('received', 'processing', 'processed', 'failed', 'ignored')",
            name=op.f("ck_webhook_events_status"),
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_webhook_events_attempts_non_negative")),
        sa.CheckConstraint("provider ~ '^[a-z][a-z0-9_]{1,39}$'", name=op.f("ck_webhook_events_provider_format")),
        sa.CheckConstraint(
            "last_error IS NULL OR char_length(last_error) <= 2000", name=op.f("ck_webhook_events_last_error_length")
        ),
        sa.CheckConstraint(
            "ignored_reason IS NULL OR char_length(ignored_reason) <= 200",
            name=op.f("ck_webhook_events_ignored_reason_length"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_events")),
        sa.UniqueConstraint("provider", "event_id", name=op.f("uq_webhook_events_provider_event_id")),
    )
    op.create_index(
        op.f("ix_webhook_events_status_received_at"),
        "webhook_events",
        ["status", "received_at"],
        postgresql_where=sa.text("status IN ('received', 'failed')"),
    )
    op.create_index(
        op.f("ix_webhook_events_provider_event_type_received_at"),
        "webhook_events",
        ["provider", "event_type", "received_at"],
    )
    op.create_index(op.f("ix_webhook_events_received_at"), "webhook_events", ["received_at"])


def create_billing_reconciliation_runs() -> None:
    op.create_table(
        "billing_reconciliation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'running'"), nullable=False),
        sa.Column("checked_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("repaired_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mismatch_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "summary", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("report_storage_key", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "type IN ('pending_orders', 'subscriptions', 'settlement')",
            name=op.f("ck_billing_reconciliation_runs_type"),
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name=op.f("ck_billing_reconciliation_runs_status")
        ),
        sa.CheckConstraint(
            "(period_start IS NULL) = (period_end IS NULL) AND (period_start IS NULL OR period_end > period_start)",
            name=op.f("ck_billing_reconciliation_runs_period"),
        ),
        sa.CheckConstraint(
            "checked_count >= 0 AND repaired_count >= 0 AND mismatch_count >= 0",
            name=op.f("ck_billing_reconciliation_runs_counts_non_negative"),
        ),
        sa.CheckConstraint(
            "(status = 'running') = (finished_at IS NULL)",
            name=op.f("ck_billing_reconciliation_runs_finished_consistent"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(summary) = 'object'", name=op.f("ck_billing_reconciliation_runs_summary_object")
        ),
        sa.CheckConstraint(
            "report_storage_key IS NULL OR char_length(report_storage_key) <= 512",
            name=op.f("ck_billing_reconciliation_runs_report_storage_key_length"),
        ),
        sa.CheckConstraint(
            "error IS NULL OR char_length(error) <= 2000", name=op.f("ck_billing_reconciliation_runs_error_length")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_billing_reconciliation_runs")),
    )
    op.create_index(
        op.f("uq_billing_reconciliation_runs_settlement_period"),
        "billing_reconciliation_runs",
        ["period_start"],
        unique=True,
        postgresql_where=sa.text("type = 'settlement'"),
    )
    op.create_index(
        op.f("ix_billing_reconciliation_runs_type_created_at"),
        "billing_reconciliation_runs",
        ["type", "created_at"],
    )
    op.create_index(
        op.f("ix_billing_reconciliation_runs_mismatches"),
        "billing_reconciliation_runs",
        ["created_at"],
        postgresql_where=sa.text("mismatch_count > 0"),
    )


def create_credit_wallets() -> None:
    op.create_table(
        "credit_wallets",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("balance", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reserved", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="0", nullable=False),
        *timestamps(),
        sa.CheckConstraint("balance >= 0", name=op.f("ck_credit_wallets_balance_non_negative")),
        sa.CheckConstraint("reserved >= 0 AND reserved <= balance", name=op.f("ck_credit_wallets_reserved_range")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_credit_wallets_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_credit_wallets")),
    )


def create_credit_lots() -> None:
    op.create_table(
        "credit_lots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("remaining", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ref_type", sa.Text(), nullable=True),
        sa.Column("ref_id", sa.Uuid(), nullable=True),
        sa.Column("expiry_reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "source IN ('purchase', 'subscription', 'admin', 'promo')", name=op.f("ck_credit_lots_source")
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_credit_lots_amount_positive")),
        sa.CheckConstraint("remaining BETWEEN 0 AND amount", name=op.f("ck_credit_lots_remaining_range")),
        sa.CheckConstraint(
            "ref_type IS NULL OR ref_type IN ('payment', 'admin', 'promo')", name=op.f("ck_credit_lots_ref_type")
        ),
        sa.CheckConstraint("(ref_type IS NULL) = (ref_id IS NULL)", name=op.f("ck_credit_lots_ref_consistent")),
        sa.CheckConstraint("expired_at IS NULL OR remaining = 0", name=op.f("ck_credit_lots_expired_consistent")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_credit_lots_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_lots")),
    )
    op.create_index(
        op.f("uq_credit_lots_source_ref"),
        "credit_lots",
        ["source", "ref_type", "ref_id"],
        unique=True,
        postgresql_where=sa.text("ref_id IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_credit_lots_user_id_consumption"),
        "credit_lots",
        ["user_id", "expires_at", "created_at", "id"],
        postgresql_where=sa.text("remaining > 0"),
    )
    op.create_index(
        op.f("ix_credit_lots_expires_at"),
        "credit_lots",
        ["expires_at"],
        postgresql_where=sa.text("remaining > 0 AND expires_at IS NOT NULL"),
    )


def create_credit_reservations() -> None:
    op.create_table(
        "credit_reservations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("ref_type", sa.Text(), nullable=False),
        sa.Column("ref_id", sa.Uuid(), nullable=False),
        sa.Column("committed_amount", sa.BigInteger(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('active', 'committed', 'released', 'expired')", name=op.f("ck_credit_reservations_status")
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_credit_reservations_amount_positive")),
        sa.CheckConstraint(
            "committed_amount IS NULL OR committed_amount BETWEEN 0 AND amount",
            name=op.f("ck_credit_reservations_committed_range"),
        ),
        sa.CheckConstraint(
            "(status = 'committed') = (committed_amount IS NOT NULL)",
            name=op.f("ck_credit_reservations_committed_consistent"),
        ),
        sa.CheckConstraint(
            "(status = 'active') = (settled_at IS NULL)", name=op.f("ck_credit_reservations_settled_consistent")
        ),
        sa.CheckConstraint("ref_type ~ '^[a-z][a-z0-9_]{1,39}$'", name=op.f("ck_credit_reservations_ref_type_format")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_credit_reservations_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_reservations")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_credit_reservations_idempotency_key")),
    )
    op.create_index(
        op.f("uq_credit_reservations_active_ref"),
        "credit_reservations",
        ["ref_type", "ref_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(op.f("ix_credit_reservations_user_id_created_at"), "credit_reservations", ["user_id", "created_at"])
    op.create_index(
        op.f("ix_credit_reservations_expires_at"),
        "credit_reservations",
        ["expires_at"],
        postgresql_where=sa.text("status = 'active'"),
    )


def create_credit_ledger() -> None:
    op.create_table(
        "credit_ledger",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("delta", sa.BigInteger(), nullable=False),
        sa.Column("reserved_delta", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("balance_after", sa.BigInteger(), nullable=False),
        sa.Column("reserved_after", sa.BigInteger(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("ref_type", sa.Text(), nullable=True),
        sa.Column("ref_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        created_at(),
        sa.CheckConstraint(
            "reason IN ('purchase', 'subscription_grant', 'promo_grant', 'admin_adjust', 'reserve', 'commit', "
            "'release', 'refund_clawback', 'expiry')",
            name=op.f("ck_credit_ledger_reason"),
        ),
        sa.CheckConstraint("delta <> 0 OR reserved_delta <> 0", name=op.f("ck_credit_ledger_moves_credits")),
        sa.CheckConstraint(LEDGER_REASON_DELTAS, name=op.f("ck_credit_ledger_reason_deltas")),
        sa.CheckConstraint(
            "balance_after >= 0 AND reserved_after >= 0 AND reserved_after <= balance_after",
            name=op.f("ck_credit_ledger_after_range"),
        ),
        sa.CheckConstraint(
            "ref_type IS NULL OR ref_type IN ('payment', 'refund', 'reservation', 'lot', 'admin', 'promo')",
            name=op.f("ck_credit_ledger_ref_type"),
        ),
        sa.CheckConstraint("(ref_type IS NULL) = (ref_id IS NULL)", name=op.f("ck_credit_ledger_ref_consistent")),
        sa.CheckConstraint("jsonb_typeof(metadata) = 'object'", name=op.f("ck_credit_ledger_metadata_object")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_credit_ledger_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_ledger")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_credit_ledger_idempotency_key")),
    )
    op.create_index(op.f("ix_credit_ledger_user_id_created_at_id"), "credit_ledger", ["user_id", "created_at", "id"])
    op.create_index(op.f("ix_credit_ledger_ref_type_ref_id"), "credit_ledger", ["ref_type", "ref_id"])
    op.execute(
        "CREATE TRIGGER trg_credit_ledger_append_only BEFORE UPDATE OR DELETE ON credit_ledger "
        "FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation()"
    )


def create_usage_records() -> None:
    op.create_table(
        "usage_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("publication_id", sa.Uuid(), nullable=True),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("audio_characters", sa.Integer(), server_default="0", nullable=False),
        sa.Column("render_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_micros_usd", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("credits", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        created_at(),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND audio_characters >= 0 AND render_ms >= 0 "
            "AND cost_micros_usd >= 0 AND credits >= 0",
            name=op.f("ck_usage_records_counters_non_negative"),
        ),
        sa.CheckConstraint("stage ~ '^[a-z][a-z0-9_]{1,39}$'", name=op.f("ck_usage_records_stage_format")),
        sa.CheckConstraint("provider ~ '^[a-z][a-z0-9_]{1,39}$'", name=op.f("ck_usage_records_provider_format")),
        sa.CheckConstraint("model IS NULL OR char_length(model) <= 100", name=op.f("ck_usage_records_model_length")),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_usage_records_user_id_users"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_records")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_usage_records_idempotency_key")),
    )
    op.create_index(op.f("ix_usage_records_user_id_created_at"), "usage_records", ["user_id", "created_at"])
    op.create_index(op.f("ix_usage_records_job_id"), "usage_records", ["job_id"])
    op.create_index(op.f("ix_usage_records_publication_id"), "usage_records", ["publication_id"])
    op.create_index(op.f("ix_usage_records_provider_created_at"), "usage_records", ["provider", "created_at"])
    op.execute(
        "CREATE TRIGGER trg_usage_records_append_only BEFORE UPDATE OR DELETE ON usage_records "
        "FOR EACH ROW EXECUTE FUNCTION forbid_append_only_mutation()"
    )


def seed_permissions() -> None:
    permission_table = sa.table(
        "permissions",
        sa.column("id", sa.Uuid()),
        sa.column("key", sa.Text()),
        sa.column("description", sa.Text()),
    )
    op.bulk_insert(
        permission_table,
        [
            {
                "id": UUID(f"0199eb00-0000-7000-8000-{index:012d}"),
                "key": key,
                "description": description,
            }
            for index, (key, description) in enumerate(BILLING_PERMISSIONS, start=12)
        ],
    )
    op.execute(INSERT_ADMIN_BILLING_PERMISSIONS)


def upgrade() -> None:
    create_products()
    create_billing_customers()
    create_subscriptions()
    create_orders()
    create_payments()
    create_refunds()
    create_webhook_events()
    create_billing_reconciliation_runs()
    create_credit_wallets()
    create_credit_lots()
    create_credit_reservations()
    create_credit_ledger()
    create_usage_records()
    op.execute(CREATE_PRODUCT_GUARD)
    op.execute(CREATE_PRODUCT_TRIGGER)
    seed_permissions()


def downgrade() -> None:
    op.execute("DELETE FROM permissions WHERE key LIKE 'billing.%'")
    op.execute("DROP TRIGGER IF EXISTS trg_products_financial_immutable ON products")
    op.execute("DROP FUNCTION IF EXISTS forbid_used_product_financial_change()")
    op.execute("DROP TRIGGER IF EXISTS trg_usage_records_append_only ON usage_records")
    op.drop_table("usage_records")
    op.execute("DROP TRIGGER IF EXISTS trg_credit_ledger_append_only ON credit_ledger")
    op.drop_table("credit_ledger")
    op.drop_table("credit_reservations")
    op.drop_table("credit_lots")
    op.drop_table("credit_wallets")
    op.drop_table("billing_reconciliation_runs")
    op.drop_table("webhook_events")
    op.drop_table("refunds")
    op.drop_table("payments")
    op.drop_table("orders")
    op.drop_table("subscriptions")
    op.drop_table("billing_customers")
    op.drop_table("products")
