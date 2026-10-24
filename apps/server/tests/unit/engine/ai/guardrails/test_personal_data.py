import pytest

from motionile.engine.ai.guardrails import PersonalDataKind, contains_personal_data, detect_personal_data
from motionile.engine.ai.guardrails.personal_data import luhn_valid, verhoeff_valid


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Write to priya.sharma@gmail.com about it", PersonalDataKind.EMAIL),
        ("my mail is rahul_k+news@company.co.in", PersonalDataKind.EMAIL),
        ("Call me on 98765 43210 tomorrow", PersonalDataKind.PHONE),
        ("Reach her at +91 98765 43210", PersonalDataKind.PHONE),
        ("Phone: +1 650-253-0000", PersonalDataKind.PHONE),
        ("My Aadhaar is 2345 6789 0123", PersonalDataKind.AADHAAR),
        ("aadhaar 2345-6789-0123", PersonalDataKind.AADHAAR),
        ("id 234567890124", PersonalDataKind.AADHAAR),
        ("card 4111 1111 1111 1111 expires soon", PersonalDataKind.CARD),
        ("4111-1111-1111-1111", PersonalDataKind.CARD),
        ("5500005555555559 is mine", PersonalDataKind.CARD),
        ("SSN 078-05-1120", PersonalDataKind.SSN),
    ],
)
def test_detects_personal_data(text: str, kind: PersonalDataKind) -> None:
    assert kind in detect_personal_data(text)
    assert contains_personal_data(text)


@pytest.mark.parametrize(
    "text",
    [
        "Explain how binary search works",
        "How do transformers use attention in 2024?",
        "The speed of light is 299792458 meters per second",
        "Pi is 3.14159265358979 to fifteen digits",
        "Explain 1 2 3 4 5 6 7 8 9 10 as a sequence",
        "Unix time 1700000000000 in milliseconds",
        "Format an email like user@example.com",
        "Send mail to test@example.org or admin@site.test",
        "Use name@domain.com as a placeholder address",
        "Python decorators like @property and @staticmethod",
        "The year 2023-04-05 is an ISO date",
        "Version 12.4.1234 of the library",
        "ISBN 978-3-16-148410-0 identifies a book",
        "Explain the Luhn algorithm with the number 79927398713",
        "Albert Einstein published four papers in 1905",
        "Chapter 12 covers 4000 years of history",
        "A 12 digit number 123456789012 in a tutorial",
        "In the 1990s about 100 000 000 people used the internet",
    ],
)
def test_benign_text_is_not_personal_data(text: str) -> None:
    assert detect_personal_data(text) == ()
    assert not contains_personal_data(text)


def test_checksum_helpers() -> None:
    assert luhn_valid("4111111111111111")
    assert not luhn_valid("4111111111111112")
    assert verhoeff_valid("234567890124")
    assert not verhoeff_valid("234567890123")


def test_huge_inputs_are_scanned_quickly() -> None:
    text = "plain words with numbers 12 345 6789 " * 20_000

    assert not contains_personal_data(text)
