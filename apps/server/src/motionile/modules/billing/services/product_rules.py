import re
from collections.abc import Collection, Mapping
from dataclasses import replace
from typing import cast

from motionile.modules.billing.exceptions import InvalidProductShapeError
from motionile.modules.billing.records import ProductRecord

CREDIT_PACK = "credit_pack"
SUBSCRIPTION = "subscription"
VERSION_SUFFIX = re.compile(r"_v\d+$")
MAX_CODE_LENGTH = 60
SUFFIX_RESERVE = 12
PROTECTED_FIELDS = ("kind", "price_paise", "currency", "interval", "credits_granted", "plan_key")
PLAN_FIELDS = ("kind", "price_paise", "currency", "interval")


def code_base(code: str) -> str:
    return VERSION_SUFFIX.sub("", code)


def code_prefix(code: str) -> str:
    return code_base(code)[: MAX_CODE_LENGTH - SUFFIX_RESERVE]


def versioned_code(code: str, number: int) -> str:
    suffix = f"_v{number}"
    return f"{code_base(code)[: MAX_CODE_LENGTH - len(suffix)].rstrip('_')}{suffix}"


def next_versioned_code(code: str, number: int, taken: Collection[str]) -> str:
    candidate_number = number
    while (candidate := versioned_code(code, candidate_number)) in taken:
        candidate_number += 1
    return candidate


def effective_changes(current: ProductRecord, requested: Mapping[str, object]) -> dict[str, object]:
    return {name: value for name, value in requested.items() if getattr(current, name) != value}


def changed_protected_fields(effective: Mapping[str, object]) -> list[str]:
    return [name for name in PROTECTED_FIELDS if name in effective]


def plan_invalidated(current: ProductRecord, effective: Mapping[str, object]) -> bool:
    return current.razorpay_plan_id is not None and any(name in effective for name in PLAN_FIELDS)


def apply_changes(current: ProductRecord, effective: Mapping[str, object]) -> ProductRecord:
    return replace(current, **effective)


def reconcile_plan(
    current: ProductRecord, merged: ProductRecord, effective: Mapping[str, object]
) -> tuple[ProductRecord, dict[str, object]]:
    forced: dict[str, object] = {}
    if plan_invalidated(current, effective):
        forced["razorpay_plan_id"] = None
        merged = replace(merged, razorpay_plan_id=None)
    if merged.kind == SUBSCRIPTION and merged.razorpay_plan_id is None and merged.is_active:
        forced["is_active"] = False
        merged = replace(merged, is_active=False)
    return merged, forced


def column_values(effective: Mapping[str, object]) -> dict[str, object]:
    values = dict(effective)
    features = effective.get("features")
    if isinstance(features, tuple):
        values["features"] = [str(item) for item in cast("tuple[object, ...]", features)]
    return values


def validate_shape(kind: str, plan_key: str | None, interval: str | None) -> None:
    if kind == SUBSCRIPTION and (plan_key is None or interval is None):
        message = "A subscription product needs a plan key and an interval."
        raise InvalidProductShapeError(message)
    if kind == CREDIT_PACK and (plan_key is not None or interval is not None):
        message = "A credit pack cannot have a plan key or an interval."
        raise InvalidProductShapeError(message)
