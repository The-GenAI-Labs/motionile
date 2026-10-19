import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

from motionile.modules.access import PERMISSION_KEYS, PERMISSIONS
from motionile.modules.platform import SETTINGS
from motionile.modules.platform.registry import validate_setting

MIGRATION = Path(__file__).resolve().parents[3] / "migrations" / "versions" / "20261017_0005_credits_and_billing.py"
BILLING_KEYS = (
    "billing.read",
    "billing.products.manage",
    "billing.refunds.create",
    "billing.credits.adjust",
    "billing.webhooks.manage",
)
PERMISSION_KEY_FORMAT = re.compile(r"^[a-z][a-z_]*(\.[a-z][a-z_]*)+$")


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("billing_migration", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_subscription_rollover_is_a_private_boolean_defaulting_to_off() -> None:
    definition = SETTINGS["billing.subscription_rollover"]

    assert definition.schema == {"type": "boolean"}
    assert definition.default is False
    assert definition.public is False
    assert definition.description


@pytest.mark.parametrize("value", [True, False])
def test_subscription_rollover_accepts_booleans(value: bool) -> None:
    assert validate_setting("billing.subscription_rollover", value) is value


@pytest.mark.parametrize("value", [0, 1, "true", "false", None, [True]])
def test_subscription_rollover_rejects_other_types(value: object) -> None:
    with pytest.raises(ValueError, match="wrong type"):
        validate_setting("billing.subscription_rollover", value)


def test_permission_catalog_contains_every_billing_permission() -> None:
    assert set(BILLING_KEYS) <= PERMISSION_KEYS
    assert len(PERMISSIONS) == len(PERMISSION_KEYS)
    assert all(PERMISSION_KEY_FORMAT.fullmatch(key) and len(key) <= 80 for key in PERMISSION_KEYS)
    assert all(definition.description for definition in PERMISSIONS)


def test_migration_seeds_the_same_permissions_as_the_catalog() -> None:
    migration = load_migration()
    catalog = {definition.key: definition.description for definition in PERMISSIONS}

    assert [key for key, _ in migration.BILLING_PERMISSIONS] == list(BILLING_KEYS)
    assert all(catalog[key] == description for key, description in migration.BILLING_PERMISSIONS)


def test_migration_withholds_refunds_and_adjustments_from_the_admin_role() -> None:
    statement: str = load_migration().INSERT_ADMIN_BILLING_PERMISSIONS

    assert "roles.key = 'admin'" in statement
    assert "NOT IN ('billing.refunds.create', 'billing.credits.adjust')" in statement
