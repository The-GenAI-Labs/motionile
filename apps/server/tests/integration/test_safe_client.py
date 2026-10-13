import asyncio
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from motionile.core.config import OutboundHttpSettings
from motionile.core.http.safe_client import OutboundRequestBlockedError, ResponseTooLargeError, SafeHttpClient


@dataclass
class LocalServer:
    port: int
    paths: list[str] = field(default_factory=list[str])

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def handler_for(server_state: LocalServer, redirects: dict[str, str]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            server_state.paths.append(self.path)
            target = redirects.get(self.path)
            if target is not None:
                self.send_response(302)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            body = b"x" * 4096 if self.path == "/large" else b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002, ARG002
            return

    return Handler


@pytest.fixture
def victim() -> Iterator[LocalServer]:
    yield from serve({})


@pytest.fixture
def redirector(victim: LocalServer) -> Iterator[LocalServer]:
    yield from serve(
        {
            "/to-victim": f"{victim.origin}/secret",
            "/to-localhost": f"http://localhost:{victim.port}/secret",
            "/to-metadata": "http://169.254.169.254/latest/meta-data/",
            "/to-decimal": f"http://2130706433:{victim.port}/secret",
            "/to-mapped": f"http://[::ffff:127.0.0.1]:{victim.port}/secret",
            "/to-file": "file:///etc/passwd",
            "/loop": "/loop",
            "/to-self": "/final",
        }
    )


def serve(redirects: dict[str, str]) -> Iterator[LocalServer]:
    state = LocalServer(port=0)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(state, redirects))
    state.port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state
    server.shutdown()
    server.server_close()


def client_for(*test_origins: str, max_response_bytes: int = 1024) -> SafeHttpClient:
    settings = OutboundHttpSettings(max_response_bytes=max_response_bytes, max_redirects=3)
    return SafeHttpClient(settings, insecure_test_origins=test_origins)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "2130706433", "0x7f.1", "[::1]"])
async def test_blocks_loopback_targets_without_connecting(victim: LocalServer, host: str) -> None:
    client = client_for()

    with pytest.raises(OutboundRequestBlockedError):
        await client.get(f"https://{host}:{victim.port}/secret")
    await client.aclose()

    assert victim.paths == []


async def test_system_resolver_blocks_names_that_resolve_to_loopback(victim: LocalServer) -> None:
    client = client_for()

    with pytest.raises(OutboundRequestBlockedError, match="forbidden address"):
        await client.get(f"https://localhost:{victim.port}/")
    await client.aclose()


async def test_allowlisted_test_origin_is_reachable(redirector: LocalServer) -> None:
    client = client_for(redirector.origin)

    response = await client.get(f"{redirector.origin}/to-self")
    await client.aclose()

    assert response.content == b"ok"
    assert redirector.paths == ["/to-self", "/final"]


@pytest.mark.parametrize(
    "path", ["/to-victim", "/to-localhost", "/to-metadata", "/to-decimal", "/to-mapped", "/to-file"]
)
async def test_redirects_into_forbidden_targets_are_blocked(
    redirector: LocalServer, victim: LocalServer, path: str
) -> None:
    client = client_for(redirector.origin)

    with pytest.raises(OutboundRequestBlockedError):
        await client.get(f"{redirector.origin}{path}")
    await client.aclose()

    assert victim.paths == []


async def test_redirect_loops_are_cut_off(redirector: LocalServer) -> None:
    client = client_for(redirector.origin)

    with pytest.raises(OutboundRequestBlockedError, match="too many redirects"):
        await client.get(f"{redirector.origin}/loop")
    await client.aclose()

    assert len(redirector.paths) == 4


async def test_large_responses_are_cut_off(victim: LocalServer) -> None:
    client = client_for(victim.origin)

    with pytest.raises(ResponseTooLargeError):
        await client.get(f"{victim.origin}/large")
    await client.aclose()


async def test_unresolvable_hosts_are_blocked() -> None:
    client = client_for()

    with pytest.raises(OutboundRequestBlockedError):
        await asyncio.wait_for(client.get("https://does-not-exist.invalid/"), timeout=10)
    await client.aclose()
