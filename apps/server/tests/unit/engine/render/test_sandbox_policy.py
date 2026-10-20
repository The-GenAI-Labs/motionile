from dataclasses import dataclass, field
from typing import Any, cast

import pytest
from playwright.async_api import BrowserContext, Route

from motionile.engine.render.models import (
    Aspect,
    BrowserCrashError,
    NetworkViolationError,
    PageError,
    RenderEngineConfig,
    SandboxTimeoutError,
)
from motionile.engine.render.runtime import COMPOSITION_URL, load_runtime_bundle
from motionile.engine.render.sandbox import (
    CONTENT_SECURITY_POLICY,
    PERMISSIONS_POLICY,
    PageSpec,
    RenderSandbox,
    SandboxPage,
    chromium_launch_args,
    init_script_source,
    load_browser_expression,
    load_browser_script,
    summarize_playwright_message,
)
from motionile.engine.render.synthetic import SyntheticScene, build_synthetic_narration

NARRATION = build_synthetic_narration([SyntheticScene("main", "hello world")])
SPEC = PageSpec(html="<html>composition</html>", narration=NARRATION, aspect=Aspect.LANDSCAPE, seed=42)


@dataclass
class FakeRequest:
    url: str
    method: str = "GET"
    resource_type: str = "other"


@dataclass
class FakeRoute:
    request: FakeRequest
    fulfilled: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    aborted: list[str] = field(default_factory=list[str])

    async def fulfill(self, **kwargs: Any) -> None:
        self.fulfilled.append(kwargs)

    async def abort(self, reason: str) -> None:
        self.aborted.append(reason)


def make_page() -> SandboxPage:
    sandbox = RenderSandbox(RenderEngineConfig(parallel_pages=1))
    return SandboxPage(sandbox, cast("BrowserContext", object()), SPEC)


async def route_through(page: SandboxPage, url: str, method: str = "GET") -> FakeRoute:
    route = FakeRoute(FakeRequest(url, method))
    await page.handle_route(cast("Route", route))
    return route


def test_launch_arguments_keep_the_chromium_sandbox_and_block_name_resolution() -> None:
    config = RenderEngineConfig(browser_memory_mb=512, parallel_pages=1)

    arguments = chromium_launch_args(config, "marker-1")

    assert not any("no-sandbox" in argument for argument in arguments)
    assert not any("disable-setuid-sandbox" in argument for argument in arguments)
    assert "--host-resolver-rules=MAP * ~NOTFOUND" in arguments
    assert "--proxy-server=http://127.0.0.1:1" in arguments
    assert "--proxy-bypass-list=<-loopback>" in arguments
    assert "--js-flags=--max-old-space-size=512" in arguments
    assert "--force-webrtc-ip-handling-policy=disable_non_proxied_udp" in arguments
    assert "--motionile-render-id=marker-1" in arguments


def test_content_security_policy_lists_the_documented_directives() -> None:
    directives = {
        name: value for name, _, value in (item.partition(" ") for item in CONTENT_SECURITY_POLICY.split("; "))
    }

    assert directives["default-src"] == "'none'"
    assert directives["script-src"] == "https://runtime.motionile.local 'unsafe-inline'"
    assert directives["style-src"] == "https://runtime.motionile.local 'unsafe-inline'"
    assert directives["img-src"] == "data: https://runtime.motionile.local"
    assert directives["font-src"] == "data: https://runtime.motionile.local"
    for name in ("connect-src", "frame-src", "worker-src", "media-src", "object-src", "form-action", "base-uri"):
        assert directives[name] == "'none'"
    assert directives["sandbox"] == "allow-scripts"
    assert "unsafe-eval" not in CONTENT_SECURITY_POLICY


def test_permissions_policy_denies_every_listed_feature() -> None:
    features = PERMISSIONS_POLICY.split(", ")

    assert "camera=()" in features
    assert "microphone=()" in features
    assert "geolocation=()" in features
    assert all(feature.endswith("=()") for feature in features)


def test_init_script_embeds_the_configuration_and_the_narration() -> None:
    script = init_script_source(SPEC)

    assert script.startswith("window.__motionileConfig = {")
    assert '"aspect": "16:9"' in script
    assert '"seed": 42' in script
    assert '"totalDurationMs"' in script
    assert script.rstrip().endswith("})();")


def test_browser_scripts_never_open_the_network_themselves() -> None:
    for name in ("sandbox_init.js", "layout_probe.js"):
        source = load_browser_script(name)
        assert "http://" not in source
        assert "https://" not in source
        assert "//" not in source.replace("*/", "")


async def test_the_composition_is_fulfilled_with_the_strict_headers() -> None:
    route = await route_through(make_page(), COMPOSITION_URL)

    assert route.aborted == []
    answer = route.fulfilled[0]
    assert answer["status"] == 200
    assert answer["body"] == b"<html>composition</html>"
    assert answer["headers"]["Content-Security-Policy"] == CONTENT_SECURITY_POLICY
    assert answer["headers"]["Permissions-Policy"] == PERMISSIONS_POLICY
    assert answer["headers"]["Cache-Control"] == "no-store"


async def test_runtime_assets_are_answered_from_the_bundle() -> None:
    page = make_page()
    bundle = load_runtime_bundle()

    route = await route_through(page, "https://runtime.motionile.local/v1/gsap/gsap.min.js")
    head = await route_through(page, "https://runtime.motionile.local/v1/base.css", "HEAD")

    asset = bundle.asset("gsap/gsap.min.js")
    assert asset is not None
    assert route.fulfilled[0]["body"] == asset.body
    assert route.fulfilled[0]["headers"]["Access-Control-Allow-Origin"] == "*"
    assert head.fulfilled[0]["body"] == b""
    assert page.violations == ()


async def test_a_missing_runtime_file_is_a_404_and_not_a_violation() -> None:
    page = make_page()

    route = await route_through(page, "https://runtime.motionile.local/v1/missing.js")

    assert route.fulfilled[0]["status"] == 404
    assert page.violations == ()


async def test_preflight_and_favicon_requests_are_answered() -> None:
    page = make_page()

    preflight = await route_through(page, "https://runtime.motionile.local/v1/base.css", "OPTIONS")
    favicon = await route_through(page, "https://runtime.motionile.local/favicon.ico")

    assert preflight.fulfilled[0]["status"] == 204
    assert favicon.fulfilled[0]["status"] == 204
    assert page.violations == ()


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/secret",
        "https://example.com/x.png",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "ws://example.com/socket",
        "https://runtime.motionile.local:8443/v1/base.css",
        "http://runtime.motionile.local/v1/base.css",
        "https://runtime.motionile.local.evil.test/v1/base.css",
        "https://other.motionile.local/v1/base.css",
    ],
)
async def test_every_other_request_is_aborted_and_recorded(url: str) -> None:
    page = make_page()

    route = await route_through(page, url)

    assert route.fulfilled == []
    assert route.aborted == ["blockedbyclient"]
    assert url in page.violations[0]
    with pytest.raises(NetworkViolationError):
        page.check()


async def test_posting_to_the_composition_is_not_allowed() -> None:
    page = make_page()

    route = await route_through(page, COMPOSITION_URL, "POST")

    assert route.aborted == ["blockedbyclient"]
    assert len(page.violations) == 1


async def test_violations_are_reported_once_and_in_order() -> None:
    page = make_page()

    await route_through(page, "http://a.test/")
    await route_through(page, "http://b.test/")
    await route_through(page, "http://a.test/")

    assert [violation.split()[2] for violation in page.violations] == ["http://a.test/", "http://b.test/"]


def test_check_raises_in_priority_order() -> None:
    page = make_page()
    page.record_error("boom")
    with pytest.raises(PageError, match="boom"):
        page.check()

    page.record_violation("request GET http://x.test/ (fetch)")
    with pytest.raises(NetworkViolationError):
        page.check()

    page.mark_crashed()
    with pytest.raises(BrowserCrashError):
        page.check()


def test_classification_prefers_crash_then_violations_then_the_original_error() -> None:
    page = make_page()
    original = SandboxTimeoutError("slow")

    assert page.classify(original) is original
    page.record_violation("navigation to http://x.test/")
    assert isinstance(page.classify(original), NetworkViolationError)
    page.mark_crashed()
    assert isinstance(page.classify(original), BrowserCrashError)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Page.evaluate: Error: boom\n    at <anonymous>:1:1", "Error: boom"),
        ("Page.goto: net::ERR_FAILED\nCall log:\n  - navigating", "net::ERR_FAILED"),
        ("plain", "plain"),
    ],
)
def test_playwright_messages_are_summarized(message: str, expected: str) -> None:
    assert summarize_playwright_message(message) == expected


def test_browser_scripts_are_loaded_as_function_expressions() -> None:
    for name in ("sandbox_init.js", "layout_probe.js"):
        assert not load_browser_expression(name).endswith(";")
