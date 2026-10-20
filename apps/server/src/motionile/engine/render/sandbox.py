import asyncio
import base64
import contextlib
import json
import re
import uuid
from collections.abc import AsyncGenerator, Awaitable, Iterable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib import resources
from types import TracebackType
from typing import Any, Protocol, Self, cast
from urllib.parse import urldefrag

from playwright.async_api import (
    Browser,
    BrowserContext,
    CDPSession,
    ConsoleMessage,
    Frame,
    Page,
    Playwright,
    Route,
    WebSocketRoute,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.render.models import (
    Aspect,
    BrowserCrashError,
    NetworkViolationError,
    PageError,
    RenderEngineConfig,
    SandboxError,
    SandboxTimeoutError,
)
from motionile.engine.render.runtime import (
    COMPOSITION_URL,
    RUNTIME_ORIGIN,
    RuntimeBundle,
    load_runtime_bundle,
)

EPOCH_MS = 1_700_000_000_000
CLOCK_PAUSED_AT_MS = EPOCH_MS + 1_000
CLOCK_JUMP_THRESHOLD_MS = 1_000
SETTLE_FRAMES = 2
LAUNCH_TIMEOUT_MS = 60_000
TEARDOWN_TIMEOUT_SECONDS = 5.0
MAX_REPORTED_ERRORS = 20
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
BLACK_HOLE_PROXY = "http://127.0.0.1:1"
PROCESS_MARKER_FLAG = "--motionile-render-id"
DOCUMENT_CONTENT_TYPE = "text/html; charset=utf-8"

CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'none'",
        f"script-src {RUNTIME_ORIGIN} 'unsafe-inline'",
        f"style-src {RUNTIME_ORIGIN} 'unsafe-inline'",
        f"img-src data: {RUNTIME_ORIGIN}",
        f"font-src data: {RUNTIME_ORIGIN}",
        "connect-src 'none'",
        "frame-src 'none'",
        "worker-src 'none'",
        "media-src 'none'",
        "object-src 'none'",
        "form-action 'none'",
        "base-uri 'none'",
        "sandbox allow-scripts",
    )
)
PERMISSIONS_POLICY = ", ".join(
    f"{feature}=()"
    for feature in (
        "accelerometer",
        "autoplay",
        "camera",
        "clipboard-read",
        "clipboard-write",
        "display-capture",
        "encrypted-media",
        "fullscreen",
        "geolocation",
        "gyroscope",
        "hid",
        "magnetometer",
        "microphone",
        "midi",
        "payment",
        "serial",
        "usb",
        "xr-spatial-tracking",
    )
)
DOCUMENT_HEADERS: Mapping[str, str] = {
    "Content-Type": DOCUMENT_CONTENT_TYPE,
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "Permissions-Policy": PERMISSIONS_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}
CORS_PREFLIGHT_HEADERS: Mapping[str, str] = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "*",
}
MATCH_ALL = re.compile(".*")
CRASH_MARKERS = ("crash", "target closed", "has been closed", "browser closed", "connection closed")
IGNORED_CONSOLE_MARKERS = ("ERR_BLOCKED_BY_CLIENT",)
POLICY_CONSOLE_MARKERS = (
    "Content Security Policy",
    "violates the following",
    "Not allowed to load local resource",
    "Blocked form submission",
    "Blocked opening",
    "is sandboxed",
)


class CdpClient(Protocol):
    async def send(self, method: str, params: dict[str, object] | None = None) -> dict[str, Any]: ...


def chromium_launch_args(config: RenderEngineConfig, marker: str) -> list[str]:
    return [
        "--host-resolver-rules=MAP * ~NOTFOUND",
        f"--proxy-server={BLACK_HOLE_PROXY}",
        "--proxy-bypass-list=<-loopback>",
        f"--js-flags=--max-old-space-size={config.browser_memory_mb}",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--force-color-profile=srgb",
        "--font-render-hinting=none",
        "--disable-lcd-text",
        "--hide-scrollbars",
        "--mute-audio",
        "--disable-breakpad",
        "--disable-sync",
        "--deny-permission-prompts",
        f"{PROCESS_MARKER_FLAG}={marker}",
    ]


def load_browser_script(name: str) -> str:
    return resources.files("motionile.engine.render").joinpath("browser", name).read_text(encoding="utf-8")


def load_browser_expression(name: str) -> str:
    return load_browser_script(name).strip().removesuffix(";")


def init_script_source(spec: "PageSpec") -> str:
    configuration = {
        "aspect": spec.aspect.value,
        "seed": spec.seed,
        "narration": spec.narration.window_payload(),
    }
    return f"window.__motionileConfig = {json.dumps(configuration)};\n{load_browser_expression('sandbox_init.js')};"


@dataclass(frozen=True)
class PageSpec:
    html: str
    narration: NarrationDocument
    aspect: Aspect
    seed: int
    language: str = "en-US"
    fps: int | None = None


@dataclass(frozen=True)
class SceneInfo:
    id: str
    start_ms: int
    end_ms: int
    content_end_ms: int


@dataclass(frozen=True)
class CompositionInfo:
    duration_ms: int
    timeline_duration_ms: int
    aspects: tuple[str, ...]
    scenes: tuple[SceneInfo, ...]
    scene_elements: tuple[str, ...]


def parse_composition_info(payload: Mapping[str, Any]) -> CompositionInfo:
    composition = cast("Mapping[str, Any]", payload["composition"])
    scenes = tuple(
        SceneInfo(
            id=str(scene["id"]),
            start_ms=int(scene["startMs"]),
            end_ms=int(scene["endMs"]),
            content_end_ms=int(scene["contentEndMs"]),
        )
        for scene in cast("list[Mapping[str, Any]]", composition["scenes"])
    )
    return CompositionInfo(
        duration_ms=int(composition["durationMs"]),
        timeline_duration_ms=int(payload["timelineDurationMs"]),
        aspects=tuple(str(aspect) for aspect in cast("list[str]", composition["aspects"])),
        scenes=scenes,
        scene_elements=tuple(str(item) for item in cast("list[str]", payload["sceneElements"])),
    )


def summarize_playwright_message(message: str) -> str:
    lines: list[str] = []
    for raw in message.splitlines():
        line = raw.strip()
        if not line or line.startswith("at ") or line.startswith("Call log"):
            break
        lines.append(line)
    summary = " ".join(lines) or message.strip()
    return summary.split(": ", 1)[1] if summary.startswith(("Page.evaluate: ", "Page.goto: ")) else summary


def unique_limited(values: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
        if len(seen) >= MAX_REPORTED_ERRORS:
            break
    return list(seen)


async def close_quietly(awaitable: Awaitable[object], limit_seconds: float) -> None:
    with contextlib.suppress(Exception, asyncio.CancelledError):
        await asyncio.wait_for(awaitable, limit_seconds)


class SandboxPage:
    def __init__(
        self,
        sandbox: "RenderSandbox",
        context: BrowserContext,
        spec: PageSpec,
    ) -> None:
        self._sandbox = sandbox
        self._config = sandbox.config
        self._runtime = sandbox.runtime
        self._context = context
        self._spec = spec
        self._page: Page | None = None
        self._cdp: CDPSession | None = None
        self._cdp_client: CdpClient | None = None
        self._violations: list[str] = []
        self._page_violations: list[str] = []
        self._errors: list[str] = []
        self._crashed = False
        self._dead = False
        self._loads = 0
        self._clock_ms = 0
        self._tasks: set[asyncio.Task[None]] = set()
        self.composition: CompositionInfo | None = None

    @property
    def spec(self) -> PageSpec:
        return self._spec

    @property
    def violations(self) -> tuple[str, ...]:
        return tuple(unique_limited([*self._violations, *self._page_violations]))

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(unique_limited(self._errors))

    @property
    def fps(self) -> int:
        return self._spec.fps or self._config.fps

    @property
    def frame_clock_ms(self) -> int:
        return round(1000 / self.fps)

    def page(self) -> Page:
        if self._page is None:
            raise BrowserCrashError("The page has not been opened")
        return self._page

    def cdp(self) -> CdpClient:
        if self._cdp_client is None:
            raise BrowserCrashError("The page has not been opened")
        return self._cdp_client

    def record_violation(self, description: str) -> None:
        if len(self._violations) < MAX_REPORTED_ERRORS:
            self._violations.append(description)

    async def _fulfill_document(self, route: Route) -> None:
        await route.fulfill(status=200, headers=dict(DOCUMENT_HEADERS), body=self._spec.html.encode("utf-8"))

    async def handle_route(self, route: Route) -> None:
        request = route.request
        url = request.url
        try:
            if url == COMPOSITION_URL and request.method == "GET":
                await self._fulfill_document(route)
                return
            asset = self._runtime.asset_for_url(url)
            if asset is not None and request.method in {"GET", "HEAD"}:
                body = b"" if request.method == "HEAD" else asset.body
                await route.fulfill(status=200, headers=asset.headers, body=body)
                return
            if url.startswith(RUNTIME_ORIGIN) and request.method == "OPTIONS":
                await route.fulfill(status=204, headers=dict(CORS_PREFLIGHT_HEADERS))
                return
            if url == f"{RUNTIME_ORIGIN}/favicon.ico":
                await route.fulfill(status=204)
                return
            if url.startswith(f"{RUNTIME_ORIGIN}/") and request.method in {"GET", "HEAD"}:
                await route.fulfill(status=404, headers={"Content-Type": "text/plain"}, body=f"not found: {url}")
                return
            self.record_violation(f"request {request.method} {url} ({request.resource_type})")
            await route.abort("blockedbyclient")
        except PlaywrightError:
            return

    async def _handle_websocket(self, route: WebSocketRoute) -> None:
        self.record_violation(f"websocket {route.url}")
        with contextlib.suppress(PlaywrightError):
            await route.close(code=1008, reason="blocked")

    def _on_console(self, message: ConsoleMessage) -> None:
        if message.type != "error":
            return
        text = message.text
        if any(marker in text for marker in IGNORED_CONSOLE_MARKERS):
            return
        if any(marker in text for marker in POLICY_CONSOLE_MARKERS):
            self.record_violation(f"policy {text[:200]}")
            return
        location = message.location.get("url") if message.location else None
        self._errors.append(f"{text} ({location})" if location and location not in text else text)

    def record_error(self, message: str) -> None:
        self._errors.append(message)

    def mark_crashed(self) -> None:
        self._crashed = True

    def _on_page_error(self, error: Any) -> None:
        self.record_error(str(getattr(error, "message", error)).splitlines()[0])

    def _on_crash(self, _page: Page) -> None:
        self.mark_crashed()

    def _on_load(self, _page: Page) -> None:
        self._loads += 1
        if self._loads > 1:
            self.record_violation("navigation: the document reloaded")

    def _on_frame_navigated(self, frame: Frame) -> None:
        if frame.parent_frame is None and self._loads > 0 and urldefrag(frame.url).url != COMPOSITION_URL:
            self.record_violation(f"navigation to {frame.url[:200]}")

    def _on_popup(self, page: Page) -> None:
        if page is self._page:
            return
        self.record_violation(f"popup {page.url[:200]}")
        task = asyncio.ensure_future(close_quietly(page.close(run_before_unload=False), TEARDOWN_TIMEOUT_SECONDS))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _on_requested_navigation(self, event: Mapping[str, Any]) -> None:
        url = str(event.get("url", ""))
        if self._loads > 0 or urldefrag(url).url != COMPOSITION_URL:
            self.record_violation(f"navigation requested to {url[:200]}")

    def _on_scheduled_navigation(self, event: Mapping[str, Any]) -> None:
        url = str(event.get("url", ""))
        self.record_violation(f"navigation scheduled to {url[:200]}")

    def _on_worker(self, _worker: object) -> None:
        self.record_violation("worker started")

    def _on_download(self, _download: object) -> None:
        self.record_violation("download started")

    def _attach_listeners(self, page: Page, cdp: CDPSession) -> None:
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("crash", self._on_crash)
        page.on("load", self._on_load)
        page.on("framenavigated", self._on_frame_navigated)
        page.on("worker", self._on_worker)
        page.on("download", self._on_download)
        self._context.on("page", self._on_popup)
        cdp.on("Page.frameRequestedNavigation", self._on_requested_navigation)
        cdp.on("Page.frameScheduledNavigation", self._on_scheduled_navigation)

    def classify(self, error: SandboxError) -> SandboxError:
        if self._crashed:
            return BrowserCrashError("The browser page crashed or ran out of memory")
        violations = self.violations
        if violations:
            return NetworkViolationError(violations)
        return error

    def _error_from(self, error: PlaywrightError) -> SandboxError:
        message = summarize_playwright_message(error.message)
        if isinstance(error, PlaywrightTimeoutError):
            return SandboxTimeoutError(message)
        if any(marker in message.lower() for marker in CRASH_MARKERS):
            return BrowserCrashError(message)
        return PageError(unique_limited([*self._errors, message]))

    async def _guard[T](self, awaitable: Awaitable[T], *, limit_seconds: float, what: str) -> T:
        if self._dead:
            raise self.classify(BrowserCrashError("The page is no longer available"))
        try:
            return await asyncio.wait_for(awaitable, limit_seconds)
        except TimeoutError:
            await self.kill()
            raise self.classify(
                SandboxTimeoutError(f"{what} did not finish within {limit_seconds:g} seconds")
            ) from None
        except PlaywrightError as error:
            await self._refresh_violations()
            raise self.classify(self._error_from(error)) from error

    async def _refresh_violations(self) -> None:
        if self._page is None or self._dead or self._crashed:
            return
        with contextlib.suppress(Exception):
            reported = await asyncio.wait_for(
                self._page.evaluate("() => window.__motionileSandbox.violations()"),
                self._config.frame_timeout_seconds,
            )
            self._page_violations = [str(item) for item in cast("list[object]", reported)]

    def check(self) -> None:
        if self._crashed:
            raise BrowserCrashError("The browser page crashed or ran out of memory")
        violations = self.violations
        if violations:
            raise NetworkViolationError(violations)
        if self._errors:
            raise PageError(self.errors)

    async def kill(self) -> None:
        self._dead = True
        if self._page is not None:
            await close_quietly(self._page.close(run_before_unload=False), TEARDOWN_TIMEOUT_SECONDS)
        await close_quietly(self._context.close(), TEARDOWN_TIMEOUT_SECONDS)

    async def close(self) -> None:
        if self._dead:
            return
        self._dead = True
        await close_quietly(self._context.close(), self._config.shutdown_timeout_seconds)
        for task in list(self._tasks):
            task.cancel()

    async def open(self) -> None:
        spec = self._spec
        viewport = spec.aspect.spec.viewport
        context = self._context
        context.set_default_timeout(
            max(self._config.page_load_timeout_seconds, self._config.ready_timeout_seconds) * 2000
        )
        await context.route(MATCH_ALL, self.handle_route)
        await context.route_web_socket(MATCH_ALL, self._handle_websocket)
        await context.add_init_script(script=init_script_source(spec))
        await context.clock.install(time=EPOCH_MS)
        await context.clock.pause_at(CLOCK_PAUSED_AT_MS)
        page = await context.new_page()
        self._page = page
        await page.set_viewport_size({"width": viewport.width, "height": viewport.height})
        cdp = await context.new_cdp_session(page)
        self._cdp = cdp
        self._cdp_client = cast("CdpClient", cdp)
        await self.cdp().send("Page.enable")
        self._attach_listeners(page, cdp)
        await self._guard(
            page.goto(COMPOSITION_URL, wait_until="load"),
            limit_seconds=self._config.page_load_timeout_seconds,
            what="Loading the composition",
        )
        await self._drain_violations()
        self.check()
        await self.wait_ready()

    async def _drain_violations(self) -> None:
        page_violations = await self._guard(
            self.page().evaluate("() => window.__motionileSandbox.violations()"),
            limit_seconds=self._config.frame_timeout_seconds,
            what="Reading sandbox violations",
        )
        self._page_violations = [str(item) for item in cast("list[object]", page_violations)]

    async def wait_ready(self) -> CompositionInfo | None:
        has_ready = await self._guard(
            self.page().evaluate("() => window.__motionileSandbox.awaitReady()"),
            limit_seconds=self._config.ready_timeout_seconds,
            what="The composition ready signal",
        )
        await self._drain_violations()
        self.check()
        if not has_ready:
            return None
        payload = await self._guard(
            self.page().evaluate("() => window.__motionileSandbox.readComposition()"),
            limit_seconds=self._config.frame_timeout_seconds,
            what="Reading the composition",
        )
        if payload is None:
            return None
        self.composition = parse_composition_info(cast("Mapping[str, Any]", payload))
        return self.composition

    async def evaluate(self, expression: str, argument: object = None, *, what: str = "A page evaluation") -> Any:
        result = await self._guard(
            self.page().evaluate(expression, argument),
            limit_seconds=self._config.frame_timeout_seconds,
            what=what,
        )
        self.check()
        return result

    async def seek(self, time_ms: float) -> None:
        await self._guard(
            self.page().evaluate("(timeMs) => window.__motionileSandbox.seek(timeMs)", time_ms),
            limit_seconds=self._config.frame_timeout_seconds,
            what="Seeking the timeline",
        )

    async def advance_clock_to(self, target_ms: int) -> None:
        delta = target_ms - self._clock_ms
        if delta <= 0:
            return
        clock = self.page().clock
        advance = clock.run_for(delta) if delta <= CLOCK_JUMP_THRESHOLD_MS else clock.fast_forward(delta)
        await self._guard(advance, limit_seconds=self._config.frame_timeout_seconds, what="Advancing the clock")
        self._clock_ms = target_ms

    async def settle(self) -> None:
        reported = await self._guard(
            self.page().evaluate("(frames) => window.__motionileSandbox.settle(frames)", SETTLE_FRAMES),
            limit_seconds=self._config.frame_timeout_seconds,
            what="Waiting for animation frames",
        )
        self._page_violations = [str(item) for item in cast("list[object]", reported)]

    async def screenshot(self) -> bytes:
        viewport = self._spec.aspect.spec.viewport
        result = await self._guard(
            self.cdp().send(
                "Page.captureScreenshot",
                {
                    "format": "png",
                    "optimizeForSpeed": True,
                    "fromSurface": True,
                    "captureBeyondViewport": False,
                    "clip": {"x": 0, "y": 0, "width": viewport.width, "height": viewport.height, "scale": 1},
                },
            ),
            limit_seconds=self._config.frame_timeout_seconds,
            what="Capturing a screenshot",
        )
        return base64.b64decode(result["data"])

    async def settle_at(self, time_ms: float) -> None:
        await self.seek(time_ms)
        await self.advance_clock_to(self._clock_ms + self.frame_clock_ms)
        await self.settle()
        self.check()

    async def capture_at(self, time_ms: float) -> bytes:
        await self.settle_at(time_ms)
        png = await self.screenshot()
        self.check()
        return png

    async def capture_frame(self, frame_index: int) -> bytes:
        fps = self.fps
        total_ms = self._spec.narration.total_duration_ms
        await self.seek(min(frame_index * 1000 / fps, total_ms))
        await self.advance_clock_to(round(frame_index * 1000 / fps))
        await self.settle()
        png = await self.screenshot()
        self.check()
        return png


class RenderSandbox:
    def __init__(
        self,
        config: RenderEngineConfig,
        *,
        runtime: RuntimeBundle | None = None,
        process_marker: str | None = None,
    ) -> None:
        self.config = config
        self.runtime = runtime or load_runtime_bundle()
        self.process_marker = process_marker or uuid.uuid4().hex
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def start(self) -> Self:
        playwright = await async_playwright().start()
        self._playwright = playwright
        try:
            self._browser = await playwright.chromium.launch(
                headless=True,
                chromium_sandbox=True,
                args=chromium_launch_args(self.config, self.process_marker),
                timeout=LAUNCH_TIMEOUT_MS,
                handle_sigint=False,
                handle_sigterm=False,
                handle_sighup=False,
            )
        except BaseException:
            await self.close()
            raise
        return self

    async def close(self) -> None:
        browser, playwright = self._browser, self._playwright
        self._browser = None
        self._playwright = None
        if browser is not None:
            await close_quietly(browser.close(), self.config.shutdown_timeout_seconds)
        if playwright is not None:
            await close_quietly(playwright.stop(), self.config.shutdown_timeout_seconds)

    async def __aenter__(self) -> Self:
        return await self.start()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def open_page(self, spec: PageSpec) -> SandboxPage:
        if self._browser is None:
            raise BrowserCrashError("The render sandbox is not running")
        viewport = spec.aspect.spec.viewport
        try:
            context = await self._browser.new_context(
                viewport={"width": viewport.width, "height": viewport.height},
                device_scale_factor=1,
                java_script_enabled=True,
                accept_downloads=False,
                permissions=[],
                locale=spec.language,
                timezone_id="UTC",
                color_scheme="dark",
                reduced_motion="no-preference",
                forced_colors="none",
                is_mobile=False,
                has_touch=False,
                bypass_csp=False,
                offline=False,
                ignore_https_errors=False,
                user_agent=USER_AGENT,
            )
        except PlaywrightError as error:
            raise BrowserCrashError(summarize_playwright_message(error.message)) from error
        page = SandboxPage(self, context, spec)
        try:
            await page.open()
        except BaseException:
            await page.close()
            raise
        return page

    @asynccontextmanager
    async def page(self, spec: PageSpec) -> AsyncGenerator[SandboxPage]:
        sandbox_page = await self.open_page(spec)
        try:
            yield sandbox_page
        finally:
            await sandbox_page.close()
