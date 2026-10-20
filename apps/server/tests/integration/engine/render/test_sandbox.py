import asyncio
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

import pytest
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright
from tests.integration.engine.render.support import (
    TINY_COMPOSITION,
    Canary,
    leftover_processes,
    render_config,
    tiny_narration,
)

from motionile.engine.ffmpeg import FfmpegTools
from motionile.engine.render.models import (
    Aspect,
    BrowserCrashError,
    NetworkViolationError,
    PageError,
    RenderEngineConfig,
    SandboxTimeoutError,
)
from motionile.engine.render.sandbox import (
    PageSpec,
    RenderSandbox,
    chromium_launch_args,
)

pytestmark = [pytest.mark.slow, pytest.mark.asyncio(loop_scope="module")]

SHELL = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Probe</title>
    <link rel="stylesheet" href="https://runtime.motionile.local/v1/base.css" />
    <script src="https://runtime.motionile.local/v1/gsap/gsap.min.js"></script>
    <script src="https://runtime.motionile.local/v1/motionile.js"></script>
    {head}
  </head>
  <body>
    <main class="mo-stage">
      <section class="mo-scene mo-center" data-scene="one"><p class="mo-title">One</p></section>
      <section class="mo-scene mo-center" data-scene="two"><p class="mo-title">Two</p></section>
    </main>
    <script>
      {script}
      Motionile.composition({{
        aspects: ["16:9", "9:16", "1:1"],
        scenes: [{{ id: "one", build(ctx) {{}} }}, {{ id: "two", build(ctx) {{}} }}],
      }});
    </script>
  </body>
</html>
"""


def spec(html: str, aspect: Aspect = Aspect.LANDSCAPE, seed: int = 7) -> PageSpec:
    return PageSpec(html=html, narration=tiny_narration(), aspect=aspect, seed=seed)


def probe_html(script: str = "", head: str = "") -> str:
    return SHELL.format(head=head, script=script)


async def test_the_page_loads_the_runtime_and_reports_the_composition(sandbox: RenderSandbox) -> None:
    async with sandbox.page(spec(TINY_COMPOSITION)) as page:
        info = page.composition

        assert info is not None
        assert [scene.id for scene in info.scenes] == ["one", "two"]
        assert info.aspects == ("16:9", "9:16", "1:1")
        assert info.timeline_duration_ms == tiny_narration().total_duration_ms
        assert page.violations == ()
        assert page.errors == ()


@pytest.mark.parametrize("aspect", list(Aspect))
async def test_the_aspect_is_set_before_any_page_script_runs(sandbox: RenderSandbox, aspect: Aspect) -> None:
    html = probe_html(head="<script>window.earlyAspect = document.documentElement.dataset.aspect;</script>")

    async with sandbox.page(spec(html, aspect)) as page:
        early = await page.evaluate("() => window.earlyAspect")
        size = await page.evaluate("() => [innerWidth, innerHeight, devicePixelRatio]")

        assert early == aspect.value
        viewport = aspect.spec.viewport
        assert size == [viewport.width, viewport.height, 1]


async def test_every_hardening_step_took_effect(sandbox: RenderSandbox) -> None:
    async with sandbox.page(spec(probe_html())) as page:
        failures = await page.evaluate("() => window.__motionileSandbox.hardeningFailures()")

        assert failures == []


async def test_the_clock_is_frozen_and_advances_one_frame_per_capture(sandbox: RenderSandbox) -> None:
    async with sandbox.page(spec(probe_html())) as page:
        first = await page.evaluate("() => [Date.now(), performance.now()]")
        await asyncio.sleep(0.3)
        second = await page.evaluate("() => [Date.now(), performance.now()]")
        await page.capture_frame(1)
        third = await page.evaluate("() => Date.now()")

        assert first == second
        assert third - first[0] == round(1000 / sandbox.config.fps)


async def test_math_random_is_seeded_before_page_scripts(sandbox: RenderSandbox) -> None:
    html = probe_html(head="<script>window.firstRandoms = [Math.random(), Math.random()];</script>")

    async with (
        sandbox.page(spec(html, seed=5)) as first,
        sandbox.page(spec(html, seed=5)) as same,
        sandbox.page(spec(html, seed=6)) as other,
    ):
        a = await first.evaluate("() => window.firstRandoms")
        b = await same.evaluate("() => window.firstRandoms")
        c = await other.evaluate("() => window.firstRandoms")

    assert a == b
    assert a != c
    assert all(0 <= value < 1 for value in a)


async def test_the_runtime_fonts_are_loaded_before_ready(sandbox: RenderSandbox) -> None:
    async with sandbox.page(spec(probe_html())) as page:
        statuses = await page.evaluate("() => Array.from(document.fonts).map((face) => face.status)")

        assert len(statuses) == 4
        assert set(statuses) == {"loaded"}


async def test_the_page_is_isolated_from_storage_and_the_network_apis(sandbox: RenderSandbox) -> None:
    async with sandbox.page(spec(probe_html())) as page:
        types = await page.evaluate(
            "() => [typeof fetch, typeof XMLHttpRequest, typeof WebSocket, typeof Worker, typeof RTCPeerConnection]"
        )

        assert types == ["function", "function", "function", "function", "function"]
        with pytest.raises(NetworkViolationError):
            await page.evaluate("() => fetch('https://example.com/')")


async def test_a_console_error_fails_with_page_error(sandbox: RenderSandbox) -> None:
    html = probe_html(script='console.error("something is wrong");')

    with pytest.raises(PageError, match="something is wrong"):
        await sandbox.open_page(spec(html))


async def test_an_uncaught_exception_fails_with_page_error(sandbox: RenderSandbox) -> None:
    html = probe_html(script='throw new Error("kaboom");')

    with pytest.raises(PageError, match="kaboom"):
        await sandbox.open_page(spec(html))


async def test_a_rejected_ready_promise_fails_with_the_builder_message(sandbox: RenderSandbox) -> None:
    html = probe_html().replace("build(ctx) {}", 'build(ctx) { ctx.at("missing-word"); }', 1)

    with pytest.raises(PageError, match="missing-word"):
        await sandbox.open_page(spec(html))


async def test_a_missing_runtime_file_fails_with_page_error(sandbox: RenderSandbox) -> None:
    html = probe_html(head='<script src="https://runtime.motionile.local/v1/gsap/Missing.min.js"></script>')

    with pytest.raises(PageError, match=r"Missing\.min\.js"):
        await sandbox.open_page(spec(html))


async def test_calling_the_composition_twice_throws(sandbox: RenderSandbox) -> None:
    html = probe_html().replace(
        "</script>\n  </body>", 'Motionile.composition({aspects: ["16:9"], scenes: []});</script>\n  </body>'
    )

    with pytest.raises(PageError, match="only be called once"):
        await sandbox.open_page(spec(html))


async def test_a_page_without_a_composition_opens_with_no_composition(sandbox: RenderSandbox) -> None:
    html = "<!doctype html><html><head><title>x</title></head><body><p>plain</p></body></html>"

    async with sandbox.page(spec(html)) as page:
        assert page.composition is None


async def test_each_page_gets_a_fresh_context(sandbox: RenderSandbox) -> None:
    html = probe_html()

    async with sandbox.page(spec(html)) as first:
        await first.evaluate("() => { window.leftover = 1; }")
        async with sandbox.page(spec(html)) as second:
            assert await second.evaluate("() => typeof window.leftover") == "undefined"


async def test_a_frozen_page_is_killed_within_the_timeout(tools: FfmpegTools, tmp_path: Path) -> None:
    config = render_config(
        tools, tmp_path, page_load_timeout_seconds=3, ready_timeout_seconds=3, frame_timeout_seconds=3
    )
    html = probe_html(script="while (true) {}")
    loop = asyncio.get_running_loop()

    async with RenderSandbox(config) as isolated:
        started = loop.time()
        with pytest.raises(SandboxTimeoutError):
            await isolated.open_page(spec(html))
        elapsed = loop.time() - started

    assert elapsed < 20
    assert await leftover_processes(isolated.process_marker) == []


async def test_a_frame_evaluation_that_hangs_times_out(tools: FfmpegTools, tmp_path: Path) -> None:
    config = render_config(tools, tmp_path, frame_timeout_seconds=2)

    async with RenderSandbox(config) as isolated, isolated.page(spec(probe_html())) as page:
        with pytest.raises(SandboxTimeoutError):
            await page.evaluate("() => { while (true) {} }")


async def test_browser_flags_alone_keep_a_loopback_server_unreachable(
    tools: FfmpegTools, config: RenderEngineConfig, canary: Canary
) -> None:
    arguments = chromium_launch_args(replace(config, tools=tools), "flags-only")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, chromium_sandbox=True, args=arguments)
        try:
            page = await browser.new_page()
            with pytest.raises(PlaywrightError, match="net::ERR"):
                await page.goto(f"http://{canary.authority}/direct", timeout=15_000)
            blank = await browser.new_page()
            await blank.goto("about:blank")
            result = await blank.evaluate(
                "async (url) => { try { await fetch(url); return 'reached'; } catch (error) { return 'blocked'; } }",
                f"http://{canary.authority}/fetch",
            )
        finally:
            await browser.close()

    assert result == "blocked"
    assert canary.hits == []


async def test_a_crashed_renderer_fails_with_browser_crash(sandbox: RenderSandbox) -> None:
    async with sandbox.page(spec(probe_html())) as page:
        with suppress(PlaywrightError, TimeoutError):
            await asyncio.wait_for(page.cdp().send("Page.crash"), 5)
        with pytest.raises(BrowserCrashError):
            await page.evaluate("() => 1")
