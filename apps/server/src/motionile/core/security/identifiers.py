from dataclasses import dataclass
from typing import Literal

import phonenumbers
from email_validator import EmailNotValidError, validate_email

from motionile.core.errors import ValidationAppError


@dataclass(frozen=True)
class Identifier:
    kind: Literal["email", "phone"]
    value: str

    @property
    def channel(self) -> Literal["email", "whatsapp"]:
        return "email" if self.kind == "email" else "whatsapp"

    @property
    def masked(self) -> str:
        if self.kind == "email":
            local, domain = self.value.split("@")
            first, _, suffix = domain.rpartition(".")
            return f"{local[0]}•••@{first[0]}•••.{suffix}"
        number = phonenumbers.parse(self.value, None)
        return f"+{number.country_code} •••••• {self.value[-4:]}"


def normalize_identifier(value: str) -> Identifier:
    value = value.strip()
    try:
        if "@" in value:
            normalized = validate_email(value, check_deliverability=False).normalized
            return Identifier("email", normalized.casefold())
        number = phonenumbers.parse(value, "IN")
        supported = {phonenumbers.PhoneNumberType.MOBILE, phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE}
        if not phonenumbers.is_valid_number(number) or phonenumbers.number_type(number) not in supported:
            raise ValueError
        return Identifier("phone", phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164))
    except (EmailNotValidError, phonenumbers.NumberParseException, ValueError) as error:
        raise ValidationAppError(
            "Enter a valid email or WhatsApp-capable mobile number.", code="invalid_identifier"
        ) from error
