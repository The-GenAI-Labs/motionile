import pytest

from motionile.engine.ai.llm.redaction import REDACTED, redact, redact_value, trace_text


@pytest.mark.parametrize(
    "secret",
    [
        "Authorization: Bearer abc123DEF456ghi789",
        "bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r",
        "sk-ant-api03-AbCdEfGhIjKlMnOpQrStUvWxYz",
        "sk-proj-0123456789abcdefghij",
        "pk-lf-1234567890abcdefgh",
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_0123456789abcdefghijABCDEFGHIJ",
        "api_key=hunter2hunter2",
        'password: "correct horse battery"',
    ],
)
def test_credentials_are_removed(secret: str) -> None:
    redacted = redact(f"before {secret} after")

    assert REDACTED in redacted
    assert redacted.startswith("before")
    assert redacted.endswith("after")
    for fragment in ("abc123DEF456ghi789", "dBjftJeZ4CVPmB92K27uhbUJU1p1r", "AbCdEfGhIjKlMnOpQrStUvWxYz", "hunter2"):
        assert fragment not in redacted


@pytest.mark.parametrize(
    "contact",
    ["rishabh.k+test@example.co.in", "+91 98765 43210", "(415) 555-2671", "9876543210", "+1-415-555-2671"],
)
def test_email_addresses_and_phone_numbers_are_removed(contact: str) -> None:
    assert redact(f"Call me on {contact} today") == f"Call me on {REDACTED} today"


def test_ordinary_narration_is_untouched() -> None:
    text = "A thousand items need ten steps, and a million need about twenty. Version 2.4 ships in 2026."

    assert redact(text) == text


def test_identifiers_with_digit_groups_are_not_mistaken_for_phone_numbers() -> None:
    text = "scene 0190d2f4-1234-5678-9abc-def012345678 at 12:30:45"

    assert redact(text) == text


def test_nested_values_are_redacted_and_other_types_pass_through() -> None:
    value = {"input": ["mail a@b.io", {"token": "Bearer abcdefgh12345678"}], "count": 3, "flag": True}

    assert redact_value(value) == {
        "input": [f"mail {REDACTED}", {"token": f"Bearer {REDACTED}"}],
        "count": 3,
        "flag": True,
    }


def test_trace_text_redacts_before_truncating() -> None:
    padding = "x" * 3_990
    text = f"{padding} someone@example.com tail"

    assert "someone" not in trace_text(text)
    assert len(trace_text(text)) <= 4_000
    assert trace_text(text, limit=5) == "xxxxx"
