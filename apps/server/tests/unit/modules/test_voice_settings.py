import pytest

from motionile.modules.platform import SETTINGS
from motionile.modules.platform.registry import validate_setting

VOICE_KEYS = (
    "voices.max_cloned_per_user",
    "voices.clone_credit_cost",
    "voices.consent_statement",
    "voices.consent_statement_version",
)


@pytest.mark.parametrize("key", sorted(SETTINGS))
def test_every_default_satisfies_its_own_schema(key: str) -> None:
    definition = SETTINGS[key]

    assert validate_setting(key, definition.default) == definition.default
    assert definition.description


def test_voice_settings_are_registered() -> None:
    assert set(VOICE_KEYS) <= set(SETTINGS)


def test_cloned_voice_limit_is_a_private_bounded_integer() -> None:
    definition = SETTINGS["voices.max_cloned_per_user"]

    assert definition.schema == {"type": "integer", "minimum": 0, "maximum": 20}
    assert definition.default == 3
    assert definition.public is False


def test_clone_credit_cost_is_a_private_bounded_integer() -> None:
    definition = SETTINGS["voices.clone_credit_cost"]

    assert definition.schema == {"type": "integer", "minimum": 0, "maximum": 100000}
    assert definition.default == 0
    assert definition.public is False


def test_consent_statement_is_public_and_states_the_commitments() -> None:
    definition = SETTINGS["voices.consent_statement"]
    statement = definition.default

    assert definition.public is True
    assert isinstance(statement, str)
    assert 50 <= len(statement) <= 4000
    assert "my own" in statement
    assert "synthetic copy" in statement
    assert "voice provider" in statement
    assert "impersonate" in statement
    assert "delete this voice at any time" in statement


def test_consent_statement_version_is_public_and_dated() -> None:
    definition = SETTINGS["voices.consent_statement_version"]

    assert definition.public is True
    assert definition.default == "2026-10-19"


@pytest.mark.parametrize("value", [0, 3, 20])
def test_cloned_voice_limit_accepts_values_in_range(value: int) -> None:
    assert validate_setting("voices.max_cloned_per_user", value) == value


@pytest.mark.parametrize("value", [-1, 21])
def test_cloned_voice_limit_rejects_values_out_of_range(value: int) -> None:
    with pytest.raises(ValueError, match="allowed range"):
        validate_setting("voices.max_cloned_per_user", value)


@pytest.mark.parametrize("value", [0, 100000])
def test_clone_credit_cost_accepts_boundaries(value: int) -> None:
    assert validate_setting("voices.clone_credit_cost", value) == value


@pytest.mark.parametrize("value", [-1, 100001])
def test_clone_credit_cost_rejects_values_out_of_range(value: int) -> None:
    with pytest.raises(ValueError, match="allowed range"):
        validate_setting("voices.clone_credit_cost", value)


@pytest.mark.parametrize("value", ["3", 3.0, True, None, [3]])
def test_integer_settings_reject_other_types(value: object) -> None:
    with pytest.raises(ValueError, match="integer"):
        validate_setting("voices.max_cloned_per_user", value)


def test_consent_statement_accepts_text_within_bounds() -> None:
    assert validate_setting("voices.consent_statement", "x" * 50) == "x" * 50
    assert validate_setting("voices.consent_statement", "y" * 4000) == "y" * 4000


def test_consent_statement_rejects_text_that_is_too_short() -> None:
    with pytest.raises(ValueError, match="too short"):
        validate_setting("voices.consent_statement", "x" * 49)
    with pytest.raises(ValueError, match="too short"):
        validate_setting("voices.consent_statement", "")


def test_consent_statement_rejects_text_that_is_too_long() -> None:
    with pytest.raises(ValueError, match="too long"):
        validate_setting("voices.consent_statement", "x" * 4001)


@pytest.mark.parametrize("value", [1, True, None, ["text"]])
def test_string_settings_reject_other_types(value: object) -> None:
    with pytest.raises(ValueError, match="wrong type"):
        validate_setting("voices.consent_statement", value)


@pytest.mark.parametrize("value", ["2026-10-19", "2027-01-02", "v2", "1", "a" * 40])
def test_version_accepts_labels(value: str) -> None:
    assert validate_setting("voices.consent_statement_version", value) == value


@pytest.mark.parametrize("value", ["", "a" * 41, "-2026", "2026 10 19", "2026/10/19", "2026-10-19\n", " 2026-10-19"])
def test_version_rejects_malformed_labels(value: str) -> None:
    with pytest.raises(ValueError, match=r"too short|too long|invalid format"):
        validate_setting("voices.consent_statement_version", value)


def test_empty_version_is_too_short_and_bad_characters_have_an_invalid_format() -> None:
    with pytest.raises(ValueError, match="too short"):
        validate_setting("voices.consent_statement_version", "")
    with pytest.raises(ValueError, match="invalid format"):
        validate_setting("voices.consent_statement_version", "2026/10/19")
    with pytest.raises(ValueError, match="too long"):
        validate_setting("voices.consent_statement_version", "a" * 41)
