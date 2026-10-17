import re
from dataclasses import dataclass
from typing import cast

type SettingValue = bool | int | str | list[str]


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    schema: dict[str, object]
    default: SettingValue
    description: str
    public: bool


SETTING_DEFINITIONS = (
    SettingDefinition(
        "preferences.styles",
        {
            "type": "array",
            "items": {"type": "string", "pattern": r"^[a-z0-9]+(-[a-z0-9]+)*$"},
            "minItems": 1,
            "maxItems": 50,
            "uniqueItems": True,
        },
        ["minimal", "editorial", "diagram"],
        "Allowed default video style slugs",
        True,
    ),
    SettingDefinition(
        "preferences.paces",
        {
            "type": "array",
            "items": {"type": "string", "enum": ["slow", "normal", "fast"]},
            "minItems": 1,
            "uniqueItems": True,
        },
        ["slow", "normal", "fast"],
        "Allowed narration pace values",
        True,
    ),
    SettingDefinition(
        "preferences.languages",
        {
            "type": "array",
            "items": {"type": "string", "pattern": r"^[a-z]{2,3}(-[A-Z]{2})?$"},
            "minItems": 1,
            "maxItems": 100,
            "uniqueItems": True,
        },
        ["en", "en-IN", "hi-IN"],
        "Allowed narration languages",
        True,
    ),
    SettingDefinition(
        "preferences.depths",
        {
            "type": "array",
            "items": {"type": "string", "enum": ["overview", "standard", "deep"]},
            "minItems": 1,
            "uniqueItems": True,
        },
        ["overview", "standard", "deep"],
        "Allowed explanation depths",
        True,
    ),
    SettingDefinition(
        "preferences.aspects",
        {
            "type": "array",
            "items": {"type": "string", "enum": ["16:9", "9:16", "1:1"]},
            "minItems": 1,
            "uniqueItems": True,
        },
        ["16:9", "9:16", "1:1"],
        "Allowed default video aspect ratios",
        True,
    ),
    SettingDefinition(
        "uploads.avatar_max_bytes",
        {"type": "integer", "minimum": 1024, "maximum": 10485760},
        2097152,
        "Maximum avatar source size in bytes",
        False,
    ),
    SettingDefinition(
        "catalog.explore_page_size",
        {"type": "integer", "minimum": 6, "maximum": 100},
        24,
        "Default public catalog page size",
        True,
    ),
)

SETTINGS = {item.key: item for item in SETTING_DEFINITIONS}


def validate_setting(key: str, value: object) -> SettingValue:  # noqa: PLR0912
    definition = SETTINGS[key]
    schema = definition.schema
    expected = schema["type"]
    if expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Setting must be an integer")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if (isinstance(minimum, int) and value < minimum) or (isinstance(maximum, int) and value > maximum):
            raise ValueError("Setting is outside its allowed range")
        return value
    if expected == "array":
        values = cast("list[object]", value) if isinstance(value, list) else None
        if values is None or not all(isinstance(item, str) for item in values):
            raise ValueError("Setting must be an array of strings")
        strings = cast("list[str]", values)
        minimum_items = schema.get("minItems")
        maximum_items = schema.get("maxItems")
        if isinstance(minimum_items, int) and len(strings) < minimum_items:
            raise ValueError("Setting has too few items")
        if isinstance(maximum_items, int) and len(strings) > maximum_items:
            raise ValueError("Setting has too many items")
        if schema.get("uniqueItems") and len(strings) != len(set(strings)):
            raise ValueError("Setting items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            typed_item_schema = cast("dict[str, object]", item_schema)
            enum = typed_item_schema.get("enum")
            enum_values = cast("list[object]", enum) if isinstance(enum, list) else None
            if (
                enum_values is not None
                and all(isinstance(item, str) for item in enum_values)
                and any(item not in cast("list[str]", enum_values) for item in strings)
            ):
                raise ValueError("Setting contains an unsupported item")
            pattern = typed_item_schema.get("pattern")
            if isinstance(pattern, str) and any(re.fullmatch(pattern, item) is None for item in strings):
                raise ValueError("Setting contains an invalid item")
        return strings
    if expected == "boolean" and isinstance(value, bool):
        return value
    if expected == "string" and isinstance(value, str):
        return value
    raise ValueError("Setting value has the wrong type")
