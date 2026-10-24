import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from pydantic import ValidationError

from motionile.engine.ai.llm.routing import DEFAULT_ROUTING_JSON, parse_routing

type SettingValue = bool | int | str | list[str]

VOICE_CONSENT_STATEMENT = (
    "I confirm that the voice I am submitting is my own. "
    "I consent to Motionile creating a synthetic copy of my voice through its voice provider "
    "so that it can narrate videos made with my account. "
    "I will not use this voice to impersonate any other person, and I will not submit recordings of anyone else. "
    "I understand that I can delete this voice at any time, which removes the copy from the provider "
    "and my recordings from Motionile."
)


def check_model_routing(value: str) -> None:
    try:
        parse_routing(value)
    except ValidationError as error:
        raise ValueError("Setting is not a valid model routing document") from error


@dataclass(frozen=True)
class SettingDefinition:
    key: str
    schema: dict[str, object]
    default: SettingValue
    description: str
    public: bool
    check: Callable[[str], None] | None = None


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
    SettingDefinition(
        "billing.subscription_rollover",
        {"type": "boolean"},
        False,
        "Whether new subscription credits roll over instead of expiring at the end of the billing period",
        False,
    ),
    SettingDefinition(
        "voices.max_cloned_per_user",
        {"type": "integer", "minimum": 0, "maximum": 20},
        3,
        "Maximum number of cloned voices a user can keep",
        False,
    ),
    SettingDefinition(
        "voices.clone_credit_cost",
        {"type": "integer", "minimum": 0, "maximum": 100000},
        0,
        "Credits reserved when a voice clone is submitted",
        False,
    ),
    SettingDefinition(
        "voices.consent_statement",
        {"type": "string", "minLength": 50, "maxLength": 4000},
        VOICE_CONSENT_STATEMENT,
        "Consent statement a user accepts before cloning a voice",
        True,
    ),
    SettingDefinition(
        "voices.consent_statement_version",
        {"type": "string", "minLength": 1, "maxLength": 40, "pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]*$"},
        "2026-10-19",
        "Version label of the voice consent statement; change it whenever the statement changes",
        True,
    ),
    SettingDefinition(
        "ai.model_routing",
        {"type": "string", "minLength": 2, "maxLength": 20000},
        DEFAULT_ROUTING_JSON,
        "JSON routing per AI task: primary model, ordered fallbacks, temperature, output tokens and timeout",
        False,
        check=check_model_routing,
    ),
    SettingDefinition(
        "ai.job_token_budget",
        {"type": "integer", "minimum": 10000, "maximum": 5000000},
        600000,
        "Model tokens one job may use before it stops with budget_exceeded",
        False,
    ),
    SettingDefinition(
        "ai.max_repairs",
        {"type": "integer", "minimum": 0, "maximum": 3},
        2,
        "Repair attempts per scene before the safe fallback scene replaces it",
        False,
    ),
    SettingDefinition(
        "ai.scene_concurrency",
        {"type": "integer", "minimum": 1, "maximum": 8},
        4,
        "Scene modules generated in parallel per job",
        False,
    ),
    SettingDefinition(
        "ai.approval_timeout_hours",
        {"type": "integer", "minimum": 1, "maximum": 720},
        168,
        "Hours a job may wait for storyboard approval before it is cancelled and its credits released",
        False,
    ),
    SettingDefinition(
        "ai.stage_timeout_minutes",
        {"type": "integer", "minimum": 5, "maximum": 240},
        30,
        "Minutes a job may stay in one stage before the sweeper fails it and releases its credits",
        False,
    ),
    SettingDefinition(
        "ai.speaking_rate_min_milli_wps",
        {"type": "integer", "minimum": 1000, "maximum": 4000},
        2000,
        "Slowest narration rate a storyboard scene may plan, in thousandths of a word per second",
        False,
    ),
    SettingDefinition(
        "ai.speaking_rate_max_milli_wps",
        {"type": "integer", "minimum": 1000, "maximum": 5000},
        2800,
        "Fastest narration rate a storyboard scene may plan, in thousandths of a word per second",
        False,
    ),
    SettingDefinition(
        "ai.skill_token_budget",
        {"type": "integer", "minimum": 1000, "maximum": 60000},
        12000,
        "Token budget for the full content of the skills selected for one generation",
        False,
    ),
    SettingDefinition(
        "ai.visual_review_enabled",
        {"type": "boolean"},
        True,
        "Whether sampled key frames are reviewed by a vision model before rendering",
        False,
    ),
    SettingDefinition(
        "charging.base_credits",
        {"type": "integer", "minimum": 0, "maximum": 100000},
        20,
        "Credits charged for every video before the per-second cost",
        True,
    ),
    SettingDefinition(
        "charging.credits_per_second",
        {"type": "integer", "minimum": 0, "maximum": 10000},
        2,
        "Credits charged per second of final video duration",
        True,
    ),
    SettingDefinition(
        "charging.extra_aspect_percent",
        {"type": "integer", "minimum": 0, "maximum": 300},
        40,
        "Percentage added to the subtotal for each aspect after the first",
        True,
    ),
    SettingDefinition(
        "charging.cloned_voice_premium",
        {"type": "integer", "minimum": 0, "maximum": 100000},
        10,
        "Credits added when the narration uses a cloned voice",
        True,
    ),
    SettingDefinition(
        "jobs.max_active_per_user",
        {"type": "integer", "minimum": 1, "maximum": 10},
        2,
        "Jobs a user may have queued or running at the same time",
        False,
    ),
    SettingDefinition(
        "evals.ci_live_budget_micros_usd",
        {"type": "integer", "minimum": 0, "maximum": 100000000},
        2000000,
        "Spending cap in millionths of a US dollar for the live eval subset that runs on pull requests",
        False,
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
        minimum_length = schema.get("minLength")
        maximum_length = schema.get("maxLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            raise ValueError("Setting is too short")
        if isinstance(maximum_length, int) and len(value) > maximum_length:
            raise ValueError("Setting is too long")
        string_pattern = schema.get("pattern")
        if isinstance(string_pattern, str) and re.fullmatch(string_pattern, value) is None:
            raise ValueError("Setting has an invalid format")
        if definition.check is not None:
            definition.check(value)
        return value
    raise ValueError("Setting value has the wrong type")
