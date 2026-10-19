from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st
from tests.unit.modules.billing.conftest import pack_product

from motionile.modules.billing.exceptions import InvalidProductShapeError
from motionile.modules.billing.services.product_rules import (
    MAX_CODE_LENGTH,
    apply_changes,
    changed_protected_fields,
    code_base,
    column_values,
    effective_changes,
    next_versioned_code,
    plan_invalidated,
    reconcile_plan,
    validate_shape,
    versioned_code,
)


@pytest.mark.parametrize(
    ("code", "base"),
    [
        ("pro_monthly", "pro_monthly"),
        ("pro_monthly_v2", "pro_monthly"),
        ("pro_monthly_v12", "pro_monthly"),
        ("pro_v2_monthly", "pro_v2_monthly"),
        ("v2", "v2"),
        ("pack_v", "pack_v"),
    ],
)
def test_the_base_strips_only_a_trailing_version_suffix(code: str, base: str) -> None:
    assert code_base(code) == base


def test_a_versioned_code_replaces_an_existing_suffix() -> None:
    assert versioned_code("pro_monthly", 2) == "pro_monthly_v2"
    assert versioned_code("pro_monthly_v2", 3) == "pro_monthly_v3"


def test_a_long_base_is_truncated_to_fit_the_code_limit() -> None:
    code = versioned_code("a" * 59, 10)

    assert len(code) == MAX_CODE_LENGTH
    assert code.endswith("_v10")


def test_truncation_never_leaves_a_trailing_underscore_before_the_suffix() -> None:
    code = versioned_code("a" * 55 + "_bcdef", 2)

    assert "__" not in code
    assert code.endswith("_v2")


def test_the_next_code_skips_codes_that_are_taken() -> None:
    taken = {"pro_monthly_v2", "pro_monthly_v3"}

    assert next_versioned_code("pro_monthly", 2, taken) == "pro_monthly_v4"
    assert next_versioned_code("pro_monthly_v2", 3, taken) == "pro_monthly_v4"
    assert next_versioned_code("pro_monthly", 2, set()) == "pro_monthly_v2"


@given(
    base=st.from_regex(r"[a-z0-9]+(_[a-z0-9]+){0,6}", fullmatch=True).filter(lambda value: len(value) <= 60),
    number=st.integers(min_value=2, max_value=99_999),
)
def test_a_versioned_code_always_satisfies_the_code_format(base: str, number: int) -> None:
    code = versioned_code(base, number)

    assert len(code) <= MAX_CODE_LENGTH
    assert code.endswith(f"_v{number}")
    assert code_base(code).strip("_") == code_base(code)
    assert "__" not in code


def test_only_changed_values_count_as_changes() -> None:
    product = pack_product()

    effective = effective_changes(product, {"price_paise": product.price_paise, "name": "Renamed", "sort_order": 10})

    assert effective == {"name": "Renamed"}


def test_protected_fields_are_reported_in_a_stable_order() -> None:
    effective = {"credits_granted": 5, "name": "x", "price_paise": 1, "plan_key": "other"}

    assert changed_protected_fields(effective) == ["price_paise", "credits_granted", "plan_key"]
    assert changed_protected_fields({"name": "x", "features": ("a",)}) == []


def test_a_plan_is_invalidated_only_by_changes_the_plan_depends_on() -> None:
    synced = replace(pack_product(kind="subscription"), razorpay_plan_id="plan_1")
    unsynced = replace(synced, razorpay_plan_id=None)

    assert plan_invalidated(synced, {"price_paise": 1})
    assert plan_invalidated(synced, {"interval": "year"})
    assert not plan_invalidated(synced, {"credits_granted": 1, "name": "x"})
    assert not plan_invalidated(unsynced, {"price_paise": 1})


def test_reconciling_a_plan_reset_deactivates_the_subscription() -> None:
    synced = replace(pack_product(kind="subscription"), razorpay_plan_id="plan_1", is_active=True)
    effective = {"price_paise": 5_000}

    merged, forced = reconcile_plan(synced, apply_changes(synced, effective), effective)

    assert forced == {"razorpay_plan_id": None, "is_active": False}
    assert (merged.razorpay_plan_id, merged.is_active) == (None, False)


def test_converting_an_active_pack_to_a_subscription_deactivates_it() -> None:
    pack = pack_product()
    effective: dict[str, object] = {"kind": "subscription", "plan_key": "pro", "interval": "month"}

    merged, forced = reconcile_plan(pack, apply_changes(pack, effective), effective)

    assert forced == {"is_active": False}
    assert merged.is_active is False


def test_a_free_text_edit_forces_nothing() -> None:
    product = pack_product()
    effective = {"name": "Renamed"}

    merged, forced = reconcile_plan(product, apply_changes(product, effective), effective)

    assert forced == {}
    assert merged.name == "Renamed"


def test_features_are_stored_as_a_list() -> None:
    assert column_values({"features": ("a", "b"), "name": "x"}) == {"features": ["a", "b"], "name": "x"}


@pytest.mark.parametrize(
    ("kind", "plan_key", "interval"),
    [
        ("subscription", None, "month"),
        ("subscription", "pro", None),
        ("credit_pack", "pro", None),
        ("credit_pack", None, "year"),
    ],
)
def test_an_inconsistent_shape_is_rejected(kind: str, plan_key: str | None, interval: str | None) -> None:
    with pytest.raises(InvalidProductShapeError):
        validate_shape(kind, plan_key, interval)


def test_consistent_shapes_pass() -> None:
    validate_shape("subscription", "pro", "month")
    validate_shape("credit_pack", None, None)
