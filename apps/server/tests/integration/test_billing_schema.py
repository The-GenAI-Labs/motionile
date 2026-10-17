from collections.abc import Generator, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import DBAPIError

from motionile.core.config import PSYCOPG_SCHEME, with_driver
from motionile.models import metadata
from motionile.modules.access import PERMISSION_KEYS

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
BILLING_PERMISSION_KEYS = {
    "billing.read",
    "billing.products.manage",
    "billing.refunds.create",
    "billing.credits.adjust",
    "billing.webhooks.manage",
}
ADMIN_BILLING_PERMISSION_KEYS = {"billing.read", "billing.products.manage", "billing.webhooks.manage"}


@pytest.fixture
def connection(migrated_database_url: str) -> Iterator[Connection]:
    engine = create_engine(with_driver(migrated_database_url, PSYCOPG_SCHEME))
    with engine.connect() as opened:
        transaction = opened.begin()
        yield opened
        transaction.rollback()
    engine.dispose()


@contextmanager
def rejected(connection: Connection, match: str) -> Generator[None]:
    with pytest.raises(DBAPIError, match=match), connection.begin_nested():
        yield


def token() -> str:
    return uuid4().hex


def insert(connection: Connection, table: str, **values: Any) -> UUID:
    result = connection.execute(sa.insert(metadata.tables[table]).values(**values))
    primary_key = result.inserted_primary_key
    assert primary_key is not None
    return UUID(str(primary_key[0]))


def update(connection: Connection, table: str, key: UUID, **values: Any) -> None:
    target = metadata.tables[table]
    primary_key = next(iter(target.primary_key.columns))
    connection.execute(sa.update(target).where(primary_key == key).values(**values))


def make_user(connection: Connection) -> UUID:
    return insert(connection, "users")


def make_pack(connection: Connection, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "code": f"pack_{token()[:16]}",
        "kind": "credit_pack",
        "name": "Starter",
        "price_paise": 49_900,
        "credits_granted": 100,
    }
    return insert(connection, "products", **{**values, **overrides})


def make_plan(connection: Connection, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "code": f"plan_{token()[:16]}",
        "kind": "subscription",
        "plan_key": f"key{token()[:12]}",
        "interval": "month",
        "name": "Pro monthly",
        "price_paise": 99_900,
        "credits_granted": 500,
        "razorpay_plan_id": f"plan_{token()[:14]}",
    }
    return insert(connection, "products", **{**values, **overrides})


def make_order(connection: Connection, user_id: UUID, product_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "user_id": user_id,
        "product_id": product_id,
        "product_version": 1,
        "kind": "credit_pack",
        "amount_paise": 49_900,
        "credits_granted": 100,
        "receipt": token(),
        "idempotency_key": token(),
        "expires_at": NOW + timedelta(hours=2),
    }
    return insert(connection, "orders", **{**values, **overrides})


def make_subscription(connection: Connection, user_id: UUID, product_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "user_id": user_id,
        "product_id": product_id,
        "razorpay_subscription_id": f"sub_{token()}",
        "total_count": 120,
        "status": "active",
    }
    return insert(connection, "subscriptions", **{**values, **overrides})


def make_payment(connection: Connection, user_id: UUID, order_id: UUID | None, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "order_id": order_id,
        "user_id": user_id,
        "razorpay_payment_id": f"pay_{token()}",
        "amount_paise": 49_900,
        "status": "captured",
    }
    return insert(connection, "payments", **{**values, **overrides})


def make_lot(connection: Connection, user_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {"user_id": user_id, "source": "purchase", "amount": 100, "remaining": 100}
    return insert(connection, "credit_lots", **{**values, **overrides})


def make_reservation(connection: Connection, user_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "user_id": user_id,
        "amount": 10,
        "ref_type": "job",
        "ref_id": uuid4(),
        "idempotency_key": token(),
        "expires_at": NOW + timedelta(hours=1),
    }
    return insert(connection, "credit_reservations", **{**values, **overrides})


def make_ledger_entry(
    connection: Connection, user_id: UUID, reason: str, delta: int, reserved_delta: int, **overrides: Any
) -> UUID:
    values: dict[str, Any] = {
        "user_id": user_id,
        "delta": delta,
        "reserved_delta": reserved_delta,
        "balance_after": 100,
        "reserved_after": 10,
        "reason": reason,
        "idempotency_key": token(),
    }
    return insert(connection, "credit_ledger", **{**values, **overrides})


def make_usage_record(connection: Connection, user_id: UUID, **overrides: Any) -> UUID:
    values: dict[str, Any] = {
        "user_id": user_id,
        "stage": "storyboard",
        "provider": "anthropic",
        "idempotency_key": token(),
    }
    return insert(connection, "usage_records", **{**values, **overrides})


VALID_LEDGER_ENTRIES = [
    ("purchase", 10, 0),
    ("subscription_grant", 10, 0),
    ("promo_grant", 10, 0),
    ("admin_adjust", 10, 0),
    ("admin_adjust", -10, 0),
    ("reserve", 0, 5),
    ("commit", -5, -10),
    ("commit", 0, -10),
    ("release", 0, -5),
    ("refund_clawback", -5, 0),
    ("expiry", -5, 0),
]
INVALID_LEDGER_ENTRIES = [
    ("purchase", -10, 0),
    ("purchase", 10, 5),
    ("purchase", 0, 5),
    ("subscription_grant", -10, 0),
    ("subscription_grant", 10, -5),
    ("promo_grant", -10, 0),
    ("promo_grant", 10, 5),
    ("admin_adjust", 10, 5),
    ("admin_adjust", -10, -5),
    ("admin_adjust", 0, 5),
    ("reserve", 5, 5),
    ("reserve", 0, -5),
    ("reserve", -5, 5),
    ("commit", 5, -10),
    ("commit", -5, 0),
    ("commit", -5, 5),
    ("commit", 0, 5),
    ("release", -5, -5),
    ("release", 5, -5),
    ("release", 0, 5),
    ("refund_clawback", 5, 0),
    ("refund_clawback", -5, -5),
    ("refund_clawback", -5, 5),
    ("expiry", 5, 0),
    ("expiry", -5, -5),
    ("expiry", 0, 5),
]


@pytest.mark.parametrize(("reason", "delta", "reserved_delta"), VALID_LEDGER_ENTRIES)
def test_ledger_accepts_the_sign_combinations_of_each_reason(
    connection: Connection, reason: str, delta: int, reserved_delta: int
) -> None:
    user_id = make_user(connection)

    entry_id = make_ledger_entry(connection, user_id, reason, delta, reserved_delta)

    assert isinstance(entry_id, UUID)


@pytest.mark.parametrize(("reason", "delta", "reserved_delta"), INVALID_LEDGER_ENTRIES)
def test_ledger_rejects_the_sign_combinations_a_reason_forbids(
    connection: Connection, reason: str, delta: int, reserved_delta: int
) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_credit_ledger_reason_deltas"):
        make_ledger_entry(connection, user_id, reason, delta, reserved_delta)


@pytest.mark.parametrize("reason", ["purchase", "reserve", "admin_adjust", "release", "expiry"])
def test_ledger_entry_must_move_credits(connection: Connection, reason: str) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_credit_ledger_moves_credits"):
        make_ledger_entry(connection, user_id, reason, 0, 0)


def test_ledger_rejects_unknown_reasons(connection: Connection) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_credit_ledger_reason"):
        make_ledger_entry(connection, user_id, "bonus", 10, 0)


@pytest.mark.parametrize(
    ("balance_after", "reserved_after"),
    [(-1, 0), (10, -1), (10, 11)],
)
def test_ledger_snapshots_stay_in_range(connection: Connection, balance_after: int, reserved_after: int) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_credit_ledger_after_range"):
        make_ledger_entry(
            connection, user_id, "purchase", 10, 0, balance_after=balance_after, reserved_after=reserved_after
        )


def test_ledger_reference_needs_both_parts(connection: Connection) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_credit_ledger_ref_consistent"):
        make_ledger_entry(connection, user_id, "purchase", 10, 0, ref_type="payment")
    with rejected(connection, "ck_credit_ledger_ref_type"):
        make_ledger_entry(connection, user_id, "purchase", 10, 0, ref_type="invoice", ref_id=uuid4())


def test_ledger_idempotency_key_is_unique(connection: Connection) -> None:
    user_id = make_user(connection)
    make_ledger_entry(connection, user_id, "purchase", 10, 0, idempotency_key="payment:1")

    with rejected(connection, "uq_credit_ledger_idempotency_key"):
        make_ledger_entry(connection, user_id, "purchase", 10, 0, idempotency_key="payment:1")


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE credit_ledger SET delta = delta + 1 WHERE id = :id",
        "UPDATE credit_ledger SET reason = 'expiry' WHERE id = :id",
        "DELETE FROM credit_ledger WHERE id = :id",
    ],
)
def test_ledger_is_append_only(connection: Connection, statement: str) -> None:
    entry_id = make_ledger_entry(connection, make_user(connection), "purchase", 10, 0)

    with rejected(connection, "credit_ledger is append-only"):
        connection.execute(text(statement), {"id": entry_id})


def test_ledger_rows_can_only_be_purged_explicitly(connection: Connection) -> None:
    entry_id = make_ledger_entry(connection, make_user(connection), "purchase", 10, 0)

    connection.execute(text("SET LOCAL motionile.allow_purge = 'on'"))
    deleted = connection.execute(text("DELETE FROM credit_ledger WHERE id = :id"), {"id": entry_id}).rowcount

    assert deleted == 1


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE usage_records SET credits = credits + 1 WHERE id = :id",
        "DELETE FROM usage_records WHERE id = :id",
    ],
)
def test_usage_records_are_append_only(connection: Connection, statement: str) -> None:
    record_id = make_usage_record(connection, make_user(connection))

    with rejected(connection, "usage_records is append-only"):
        connection.execute(text(statement), {"id": record_id})


def test_usage_records_reject_negative_counters_and_duplicate_keys(connection: Connection) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_usage_records_counters_non_negative"):
        make_usage_record(connection, user_id, input_tokens=-1)
    with rejected(connection, "ck_usage_records_stage_format"):
        make_usage_record(connection, user_id, stage="Render")
    make_usage_record(connection, user_id, idempotency_key="stage:1")
    with rejected(connection, "uq_usage_records_idempotency_key"):
        make_usage_record(connection, user_id, idempotency_key="stage:1")


def test_usage_records_accept_job_and_publication_ids_without_foreign_keys(connection: Connection) -> None:
    record_id = make_usage_record(connection, make_user(connection), job_id=uuid4(), publication_id=uuid4())

    assert isinstance(record_id, UUID)


def test_wallet_reserved_credits_never_exceed_the_balance(connection: Connection) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_credit_wallets_reserved_range"):
        insert(connection, "credit_wallets", user_id=user_id, balance=10, reserved=11)
    insert(connection, "credit_wallets", user_id=user_id, balance=10, reserved=10)
    with rejected(connection, "ck_credit_wallets_reserved_range"):
        update(connection, "credit_wallets", user_id, balance=9)
    with rejected(connection, "ck_credit_wallets_reserved_range"):
        update(connection, "credit_wallets", user_id, reserved=-1)


def test_wallet_balance_cannot_be_negative(connection: Connection) -> None:
    with rejected(connection, "ck_credit_wallets_balance_non_negative"):
        insert(connection, "credit_wallets", user_id=make_user(connection), balance=-1, reserved=0)


@pytest.mark.parametrize(("amount", "remaining"), [(100, 101), (100, -1), (0, 0)])
def test_lot_remaining_stays_between_zero_and_amount(connection: Connection, amount: int, remaining: int) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_credit_lots_(remaining_range|amount_positive)"):
        make_lot(connection, user_id, amount=amount, remaining=remaining)


def test_lot_accepts_boundary_remaining_values(connection: Connection) -> None:
    user_id = make_user(connection)

    make_lot(connection, user_id, amount=100, remaining=0)
    make_lot(connection, user_id, amount=100, remaining=100)


def test_lot_expiry_requires_nothing_remaining(connection: Connection) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_credit_lots_expired_consistent"):
        make_lot(connection, user_id, remaining=5, expired_at=NOW)
    make_lot(connection, user_id, remaining=0, expired_at=NOW)


def test_lot_source_and_reference_are_checked(connection: Connection) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_credit_lots_source"):
        make_lot(connection, user_id, source="gift")
    with rejected(connection, "ck_credit_lots_ref_consistent"):
        make_lot(connection, user_id, ref_type="payment")
    with rejected(connection, "ck_credit_lots_ref_type"):
        make_lot(connection, user_id, ref_type="order", ref_id=uuid4())


def test_one_lot_per_source_and_reference(connection: Connection) -> None:
    user_id = make_user(connection)
    payment_id = uuid4()
    make_lot(connection, user_id, ref_type="payment", ref_id=payment_id)

    with rejected(connection, "uq_credit_lots_source_ref"):
        make_lot(connection, user_id, ref_type="payment", ref_id=payment_id)
    make_lot(connection, user_id, source="subscription", ref_type="payment", ref_id=payment_id)
    make_lot(connection, user_id, ref_type="payment", ref_id=uuid4())


def test_lots_without_a_reference_do_not_collide(connection: Connection) -> None:
    user_id = make_user(connection)

    make_lot(connection, user_id)
    make_lot(connection, user_id)


def test_only_one_active_reservation_per_reference(connection: Connection) -> None:
    user_id = make_user(connection)
    ref_id = uuid4()
    first = make_reservation(connection, user_id, ref_id=ref_id)

    with rejected(connection, "uq_credit_reservations_active_ref"):
        make_reservation(connection, user_id, ref_id=ref_id)
    make_reservation(connection, user_id, ref_id=ref_id, ref_type="publication")
    update(connection, "credit_reservations", first, status="released", settled_at=NOW)
    make_reservation(connection, user_id, ref_id=ref_id)


def test_reservation_lifecycle_columns_stay_consistent(connection: Connection) -> None:
    user_id = make_user(connection)

    with rejected(connection, "ck_credit_reservations_settled_consistent"):
        make_reservation(connection, user_id, status="released")
    with rejected(connection, "ck_credit_reservations_settled_consistent"):
        make_reservation(connection, user_id, settled_at=NOW)
    with rejected(connection, "ck_credit_reservations_committed_consistent"):
        make_reservation(connection, user_id, status="committed", settled_at=NOW)
    with rejected(connection, "ck_credit_reservations_committed_range"):
        make_reservation(connection, user_id, status="committed", settled_at=NOW, committed_amount=11)
    make_reservation(connection, user_id, status="committed", settled_at=NOW, committed_amount=10)
    make_reservation(connection, user_id, status="expired", settled_at=NOW)


def test_reservation_idempotency_key_and_reference_type_are_checked(connection: Connection) -> None:
    user_id = make_user(connection)
    make_reservation(connection, user_id, idempotency_key="reserve:1")

    with rejected(connection, "uq_credit_reservations_idempotency_key"):
        make_reservation(connection, user_id, idempotency_key="reserve:1")
    with rejected(connection, "ck_credit_reservations_ref_type_format"):
        make_reservation(connection, user_id, ref_type="Job")


def test_one_live_subscription_per_user(connection: Connection) -> None:
    user_id = make_user(connection)
    product_id = make_plan(connection)
    first = make_subscription(connection, user_id, product_id, status="active")

    with rejected(connection, "ix_subscriptions_user_id_live"):
        make_subscription(connection, user_id, product_id, status="authenticated")
    make_subscription(connection, user_id, product_id, status="created")
    make_subscription(connection, user_id, product_id, status="cancelled", ended_at=NOW)
    make_subscription(connection, make_user(connection), product_id, status="active")
    update(connection, "subscriptions", first, status="cancelled", ended_at=NOW)
    make_subscription(connection, user_id, product_id, status="halted")


@pytest.mark.parametrize("status", ["authenticated", "active", "pending", "halted", "paused"])
def test_every_live_status_blocks_a_second_subscription(connection: Connection, status: str) -> None:
    user_id = make_user(connection)
    product_id = make_plan(connection)
    make_subscription(connection, user_id, product_id, status=status)

    with rejected(connection, "ix_subscriptions_user_id_live"):
        make_subscription(connection, user_id, product_id, status="active")


def test_subscription_end_and_period_consistency(connection: Connection) -> None:
    user_id = make_user(connection)
    product_id = make_plan(connection)

    with rejected(connection, "ck_subscriptions_ended_consistent"):
        make_subscription(connection, user_id, product_id, status="cancelled")
    with rejected(connection, "ck_subscriptions_ended_consistent"):
        make_subscription(connection, user_id, product_id, status="active", ended_at=NOW)
    with rejected(connection, "ck_subscriptions_period_order"):
        make_subscription(
            connection, user_id, product_id, current_period_start=NOW, current_period_end=NOW - timedelta(days=1)
        )
    with rejected(connection, "ck_subscriptions_status"):
        make_subscription(connection, user_id, product_id, status="trial")


def test_one_active_product_per_plan_and_interval(connection: Connection) -> None:
    plan_key = f"key{token()[:12]}"
    make_plan(connection, plan_key=plan_key, interval="month")

    with rejected(connection, "ix_products_plan_key_interval_active"):
        make_plan(connection, plan_key=plan_key, interval="month")
    make_plan(connection, plan_key=plan_key, interval="year")
    make_plan(connection, plan_key=plan_key, interval="month", is_active=False, razorpay_plan_id=None)


def test_active_subscription_product_needs_a_razorpay_plan(connection: Connection) -> None:
    with rejected(connection, "ck_products_active_subscription_has_plan"):
        make_plan(connection, razorpay_plan_id=None)


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"price_paise": 0}, "ck_products_price_paise_positive"),
        ({"credits_granted": 0}, "ck_products_credits_granted_positive"),
        ({"currency": "inr"}, "ck_products_currency_format"),
        ({"code": "Starter"}, "ck_products_code_format"),
        ({"name": ""}, "ck_products_name_length"),
        ({"interval": "month"}, "ck_products_shape"),
        ({"plan_key": "pro"}, "ck_products_shape"),
        ({"razorpay_plan_id": "plan_1"}, "ck_products_shape"),
        ({"kind": "bundle"}, "ck_products_kind"),
        ({"version": 0}, "ck_products_version_positive"),
        ({"features": {"a": 1}}, "ck_products_features_array"),
    ],
)
def test_product_shape_and_value_checks(connection: Connection, overrides: dict[str, Any], constraint: str) -> None:
    with rejected(connection, constraint):
        make_pack(connection, **overrides)


def test_product_code_and_plan_identifiers_are_unique(connection: Connection) -> None:
    plan_id = f"plan_{token()[:14]}"
    make_pack(connection, code="pack_unique")
    make_plan(connection, razorpay_plan_id=plan_id)

    with rejected(connection, "uq_products_code"):
        make_pack(connection, code="pack_unique")
    with rejected(connection, "uq_products_razorpay_plan_id"):
        make_plan(connection, razorpay_plan_id=plan_id)


def test_product_cannot_supersede_itself(connection: Connection) -> None:
    product_id = make_pack(connection)

    with rejected(connection, "ck_products_not_own_predecessor"):
        update(connection, "products", product_id, supersedes_product_id=product_id)
    successor = make_pack(connection, supersedes_product_id=product_id, version=2)

    assert isinstance(successor, UUID)


@pytest.mark.parametrize(
    "changes",
    [{"price_paise": 59_900}, {"credits_granted": 150}, {"currency": "USD"}],
)
def test_unused_product_financial_fields_can_change(connection: Connection, changes: dict[str, Any]) -> None:
    product_id = make_pack(connection)

    update(connection, "products", product_id, **changes)


@pytest.mark.parametrize(
    "changes",
    [{"price_paise": 59_900}, {"credits_granted": 150}, {"currency": "USD"}],
)
def test_product_financial_fields_are_frozen_once_an_order_exists(
    connection: Connection, changes: dict[str, Any]
) -> None:
    product_id = make_pack(connection)
    make_order(connection, make_user(connection), product_id)

    with rejected(connection, "financially immutable"):
        update(connection, "products", product_id, **changes)


def test_product_kind_is_frozen_once_an_order_exists(connection: Connection) -> None:
    product_id = make_pack(connection)
    make_order(connection, make_user(connection), product_id)

    with rejected(connection, "financially immutable"):
        update(
            connection,
            "products",
            product_id,
            kind="subscription",
            interval="month",
            plan_key="pro",
            razorpay_plan_id="plan_x",
        )


def test_product_non_financial_fields_stay_editable_once_used(connection: Connection) -> None:
    product_id = make_pack(connection)
    make_order(connection, make_user(connection), product_id)

    update(
        connection,
        "products",
        product_id,
        name="Starter pack",
        description="Fifty videos",
        is_active=False,
        sort_order=3,
        features=["a", "b"],
        version=2,
    )


def test_plan_fields_are_frozen_once_a_subscription_references_the_product(connection: Connection) -> None:
    product_id = make_plan(connection)
    make_subscription(connection, make_user(connection), product_id)

    with rejected(connection, "financially immutable"):
        update(connection, "products", product_id, interval="year")
    with rejected(connection, "financially immutable"):
        update(connection, "products", product_id, razorpay_plan_id="plan_other")
    with rejected(connection, "financially immutable"):
        update(connection, "products", product_id, price_paise=1)
    update(connection, "products", product_id, name="Pro monthly renamed", is_active=False)


def test_pending_plan_changes_also_freeze_the_target_product(connection: Connection) -> None:
    current = make_plan(connection)
    target = make_plan(connection)
    make_subscription(connection, make_user(connection), current, pending_product_id=target)

    with rejected(connection, "financially immutable"):
        update(connection, "products", target, price_paise=1)


def test_razorpay_plan_id_can_be_set_once_on_a_used_inactive_product(connection: Connection) -> None:
    product_id = make_plan(connection, is_active=False, razorpay_plan_id=None)
    make_subscription(connection, make_user(connection), product_id, status="created")

    update(connection, "products", product_id, razorpay_plan_id="plan_assigned")
    with rejected(connection, "financially immutable"):
        update(connection, "products", product_id, razorpay_plan_id="plan_replaced")


def test_other_products_remain_editable_when_one_is_used(connection: Connection) -> None:
    used = make_pack(connection)
    unused = make_pack(connection)
    make_order(connection, make_user(connection), used)

    update(connection, "products", unused, price_paise=1)


def test_order_paid_flag_matches_paid_at(connection: Connection) -> None:
    user_id = make_user(connection)
    product_id = make_pack(connection)

    with rejected(connection, "ck_orders_paid_consistent"):
        make_order(connection, user_id, product_id, status="paid")
    with rejected(connection, "ck_orders_paid_consistent"):
        make_order(connection, user_id, product_id, status="created", paid_at=NOW)
    make_order(connection, user_id, product_id, status="paid", paid_at=NOW)
    make_order(connection, user_id, product_id, status="expired")


def test_order_flag_reason_matches_flagged_at(connection: Connection) -> None:
    user_id = make_user(connection)
    product_id = make_pack(connection)

    with rejected(connection, "ck_orders_flag_consistent"):
        make_order(connection, user_id, product_id, flagged_at=NOW)
    with rejected(connection, "ck_orders_flag_consistent"):
        make_order(connection, user_id, product_id, flag_reason="amount_mismatch")
    with rejected(connection, "ck_orders_flag_reason"):
        make_order(connection, user_id, product_id, flagged_at=NOW, flag_reason="other")
    make_order(connection, user_id, product_id, flagged_at=NOW, flag_reason="currency_mismatch")
    make_order(connection, user_id, product_id, flagged_at=NOW, flag_reason="duplicate_payment")


def test_order_subscription_link_matches_kind(connection: Connection) -> None:
    user_id = make_user(connection)
    plan_id = make_plan(connection)
    pack_id = make_pack(connection)
    subscription_id = make_subscription(connection, user_id, plan_id)

    with rejected(connection, "ck_orders_subscription_consistent"):
        make_order(connection, user_id, plan_id, kind="subscription")
    with rejected(connection, "ck_orders_subscription_consistent"):
        make_order(connection, user_id, pack_id, subscription_id=subscription_id)
    make_order(connection, user_id, plan_id, kind="subscription", subscription_id=subscription_id)


def test_order_uniqueness_and_limits(connection: Connection) -> None:
    user_id = make_user(connection)
    product_id = make_pack(connection)
    make_order(connection, user_id, product_id, idempotency_key="key-1", receipt="receipt-1", razorpay_order_id="o1")

    with rejected(connection, "uq_orders_user_id_idempotency_key"):
        make_order(connection, user_id, product_id, idempotency_key="key-1")
    with rejected(connection, "uq_orders_receipt"):
        make_order(connection, user_id, product_id, receipt="receipt-1")
    with rejected(connection, "uq_orders_razorpay_order_id"):
        make_order(connection, user_id, product_id, razorpay_order_id="o1")
    with rejected(connection, "ck_orders_receipt_length"):
        make_order(connection, user_id, product_id, receipt="r" * 41)
    with rejected(connection, "ck_orders_amount_paise_positive"):
        make_order(connection, user_id, product_id, amount_paise=0)
    make_order(connection, make_user(connection), product_id, idempotency_key="key-1")


@pytest.mark.parametrize("refunded_paise", [-1, 49_901])
def test_payment_refunded_amount_stays_within_the_payment(connection: Connection, refunded_paise: int) -> None:
    user_id = make_user(connection)
    order_id = make_order(connection, user_id, make_pack(connection))

    with rejected(connection, "ck_payments_refunded_paise_range"):
        make_payment(connection, user_id, order_id, refunded_paise=refunded_paise)


def test_payment_accepts_partial_and_full_refunds(connection: Connection) -> None:
    user_id = make_user(connection)
    order_id = make_order(connection, user_id, make_pack(connection))

    payment_id = make_payment(connection, user_id, order_id, refunded_paise=10_000, status="partially_refunded")
    update(connection, "payments", payment_id, refunded_paise=49_900, status="refunded")
    with rejected(connection, "ck_payments_refunded_paise_range"):
        update(connection, "payments", payment_id, refunded_paise=49_901)


def test_payment_needs_a_parent_and_a_unique_gateway_id(connection: Connection) -> None:
    user_id = make_user(connection)
    order_id = make_order(connection, user_id, make_pack(connection))

    with rejected(connection, "ck_payments_has_parent"):
        make_payment(connection, user_id, None)
    make_payment(connection, user_id, order_id, razorpay_payment_id="pay_1")
    with rejected(connection, "uq_payments_razorpay_payment_id"):
        make_payment(connection, user_id, order_id, razorpay_payment_id="pay_1")
    with rejected(connection, "ck_payments_status"):
        make_payment(connection, user_id, order_id, status="settled")
    with rejected(connection, "ck_payments_fee_paise_non_negative"):
        make_payment(connection, user_id, order_id, fee_paise=-1)


def test_refund_checks(connection: Connection) -> None:
    user_id = make_user(connection)
    payment_id = make_payment(connection, user_id, make_order(connection, user_id, make_pack(connection)))
    values: dict[str, Any] = {"payment_id": payment_id, "amount_paise": 1_000, "reason": "Requested by user"}

    with rejected(connection, "ck_refunds_processed_consistent"):
        insert(connection, "refunds", **values, status="processed")
    with rejected(connection, "ck_refunds_reason_length"):
        insert(connection, "refunds", **{**values, "reason": ""})
    with rejected(connection, "ck_refunds_amount_paise_positive"):
        insert(connection, "refunds", **{**values, "amount_paise": 0})
    insert(connection, "refunds", **values, status="processed", processed_at=NOW, razorpay_refund_id="rfnd_1")
    with rejected(connection, "uq_refunds_razorpay_refund_id"):
        insert(connection, "refunds", **values, razorpay_refund_id="rfnd_1")


def test_webhook_events_deduplicate_per_provider(connection: Connection) -> None:
    values: dict[str, Any] = {"provider": "razorpay", "event_id": "evt_1", "event_type": "payment.captured"}
    insert(connection, "webhook_events", **values, payload={"event": "payment.captured"})

    with rejected(connection, "uq_webhook_events_provider_event_id"):
        insert(connection, "webhook_events", **values, payload={})
    insert(connection, "webhook_events", **{**values, "provider": "youtube"}, payload={})
    with rejected(connection, "ck_webhook_events_status"):
        insert(connection, "webhook_events", **{**values, "event_id": "evt_2"}, payload={}, status="done")
    with rejected(connection, "ck_webhook_events_provider_format"):
        insert(connection, "webhook_events", **{**values, "provider": "Razorpay"}, payload={})


def test_settlement_runs_are_unique_per_period(connection: Connection) -> None:
    day = datetime(2026, 10, 16, tzinfo=UTC)
    period = {"period_start": day, "period_end": day + timedelta(days=1)}
    insert(connection, "billing_reconciliation_runs", type="settlement", **period)

    with rejected(connection, "uq_billing_reconciliation_runs_settlement_period"):
        insert(connection, "billing_reconciliation_runs", type="settlement", **period)
    insert(connection, "billing_reconciliation_runs", type="pending_orders")
    insert(connection, "billing_reconciliation_runs", type="pending_orders", **period)


def test_reconciliation_run_checks(connection: Connection) -> None:
    day = datetime(2026, 10, 16, tzinfo=UTC)

    with rejected(connection, "ck_billing_reconciliation_runs_period"):
        insert(connection, "billing_reconciliation_runs", type="settlement", period_start=day)
    with rejected(connection, "ck_billing_reconciliation_runs_period"):
        insert(connection, "billing_reconciliation_runs", type="settlement", period_start=day, period_end=day)
    with rejected(connection, "ck_billing_reconciliation_runs_finished_consistent"):
        insert(connection, "billing_reconciliation_runs", type="subscriptions", status="completed")
    with rejected(connection, "ck_billing_reconciliation_runs_finished_consistent"):
        insert(connection, "billing_reconciliation_runs", type="subscriptions", finished_at=day)
    insert(connection, "billing_reconciliation_runs", type="subscriptions", status="completed", finished_at=day)
    with rejected(connection, "ck_billing_reconciliation_runs_type"):
        insert(connection, "billing_reconciliation_runs", type="nightly")


@pytest.mark.parametrize("table", ["credit_wallets", "credit_lots", "billing_customers", "orders", "subscriptions"])
def test_users_with_financial_history_cannot_be_hard_deleted(connection: Connection, table: str) -> None:
    user_id = make_user(connection)
    if table == "credit_wallets":
        insert(connection, table, user_id=user_id)
    elif table == "credit_lots":
        make_lot(connection, user_id)
    elif table == "billing_customers":
        insert(connection, table, user_id=user_id, razorpay_customer_id=f"cust_{token()}")
    elif table == "orders":
        make_order(connection, user_id, make_pack(connection))
    else:
        make_subscription(connection, user_id, make_plan(connection))

    with rejected(connection, "violates foreign key constraint"):
        connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})


def test_used_products_cannot_be_deleted(connection: Connection) -> None:
    product_id = make_pack(connection)
    make_order(connection, make_user(connection), product_id)

    with rejected(connection, "violates foreign key constraint"):
        connection.execute(text("DELETE FROM products WHERE id = :id"), {"id": product_id})


def test_permission_catalog_matches_the_database(connection: Connection) -> None:
    keys = set(connection.execute(text("SELECT key FROM permissions")).scalars())

    assert keys == PERMISSION_KEYS
    assert keys >= BILLING_PERMISSION_KEYS


def test_admin_holds_only_the_billing_permissions_it_is_meant_to(connection: Connection) -> None:
    query = text(
        "SELECT permissions.key FROM role_permissions "
        "JOIN roles ON roles.id = role_permissions.role_id "
        "JOIN permissions ON permissions.id = role_permissions.permission_id "
        "WHERE roles.key = :role AND permissions.key LIKE 'billing.%'"
    )

    admin = set(connection.execute(query, {"role": "admin"}).scalars())
    user = set(connection.execute(query, {"role": "user"}).scalars())

    assert admin == ADMIN_BILLING_PERMISSION_KEYS
    assert user == set()
