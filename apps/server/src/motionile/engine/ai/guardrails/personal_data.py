import re
from enum import StrEnum
from typing import Final

import phonenumbers
from phonenumbers import Leniency, PhoneNumberMatcher

DEFAULT_PHONE_REGION: Final = "IN"
MAX_PHONE_TRIES: Final = 2_000
MIN_CARD_DIGITS: Final = 13
MAX_CARD_DIGITS: Final = 19
VERHOEFF_PERIOD: Final = 8
LUHN_DIGIT_CAP: Final = 9

EMAIL_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
EMAIL = re.compile(rf"(?<![\w.%+-])[\w.%+-]{{1,64}}@(?P<domain>(?:{EMAIL_LABEL}\.)+[A-Za-z]{{2,24}})\b")
AADHAAR_GROUPED = re.compile(r"(?<!\d)[2-9]\d{3}[ -]\d{4}[ -]\d{4}(?!\d)")
AADHAAR_CONTIGUOUS = re.compile(r"(?<!\d)[2-9]\d{11}(?!\d)")
CARD_CANDIDATE = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
CARD_PREFIX = re.compile(r"^(?:4|5[1-5]|2[2-7]|3[0-9]|6|81|82)")
IPV4_ADDRESS = re.compile(r"(?<![\d.])(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?![\d.])")
SSN = re.compile(r"(?<!\d)(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\d)")

RESERVED_EMAIL_LABELS: Final = frozenset({"example", "test", "invalid", "localhost"})
PLACEHOLDER_EMAIL_DOMAINS: Final = frozenset(
    {"domain.com", "email.com", "mail.com", "yourdomain.com", "company.com", "website.com", "site.com", "test.com"}
)

VERHOEFF_MULTIPLICATION: Final = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
VERHOEFF_PERMUTATION: Final = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


class PersonalDataKind(StrEnum):
    EMAIL = "email"
    PHONE = "phone"
    AADHAAR = "aadhaar"
    CARD = "card"
    SSN = "ssn"


def luhn_valid(digits: str) -> bool:
    total = 0
    for position, character in enumerate(reversed(digits)):
        value = int(character)
        if position % 2 == 1:
            value *= 2
            if value > LUHN_DIGIT_CAP:
                value -= LUHN_DIGIT_CAP
        total += value
    return total % 10 == 0


def verhoeff_valid(digits: str) -> bool:
    checksum = 0
    for position, character in enumerate(reversed(digits)):
        checksum = VERHOEFF_MULTIPLICATION[checksum][VERHOEFF_PERMUTATION[position % VERHOEFF_PERIOD][int(character)]]
    return checksum == 0


def only_digits(text: str) -> str:
    return "".join(character for character in text if character.isdigit())


def is_placeholder_domain(domain: str) -> bool:
    labels = domain.lower().split(".")
    return domain.lower() in PLACEHOLDER_EMAIL_DOMAINS or any(label in RESERVED_EMAIL_LABELS for label in labels)


def has_email(text: str) -> bool:
    return any(not is_placeholder_domain(match["domain"]) for match in EMAIL.finditer(text))


def has_phone(text: str) -> bool:
    without_addresses = IPV4_ADDRESS.sub(" ", text)
    matcher = PhoneNumberMatcher(
        without_addresses, DEFAULT_PHONE_REGION, leniency=Leniency.VALID, max_tries=MAX_PHONE_TRIES
    )
    return any(phonenumbers.is_valid_number(match.number) for match in matcher)


def has_aadhaar(text: str) -> bool:
    if AADHAAR_GROUPED.search(text):
        return True
    return any(verhoeff_valid(match.group()) for match in AADHAAR_CONTIGUOUS.finditer(text))


def has_card(text: str) -> bool:
    for match in CARD_CANDIDATE.finditer(text):
        digits = only_digits(match.group())
        if MIN_CARD_DIGITS <= len(digits) <= MAX_CARD_DIGITS and CARD_PREFIX.match(digits) and luhn_valid(digits):
            return True
    return False


def has_ssn(text: str) -> bool:
    return SSN.search(text) is not None


DETECTORS = (
    (PersonalDataKind.EMAIL, has_email),
    (PersonalDataKind.AADHAAR, has_aadhaar),
    (PersonalDataKind.CARD, has_card),
    (PersonalDataKind.SSN, has_ssn),
    (PersonalDataKind.PHONE, has_phone),
)


def detect_personal_data(text: str) -> tuple[PersonalDataKind, ...]:
    return tuple(kind for kind, detector in DETECTORS if detector(text))


def contains_personal_data(text: str) -> bool:
    return any(detector(text) for _, detector in DETECTORS)
