import io
from pathlib import Path
from uuid import UUID

import pytest
from PIL import Image, PngImagePlugin

from motionile.core.errors import PayloadTooLargeError, ValidationAppError
from motionile.modules.platform import PlatformService
from motionile.modules.platform.models import FeatureFlag
from motionile.modules.platform.registry import validate_setting
from motionile.modules.users.avatar import process_avatar_sync
from motionile.scripts.seed_catalog import parse_catalog


def image_bytes(format_name: str = "PNG", *, metadata: bool = False) -> bytes:
    output = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    if metadata:
        info.add_text("private", "remove me")
    Image.new("RGB", (40, 20), "red").save(output, format=format_name, pnginfo=info if format_name == "PNG" else None)
    return output.getvalue()


def test_avatar_reencodes_square_and_strips_metadata() -> None:
    result = process_avatar_sync(image_bytes(metadata=True), 2_097_152)
    with Image.open(io.BytesIO(result)) as image:
        assert image.format == "WEBP"
        assert image.size == (256, 256)
        assert "private" not in image.info


def test_avatar_rejects_oversize_and_polyglot() -> None:
    source = image_bytes()
    with pytest.raises(PayloadTooLargeError):
        process_avatar_sync(source, len(source) - 1)
    with pytest.raises(ValidationAppError) as error:
        process_avatar_sync(source + b"<svg/>", len(source) + 16)
    assert error.value.code == "avatar_polyglot"


def test_platform_setting_validation() -> None:
    assert validate_setting("preferences.paces", ["slow", "normal", "fast"]) == ["slow", "normal", "fast"]
    with pytest.raises(ValueError, match="unique"):
        validate_setting("preferences.paces", ["slow", "slow"])
    with pytest.raises(ValueError, match="allowed range"):
        validate_setting("uploads.avatar_max_bytes", 99)


def test_flag_rollout_is_deterministic_and_rules_override() -> None:
    service = object.__new__(PlatformService)
    user_id = UUID("0199eb00-0000-7000-8000-000000000111")
    rollout = FeatureFlag(key="phase6", enabled=True, rollout_percentage=50, rules=[])
    results = {service.evaluate_flag(rollout, user_id, frozenset()) for _ in range(20)}
    assert len(results) == 1
    disabled = FeatureFlag(key="disabled", enabled=False, rollout_percentage=100, rules=[])
    assert not service.evaluate_flag(disabled, user_id, frozenset({"admin"}))
    targeted = FeatureFlag(
        key="targeted",
        enabled=True,
        rollout_percentage=0,
        rules=[{"kind": "role", "values": ["admin"]}],
    )
    assert service.evaluate_flag(targeted, user_id, frozenset({"admin"}))


def test_catalog_seed_has_required_shape() -> None:
    path = Path(__file__).resolve().parents[3] / "seeds" / "catalog.yaml"
    catalog = parse_catalog(path.read_text(encoding="utf-8"))
    assert [category.slug for category in catalog.categories] == ["education", "tech"]
    assert sum(len(category.subcategories) for category in catalog.categories) == 15
    assert all(
        len(subcategory.topics) >= 6 for category in catalog.categories for subcategory in category.subcategories
    )
