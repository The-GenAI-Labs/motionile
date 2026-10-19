import asyncio
import re
import secrets
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, cast
from urllib.parse import urlencode

import httpx
import orjson
import structlog

from motionile.core.http.safe_client import (
    OutboundRequestBlockedError,
    ResponseTooLargeError,
    SafeHttpClient,
    SafeResponse,
)
from motionile.engine.audio.providers.base import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderError,
    ProviderNotFoundError,
    ProviderRateLimitedError,
    ProviderRejectedError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)

logger = structlog.get_logger(__name__)

type Sleep = Callable[[float], Awaitable[None]]
type JsonObject = dict[str, Any]

SERVER_ERROR_FLOOR = 500
REASON_PATTERN = re.compile(r"[a-z0-9_]{1,64}")
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")
MULTIPART_BOUNDARY_BYTES = 16
CRLF = b"\r\n"
ISO_639_1_LENGTH = 2


@dataclass(frozen=True, slots=True)
class ProviderEndpoint:
    provider: str
    base_url: str
    headers: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class ApiRequest:
    method: str
    path: str
    replayable: bool
    query: Mapping[str, str] | None = None
    json_body: Mapping[str, object] | None = None
    multipart: tuple[bytes, str] | None = None
    accept: str = "application/json"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 4.0
    retry_after_cap_seconds: float = 8.0

    def backoff(self, attempt: int) -> float:
        return min(self.base_delay_seconds * 2 ** (attempt - 1), self.max_delay_seconds)


@dataclass(frozen=True, slots=True)
class MultipartFile:
    field_name: str
    filename: str
    content: bytes
    content_type: str


def safe_identifier(value: str) -> str:
    if IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ProviderRejectedError("the provider identifier is malformed", reason="invalid_identifier")
    return value


def iso639_1(language: str | None) -> str | None:
    if language is None:
        return None
    primary = re.split(r"[-_]", language.strip().lower(), maxsplit=1)[0]
    return primary if len(primary) == ISO_639_1_LENGTH and primary.isalpha() else None


def header_safe(value: str) -> str:
    return value.replace("\r", "").replace("\n", "").replace('"', "%22")


def encode_multipart(fields: Sequence[tuple[str, str]], files: Sequence[MultipartFile]) -> tuple[bytes, str]:
    boundary = secrets.token_hex(MULTIPART_BOUNDARY_BYTES)
    delimiter = f"--{boundary}".encode()
    parts: list[bytes] = []
    for name, value in fields:
        parts.append(
            delimiter
            + CRLF
            + f'Content-Disposition: form-data; name="{header_safe(name)}"'.encode()
            + CRLF
            + CRLF
            + value.encode("utf-8")
            + CRLF
        )
    for file in files:
        disposition = f'Content-Disposition: form-data; name="{header_safe(file.field_name)}"; '
        disposition += f'filename="{header_safe(file.filename)}"'
        parts.append(
            delimiter
            + CRLF
            + disposition.encode("utf-8")
            + CRLF
            + f"Content-Type: {header_safe(file.content_type)}".encode()
            + CRLF
            + CRLF
            + file.content
            + CRLF
        )
    parts.append(delimiter + b"--" + CRLF)
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def retry_after_seconds(response: SafeResponse) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def machine_reason(response: SafeResponse) -> str | None:
    try:
        body: object = response.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    detail = cast("Mapping[str, object]", body).get("detail")
    candidate: object = None
    if isinstance(detail, dict):
        candidate = cast("Mapping[str, object]", detail).get("status")
    else:
        error = cast("Mapping[str, object]", body).get("error")
        if isinstance(error, dict):
            candidate = cast("Mapping[str, object]", error).get("code")
    if isinstance(candidate, str) and REASON_PATTERN.fullmatch(candidate):
        return candidate
    return None


def error_for(response: SafeResponse) -> ProviderError:
    status = response.status_code
    reason = machine_reason(response)
    message = f"the provider answered with status {status}"
    if status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
        return ProviderAuthenticationError(message, status_code=status, reason=reason)
    if status == HTTPStatus.NOT_FOUND:
        return ProviderNotFoundError(message, status_code=status, reason=reason)
    if status == HTTPStatus.TOO_MANY_REQUESTS:
        return ProviderRateLimitedError(
            message, status_code=status, reason=reason, retry_after_seconds=retry_after_seconds(response)
        )
    if status in (HTTPStatus.REQUEST_TIMEOUT, HTTPStatus.GATEWAY_TIMEOUT):
        return ProviderTimeoutError(message, status_code=status, reason=reason)
    if status >= SERVER_ERROR_FLOOR:
        return ProviderUnavailableError(message, status_code=status, reason=reason)
    return ProviderRejectedError(message, status_code=status, reason=reason)


class ProviderHttp:
    def __init__(
        self,
        http: SafeHttpClient,
        endpoint: ProviderEndpoint,
        *,
        sleep: Sleep = asyncio.sleep,
        retry: RetryPolicy | None = None,
    ) -> None:
        self._http = http
        self._provider = endpoint.provider
        self._base_url = endpoint.base_url.rstrip("/")
        self._headers = dict(endpoint.headers)
        self._sleep = sleep
        self._retry = retry or RetryPolicy()

    def __repr__(self) -> str:
        return f"ProviderHttp(provider={self._provider!r}, base_url={self._base_url!r})"

    async def _send_once(
        self, method: str, url: str, headers: Mapping[str, str], content: bytes | None
    ) -> SafeResponse:
        try:
            return await self._http.request(method, url, headers=headers, content=content)
        except httpx.TimeoutException:
            raise ProviderTimeoutError("the provider did not answer in time") from None
        except httpx.TransportError:
            raise ProviderUnavailableError("the provider could not be reached") from None
        except OutboundRequestBlockedError as error:
            raise ProviderConfigurationError(f"the provider endpoint was refused: {error.reason}") from None
        except ResponseTooLargeError:
            raise ProviderResponseError("the provider response was too large") from None

    async def _attempt(self, method: str, url: str, headers: Mapping[str, str], content: bytes | None) -> SafeResponse:
        response = await self._send_once(method, url, headers, content)
        if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
            raise error_for(response)
        return response

    def _delay_for(self, error: ProviderError, attempt: int) -> float:
        if isinstance(error, ProviderRateLimitedError) and error.retry_after_seconds is not None:
            return min(error.retry_after_seconds, self._retry.retry_after_cap_seconds)
        return self._retry.backoff(attempt)

    async def send(self, request: ApiRequest) -> SafeResponse:
        url = f"{self._base_url}{request.path}"
        if request.query:
            url = f"{url}?{urlencode(dict(request.query))}"
        headers = {**self._headers, "Accept": request.accept}
        content: bytes | None = None
        if request.json_body is not None:
            content = orjson.dumps(dict(request.json_body))
            headers["Content-Type"] = "application/json"
        elif request.multipart is not None:
            content, headers["Content-Type"] = request.multipart
        attempt = 1
        while True:
            try:
                return await self._attempt(request.method, url, headers, content)
            except ProviderError as error:
                retryable = isinstance(error, ProviderRateLimitedError) or (request.replayable and error.retryable)
                logger.warning(
                    "audio_provider.request_failed",
                    provider=self._provider,
                    method=request.method,
                    attempt=attempt,
                    error=error.code,
                    status=error.status_code,
                )
                if not retryable or attempt >= self._retry.attempts:
                    raise
                await self._sleep(self._delay_for(error, attempt))
                attempt += 1

    async def send_json(self, request: ApiRequest) -> JsonObject:
        response = await self.send(request)
        try:
            payload: object = response.json()
        except ValueError:
            raise ProviderResponseError("the provider response is not JSON") from None
        if not isinstance(payload, dict):
            raise ProviderResponseError("the provider response is not a JSON object")
        return cast("JsonObject", payload)
