import asyncio
import hashlib
import secrets
from http import HTTPStatus

import httpx
import structlog
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from motionile.core.errors import ValidationAppError
from motionile.core.http.safe_client import OutboundRequestBlockedError, ResponseTooLargeError, SafeHttpClient

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
HIBP_PREFIX_LENGTH = 5
logger = structlog.get_logger(__name__)


class Passwords:
    def __init__(self, client: SafeHttpClient, *, check_breaches: bool) -> None:
        self.client = client
        self.check_breaches = check_breaches
        self.hasher = PasswordHasher()
        self.dummy_hash = self.hasher.hash(secrets.token_urlsafe(32))

    async def validate(self, password: str) -> None:
        if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
            raise ValidationAppError("Password must contain 10 to 128 characters.", code="password_policy")
        if self.check_breaches and await self.is_breached(password):
            raise ValidationAppError("Choose a password not found in known breaches.", code="password_breached")

    async def is_breached(self, password: str) -> bool:
        digest = hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()
        try:
            response = await self.client.get(
                f"https://api.pwnedpasswords.com/range/{digest[:HIBP_PREFIX_LENGTH]}",
                headers={"Add-Padding": "true"},
            )
            if response.status_code != HTTPStatus.OK:
                raise OSError
            for line in response.content.decode().splitlines():
                suffix, _, count = line.partition(":")
                if secrets.compare_digest(suffix, digest[HIBP_PREFIX_LENGTH:]) and int(count) > 0:
                    return True
        except (httpx.HTTPError, OSError, ValueError, OutboundRequestBlockedError, ResponseTooLargeError):
            logger.warning("auth.password_breach_check_unavailable")
        return False

    async def hash(self, password: str) -> str:
        return await asyncio.to_thread(self.hasher.hash, password)

    async def verify(self, password: str, encoded: str | None) -> bool:
        try:
            valid = await asyncio.to_thread(self.hasher.verify, encoded or self.dummy_hash, password)
        except (VerificationError, InvalidHashError):
            return False
        return valid and encoded is not None

    def needs_rehash(self, encoded: str) -> bool:
        return self.hasher.check_needs_rehash(encoded)
