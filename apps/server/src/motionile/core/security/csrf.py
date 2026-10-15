import hmac
from uuid import UUID

from motionile.core.errors import ForbiddenError
from motionile.core.security.tokens import random_token, sign_value

MAX_CSRF_LENGTH = 256


class CsrfError(ForbiddenError):
    default_code = "csrf_failed"
    title = "CSRF verification failed"


class CsrfTokens:
    def __init__(self, secret: bytes) -> None:
        self.secret = secret

    def issue(self, family_id: UUID) -> str:
        nonce = random_token()
        return f"{nonce}.{sign_value(self.secret, str(family_id), nonce)}"

    def verify(self, family_id: UUID, cookie: str | None, header: str | None) -> None:
        if not cookie or not header or not cookie.isascii() or not header.isascii():
            raise CsrfError
        if len(cookie) > MAX_CSRF_LENGTH or not hmac.compare_digest(cookie, header):
            raise CsrfError
        nonce, separator, signature = cookie.partition(".")
        if not separator or not hmac.compare_digest(signature, sign_value(self.secret, str(family_id), nonce)):
            raise CsrfError
