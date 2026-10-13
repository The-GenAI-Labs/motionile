import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx
import orjson

from motionile.core.config import OutboundHttpSettings

type IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
type Resolver = Callable[[str, int], Awaitable[list[IPAddress]]]

DEFAULT_PORTS = {"http": 80, "https": 443}
NAT64_PREFIX = ipaddress.IPv6Network("64:ff9b::/96")
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
SEE_OTHER = 303
METHOD_CHANGING_REDIRECTS = frozenset({301, 302})
USER_AGENT = "Motionile/1.0 (+https://motionile.com)"
CREDENTIAL_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})


class OutboundRequestBlockedError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(f"outbound request blocked: {reason}")
        self.reason = reason


class ResponseTooLargeError(Exception):
    def __init__(self, limit: int) -> None:
        super().__init__(f"response exceeded {limit} bytes")
        self.limit = limit


@dataclass(frozen=True)
class SafeResponse:
    status_code: int
    headers: httpx.Headers
    content: bytes
    url: str

    def json(self) -> Any:
        return orjson.loads(self.content)


def embedded_addresses(address: IPAddress) -> list[IPAddress]:
    candidates: list[IPAddress] = [address]
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped is not None:
            candidates.append(address.ipv4_mapped)
        if address.sixtofour is not None:
            candidates.append(address.sixtofour)
        if address.teredo is not None:
            candidates.extend(address.teredo)
        if address in NAT64_PREFIX:
            candidates.append(ipaddress.IPv4Address(int(address) & 0xFFFFFFFF))
    return candidates


def is_forbidden_address(address: IPAddress) -> bool:
    return any(
        not candidate.is_global
        or candidate.is_private
        or candidate.is_loopback
        or candidate.is_link_local
        or candidate.is_multicast
        or candidate.is_reserved
        or candidate.is_unspecified
        for candidate in embedded_addresses(address)
    )


def literal_address(host: str) -> IPAddress | None:
    try:
        return ipaddress.ip_address(host.strip("[]").split("%")[0])
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(host))
    except OSError:
        return None


async def system_resolver(host: str, port: int) -> list[IPAddress]:
    loop = asyncio.get_running_loop()
    try:
        results = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as error:
        message = f"could not resolve {host}"
        raise OutboundRequestBlockedError(message) from error
    addresses: list[IPAddress] = []
    for _, _, _, _, sockaddr in results:
        addresses.append(ipaddress.ip_address(str(sockaddr[0]).split("%")[0]))
    return addresses


@dataclass(frozen=True)
class ValidatedTarget:
    host: str
    port: int
    address: IPAddress
    is_test_origin: bool


def pinned_url(url: httpx.URL, target: ValidatedTarget) -> httpx.URL:
    if target.is_test_origin:
        return url
    return url.copy_with(host=str(target.address))


def host_header(url: httpx.URL) -> str:
    default = DEFAULT_PORTS.get(url.scheme)
    return url.host if url.port in (None, default) else f"{url.host}:{url.port}"


class SafeHttpClient:
    def __init__(
        self,
        settings: OutboundHttpSettings,
        *,
        resolver: Resolver = system_resolver,
        allowed_hosts: Iterable[str] | None = None,
        insecure_test_origins: Iterable[str] = (),
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.resolver = resolver
        self.allowed_hosts = frozenset(host.lower() for host in allowed_hosts) if allowed_hosts is not None else None
        self.insecure_test_origins = frozenset(origin.lower().rstrip("/") for origin in insecure_test_origins)
        self._client = httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(
                connect=settings.connect_timeout_seconds,
                read=settings.read_timeout_seconds,
                write=settings.read_timeout_seconds,
                pool=settings.connect_timeout_seconds,
            ),
            headers={"User-Agent": USER_AGENT},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def validate(self, url: httpx.URL) -> ValidatedTarget:
        if url.userinfo:
            message = "credentials in URLs are not allowed"
            raise OutboundRequestBlockedError(message)
        if url.scheme not in DEFAULT_PORTS:
            message = f"scheme {url.scheme!r} is not allowed"
            raise OutboundRequestBlockedError(message)
        host = url.host.lower()
        if not host:
            message = "URL has no host"
            raise OutboundRequestBlockedError(message)
        port = url.port or DEFAULT_PORTS[url.scheme]
        is_test_origin = f"{url.scheme}://{host}:{port}" in self.insecure_test_origins
        if url.scheme != "https" and not is_test_origin:
            message = "only https is allowed"
            raise OutboundRequestBlockedError(message)
        if self.allowed_hosts is not None and host not in self.allowed_hosts and not is_test_origin:
            message = f"host {host} is not allowed for this client"
            raise OutboundRequestBlockedError(message)
        literal = literal_address(host)
        addresses = [literal] if literal is not None else await self.resolver(host, port)
        if not addresses:
            message = f"{host} did not resolve"
            raise OutboundRequestBlockedError(message)
        if not is_test_origin:
            for address in addresses:
                if is_forbidden_address(address):
                    message = f"{host} resolves to a forbidden address"
                    raise OutboundRequestBlockedError(message)
        return ValidatedTarget(host=host, port=port, address=addresses[0], is_test_origin=is_test_origin)

    async def _send_once(
        self,
        method: str,
        url: httpx.URL,
        target: ValidatedTarget,
        *,
        headers: Mapping[str, str] | None,
        content: bytes | None,
    ) -> SafeResponse:
        request_headers = {**(headers or {}), "Host": host_header(url)}
        extensions: dict[str, Any] = {}
        if url.scheme == "https" and literal_address(target.host) is None:
            extensions["sni_hostname"] = target.host
        request = self._client.build_request(
            method,
            pinned_url(url, target),
            headers=request_headers,
            content=content,
            extensions=extensions,
        )
        response = await self._client.send(request, stream=True)
        try:
            chunks: list[bytes] = []
            received = 0
            async for chunk in response.aiter_bytes():
                received += len(chunk)
                if received > self.settings.max_response_bytes:
                    raise ResponseTooLargeError(self.settings.max_response_bytes)
                chunks.append(chunk)
        finally:
            await response.aclose()
        return SafeResponse(response.status_code, response.headers, b"".join(chunks), str(url))

    async def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
    ) -> SafeResponse:
        current = httpx.URL(url)
        current_method = method.upper()
        current_content = content
        current_headers = dict(headers or {})
        for _ in range(self.settings.max_redirects + 1):
            target = await self.validate(current)
            response = await self._send_once(
                current_method, current, target, headers=current_headers, content=current_content
            )
            location = response.headers.get("location")
            if response.status_code not in REDIRECT_STATUSES or location is None:
                return response
            following = current.join(location)
            if (following.scheme, following.host, following.port) != (current.scheme, current.host, current.port):
                current_headers = {
                    name: value for name, value in current_headers.items() if name.lower() not in CREDENTIAL_HEADERS
                }
            current = following
            changes_method = response.status_code in METHOD_CHANGING_REDIRECTS and current_method == "POST"
            if response.status_code == SEE_OTHER or changes_method:
                current_method = "GET"
                current_content = None
        message = "too many redirects"
        raise OutboundRequestBlockedError(message)

    async def get(self, url: str, *, headers: Mapping[str, str] | None = None) -> SafeResponse:
        return await self.request("GET", url, headers=headers)

    async def post_form(
        self, url: str, data: Mapping[str, str], *, headers: Mapping[str, str] | None = None
    ) -> SafeResponse:
        encoded = urlencode(dict(data)).encode()
        form_headers = {**(headers or {}), "Content-Type": "application/x-www-form-urlencoded"}
        return await self.request("POST", url, headers=form_headers, content=encoded)
