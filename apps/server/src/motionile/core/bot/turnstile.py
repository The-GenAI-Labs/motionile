from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import structlog
from fastapi import Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from motionile.core.errors import BadRequestError, ForbiddenError, ServiceUnavailableError
from motionile.core.http.safe_client import OutboundRequestBlockedError, ResponseTooLargeError, SafeHttpClient

TURNSTILE_HEADER = "X-Turnstile-Token"
MAX_TOKEN_LENGTH = 2048
FAKE_FAILING_PREFIX = "fail"

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TurnstileResult:
    success: bool
    hostname: str | None = None
    action: str | None = None
    error_codes: tuple[str, ...] = ()


@runtime_checkable
class TurnstileVerifier(Protocol):
    async def verify(self, token: str, *, remote_ip: str | None, action: str) -> TurnstileResult: ...


class SiteverifyResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    success: bool
    hostname: str | None = None
    action: str | None = None
    error_codes: list[str] = Field(default_factory=list[str], alias="error-codes")


class CloudflareTurnstileVerifier:
    def __init__(
        self,
        client: SafeHttpClient,
        *,
        secret_key: str,
        verify_url: str,
        expected_hostnames: Iterable[str],
    ) -> None:
        self.client = client
        self.secret_key = secret_key
        self.verify_url = verify_url
        self.expected_hostnames = frozenset(expected_hostnames)

    async def verify(self, token: str, *, remote_ip: str | None, action: str) -> TurnstileResult:
        form = {"secret": self.secret_key, "response": token}
        if remote_ip is not None:
            form["remoteip"] = remote_ip
        try:
            response = await self.client.post_form(self.verify_url, form)
            parsed = SiteverifyResponse.model_validate_json(response.content)
        except (OutboundRequestBlockedError, ResponseTooLargeError, ValidationError, OSError) as error:
            logger.warning("turnstile.verification_unavailable", error=type(error).__name__)
            message = "Bot verification is temporarily unavailable."
            raise ServiceUnavailableError(message, code="turnstile_unavailable") from error
        errors = tuple(parsed.error_codes)
        if not parsed.success:
            return TurnstileResult(False, parsed.hostname, parsed.action, errors)
        if self.expected_hostnames and parsed.hostname not in self.expected_hostnames:
            return TurnstileResult(False, parsed.hostname, parsed.action, (*errors, "hostname-mismatch"))
        if parsed.action != action:
            return TurnstileResult(False, parsed.hostname, parsed.action, (*errors, "action-mismatch"))
        return TurnstileResult(True, parsed.hostname, parsed.action, errors)


class FakeTurnstileVerifier:
    def __init__(self) -> None:
        self.last_remote_ip: str | None = None

    async def verify(self, token: str, *, remote_ip: str | None, action: str) -> TurnstileResult:
        self.last_remote_ip = remote_ip
        if token.startswith(FAKE_FAILING_PREFIX):
            return TurnstileResult(False, "localhost", action, ("invalid-input-response",))
        return TurnstileResult(True, "localhost", action)


class TurnstileRequiredError(BadRequestError):
    default_code = "turnstile_required"
    title = "Bot verification required"


class TurnstileFailedError(ForbiddenError):
    default_code = "turnstile_failed"
    title = "Bot verification failed"


def turnstile_verifier_of(request: Request) -> TurnstileVerifier:
    resources: object = getattr(request.app.state, "resources", None)
    verifier: object = getattr(resources, "turnstile", None)
    if not isinstance(verifier, TurnstileVerifier):
        message = "the Turnstile verifier is not configured on the application"
        raise TypeError(message)
    return verifier


def require_turnstile(action: str) -> Callable[[Request], Awaitable[TurnstileResult]]:
    async def verify_turnstile(request: Request) -> TurnstileResult:
        token = request.headers.get(TURNSTILE_HEADER)
        if not token:
            message = f"Send the Turnstile token in the {TURNSTILE_HEADER} header."
            raise TurnstileRequiredError(message)
        if len(token) > MAX_TOKEN_LENGTH:
            raise TurnstileFailedError
        client = request.client
        result = await turnstile_verifier_of(request).verify(
            token, remote_ip=client.host if client is not None else None, action=action
        )
        if not result.success:
            logger.info("turnstile.rejected", action=action, error_codes=list(result.error_codes))
            raise TurnstileFailedError
        return result

    return verify_turnstile
