from datetime import date
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from motionile.modules.billing.admin_credit_schemas import MAX_ADJUSTMENT, AdjustCreditsRequest, AnalyticsQuery
from motionile.modules.billing.admin_schemas import (
    CreateProductRequest,
    DuplicateProductRequest,
    PaymentListQuery,
    UpdateProductRequest,
)
from motionile.modules.billing.services.admin_credits import adjustment_ledger_key

ADMIN = UUID(int=1)
USER = UUID(int=2)


def pack(**overrides: Any) -> dict[str, Any]:
    return {
        "code": "pack_new",
        "kind": "credit_pack",
        "name": "New",
        "pricePaise": 9_900,
        "creditsGranted": 50,
        **overrides,
    }


def test_a_minimal_pack_request_gets_safe_defaults() -> None:
    request = CreateProductRequest.model_validate(pack())

    assert (request.currency, request.features, request.sort_order, request.is_active) == ("INR", [], 0, False)


@pytest.mark.parametrize(
    "overrides",
    [
        {"code": "Pack New"},
        {"code": "x" * 61},
        {"name": ""},
        {"name": "n" * 81},
        {"name": "   "},
        {"pricePaise": 0},
        {"pricePaise": 10_000_000_001},
        {"creditsGranted": 0},
        {"features": ["f"] * 21},
        {"features": [""]},
        {"currency": "inr"},
        {"description": "d" * 501},
        {"sortOrder": -1},
        {"surprise": True},
        {"kind": "gift"},
        {"interval": "week"},
    ],
)
def test_product_requests_bound_every_value(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        CreateProductRequest.model_validate(pack(**overrides))


def test_text_is_stripped() -> None:
    assert CreateProductRequest.model_validate(pack(name="  Padded  ")).name == "Padded"


def test_an_update_needs_at_least_one_change() -> None:
    with pytest.raises(ValidationError):
        UpdateProductRequest.model_validate({"version": 1})


@pytest.mark.parametrize("field", ["name", "features", "sortOrder", "kind", "pricePaise", "currency", "creditsGranted"])
def test_required_columns_cannot_be_nulled(field: str) -> None:
    with pytest.raises(ValidationError):
        UpdateProductRequest.model_validate({"version": 1, field: None})


def test_nullable_columns_can_be_cleared_and_changes_list_only_sent_fields() -> None:
    request = UpdateProductRequest.model_validate(
        {"version": 3, "description": None, "interval": None, "features": ["a", "b"], "name": "New"}
    )

    assert request.changes() == {"description": None, "features": ("a", "b"), "interval": None, "name": "New"}


def test_an_update_requires_the_version() -> None:
    with pytest.raises(ValidationError):
        UpdateProductRequest.model_validate({"name": "x"})
    with pytest.raises(ValidationError):
        UpdateProductRequest.model_validate({"version": 0, "name": "x"})


def test_a_duplicate_request_may_be_empty_but_not_unknown() -> None:
    assert DuplicateProductRequest.model_validate({}).price_paise is None
    with pytest.raises(ValidationError):
        DuplicateProductRequest.model_validate({"code": "forced"})


@pytest.mark.parametrize("delta", [0, MAX_ADJUSTMENT + 1, -MAX_ADJUSTMENT - 1, 1.5])
def test_adjustments_must_be_a_bounded_non_zero_integer(delta: float) -> None:
    with pytest.raises(ValidationError):
        AdjustCreditsRequest.model_validate({"delta": delta, "reason": "why"})


@pytest.mark.parametrize("reason", ["", "   ", "r" * 501])
def test_adjustments_need_a_bounded_reason(reason: str) -> None:
    with pytest.raises(ValidationError):
        AdjustCreditsRequest.model_validate({"delta": 5, "reason": reason})


def test_an_adjustment_expiry_must_carry_a_timezone() -> None:
    with pytest.raises(ValidationError):
        AdjustCreditsRequest.model_validate({"delta": 5, "reason": "ok", "expiresAt": "2030-01-01T00:00:00"})
    parsed = AdjustCreditsRequest.model_validate({"delta": -5, "reason": " ok ", "expiresAt": "2030-01-01T00:00:00Z"})
    assert parsed.reason == "ok"


def test_the_ledger_key_is_stable_and_scoped_to_admin_user_and_key() -> None:
    key = adjustment_ledger_key(ADMIN, USER, "abc")

    assert key == adjustment_ledger_key(ADMIN, USER, "abc")
    assert len(key) <= 200
    assert (
        len({key, adjustment_ledger_key(UUID(int=3), USER, "abc"), adjustment_ledger_key(ADMIN, UUID(int=3), "abc")})
        == 3
    )
    assert key != adjustment_ledger_key(ADMIN, USER, "abd")


def test_filters_use_camel_case_aliases_and_reject_unknown_values() -> None:
    query = PaymentListQuery.model_validate(
        {"status": "captured", "createdFrom": "2026-10-01T00:00:00Z", "flagged": "true", "limit": "5"}
    )

    assert (query.status, query.flagged, query.limit) == ("captured", True, 5)
    with pytest.raises(ValidationError):
        PaymentListQuery.model_validate({"status": "weird"})
    with pytest.raises(ValidationError):
        PaymentListQuery.model_validate({"createdFrom": "2026-10-01T00:00:00"})
    with pytest.raises(ValidationError):
        PaymentListQuery.model_validate({"limit": "101"})


def test_analytics_ranges_use_from_and_to() -> None:
    query = AnalyticsQuery.model_validate({"from": "2026-10-01", "to": "2026-10-18"})

    assert (query.range_start, query.range_end) == (date(2026, 10, 1), date(2026, 10, 18))
