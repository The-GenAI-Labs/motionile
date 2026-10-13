import ipaddress
from collections.abc import Callable

import httpx
import pytest

from motionile.core.config import OutboundHttpSettings
from motionile.core.http.safe_client import (
    IPAddress,
    OutboundRequestBlockedError,
    ResponseTooLargeError,
    SafeHttpClient,
    is_forbidden_address,
    literal_address,
)

PUBLIC_ADDRESS = ipaddress.ip_address("93.184.216.34")

type Handler = Callable[[httpx.Request], httpx.Response]


def make_client(
    handler: Handler,
    *,
    dns: dict[str, list[str]] | None = None,
    settings: OutboundHttpSettings | None = None,
    allowed_hosts: list[str] | None = None,
    insecure_test_origins: tuple[str, ...] = (),
) -> SafeHttpClient:
    table = dns if dns is not None else {"api.example.com": [str(PUBLIC_ADDRESS)]}

    async def resolve(host: str, _port: int) -> list[IPAddress]:
        return [ipaddress.ip_address(value) for value in table.get(host, [])]

    return SafeHttpClient(
        settings or OutboundHttpSettings(),
        resolver=resolve,
        allowed_hosts=allowed_hosts,
        insecure_test_origins=insecure_test_origins,
        transport=httpx.MockTransport(handler),
    )


def ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True})


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104
        "224.0.0.1",
        "240.0.0.1",
        "255.255.255.255",
        "198.18.0.1",
        "192.0.0.1",
        "192.0.2.1",
        "::1",
        "::",
        "fc00::1",
        "fd12:3456::1",
        "fe80::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:169.254.169.254",
        "2002:7f00:1::",
        "2002:a00:1::",
        "64:ff9b::7f00:1",
        "64:ff9b::a9fe:a9fe",
        "2001:0:4136:e378:8000:63bf:80ff:fffe",
        "2001:db8::1",
    ],
)
def test_forbids_non_public_addresses(address: str) -> None:
    assert is_forbidden_address(ipaddress.ip_address(address))


@pytest.mark.parametrize("address", ["93.184.216.34", "1.1.1.1", "2606:4700:4700::1111"])
def test_allows_public_addresses(address: str) -> None:
    assert not is_forbidden_address(ipaddress.ip_address(address))


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", "127.0.0.1"),
        ("2130706433", "127.0.0.1"),
        ("0x7f000001", "127.0.0.1"),
        ("0177.0.0.1", "127.0.0.1"),
        ("127.1", "127.0.0.1"),
        ("[::1]", "::1"),
        ("fe80::1%eth0", "fe80::1"),
        ("api.example.com", None),
    ],
)
def test_parses_literal_address_tricks(host: str, expected: str | None) -> None:
    parsed = literal_address(host)

    assert (str(parsed) if parsed is not None else None) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com/",
        "ftp://api.example.com/",
        "file:///etc/passwd",
        "https://user:pass@api.example.com/",
        "https://127.0.0.1/",
        "https://2130706433/",
        "https://0x7f000001/",
        "https://[::1]/",
        "https://[::ffff:7f00:1]/",
        "https://169.254.169.254/latest/meta-data/",
        "https://internal.example.com/",
        "https://unresolvable.example.com/",
    ],
)
async def test_blocks_forbidden_targets(url: str) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200)

    client = make_client(handler, dns={"api.example.com": ["93.184.216.34"], "internal.example.com": ["10.1.2.3"]})

    with pytest.raises(OutboundRequestBlockedError):
        await client.get(url)

    assert calls == []


async def test_blocks_when_any_resolved_address_is_forbidden() -> None:
    client = make_client(ok, dns={"api.example.com": ["93.184.216.34", "127.0.0.1"]})

    with pytest.raises(OutboundRequestBlockedError, match="forbidden address"):
        await client.get("https://api.example.com/")


async def test_pins_the_validated_address_and_keeps_host_and_sni() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    client = make_client(handler)

    response = await client.get("https://api.example.com/path?q=1")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert seen[0].url.host == str(PUBLIC_ADDRESS)
    assert seen[0].url.path == "/path"
    assert seen[0].headers["host"] == "api.example.com"
    assert seen[0].extensions["sni_hostname"] == "api.example.com"
    assert seen[0].headers["user-agent"].startswith("Motionile/")


async def test_keeps_non_default_port_in_host_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    await make_client(handler).get("https://api.example.com:8443/")

    assert seen[0].headers["host"] == "api.example.com:8443"


async def test_enforces_allowed_hosts() -> None:
    client = make_client(ok, allowed_hosts=["challenges.cloudflare.com"])

    with pytest.raises(OutboundRequestBlockedError, match="not allowed"):
        await client.get("https://api.example.com/")


@pytest.mark.parametrize(
    "location",
    [
        "https://127.0.0.1/",
        "https://169.254.169.254/latest/meta-data/",
        "http://api.example.com/",
        "https://internal.example.com/",
        "https://[::ffff:a9fe:a9fe]/",
        "file:///etc/passwd",
    ],
)
async def test_revalidates_every_redirect(location: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": location})
        return httpx.Response(200)

    client = make_client(handler, dns={"api.example.com": ["93.184.216.34"], "internal.example.com": ["10.1.2.3"]})

    with pytest.raises(OutboundRequestBlockedError):
        await client.get("https://api.example.com/start")


async def test_follows_safe_relative_redirects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(301, headers={"Location": "/final"})
        return httpx.Response(200, content=b"done")

    response = await make_client(handler).get("https://api.example.com/start")

    assert response.content == b"done"
    assert response.url == "https://api.example.com/final"


async def test_stops_after_too_many_redirects() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "/again"})

    client = make_client(handler, settings=OutboundHttpSettings(max_redirects=2))

    with pytest.raises(OutboundRequestBlockedError, match="too many redirects"):
        await client.get("https://api.example.com/")


async def test_strips_credentials_on_cross_origin_redirect() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(307, headers={"Location": "https://cdn.example.com/file"})
        return httpx.Response(200)

    client = make_client(handler, dns={"api.example.com": ["93.184.216.34"], "cdn.example.com": ["93.184.216.35"]})

    await client.get("https://api.example.com/", headers={"Authorization": "Bearer secret", "Accept": "text/plain"})

    assert "authorization" not in seen[1].headers
    assert seen[1].headers["accept"] == "text/plain"
    assert seen[1].headers["host"] == "cdn.example.com"


async def test_keeps_credentials_on_same_origin_redirect() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(307, headers={"Location": "/next"})
        return httpx.Response(200)

    await make_client(handler).get("https://api.example.com/", headers={"Authorization": "Bearer secret"})

    assert seen[1].headers["authorization"] == "Bearer secret"


@pytest.mark.parametrize(("status", "expected_method"), [(301, "GET"), (302, "GET"), (303, "GET"), (307, "POST")])
async def test_redirect_method_rules(status: int, expected_method: str) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if len(seen) == 1:
            return httpx.Response(status, headers={"Location": "/next"})
        return httpx.Response(200)

    await make_client(handler).post_form("https://api.example.com/", {"a": "b"})

    assert seen[0].content == b"a=b"
    assert seen[0].headers["content-type"] == "application/x-www-form-urlencoded"
    assert seen[1].method == expected_method
    assert (seen[1].content == b"a=b") is (expected_method == "POST")


async def test_caps_response_size() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 4096)

    client = make_client(handler, settings=OutboundHttpSettings(max_response_bytes=1024))

    with pytest.raises(ResponseTooLargeError):
        await client.get("https://api.example.com/")


async def test_insecure_test_origin_skips_address_checks_without_pinning() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    client = make_client(handler, dns={"localhost": ["127.0.0.1"]}, insecure_test_origins=("http://localhost:9000/",))

    await client.get("http://localhost:9000/health")
    await client.aclose()

    assert seen[0].url.host == "localhost"


async def test_insecure_test_origin_is_port_specific() -> None:
    client = make_client(ok, dns={"localhost": ["127.0.0.1"]}, insecure_test_origins=("http://localhost:9000",))

    with pytest.raises(OutboundRequestBlockedError):
        await client.get("http://localhost:9001/")
