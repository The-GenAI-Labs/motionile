import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from tests.integration.engine.render.support import (
    MALICIOUS_ROOT,
    Canary,
    leftover_processes,
    render_config,
    tiny_narration,
)

from motionile.engine.ffmpeg import FfmpegTools
from motionile.engine.render.models import Aspect, SandboxError
from motionile.engine.render.sandbox import PageSpec, RenderSandbox
from motionile.engine.render.sanitize import sanitize_composition

pytestmark = [pytest.mark.slow, pytest.mark.asyncio(loop_scope="module")]

NETWORK = "network_violation"
INVALID = "invalid_composition"
MEMORY_LIMIT = "memory_limit"
ACCEPTED_CODES = {MEMORY_LIMIT: {"browser_crash", "timeout"}}
OVERSIZED_PAYLOAD_BYTES = 2_600_000
HANG_BUDGET_SECONDS = 25


@dataclass(frozen=True)
class Expectation:
    sanitized: str
    raw: str


def same(code: str) -> Expectation:
    return Expectation(sanitized=code, raw=code)


def stripped(raw: str = NETWORK) -> Expectation:
    return Expectation(sanitized=INVALID, raw=raw)


EXPECTATIONS: dict[str, Expectation] = {
    "exfil_fetch": same(NETWORK),
    "exfil_xhr": same(NETWORK),
    "exfil_websocket": same(NETWORK),
    "exfil_beacon": same(NETWORK),
    "exfil_event_source": same(NETWORK),
    "exfil_image_constructor": same(NETWORK),
    "external_image": stripped(),
    "external_font": stripped(),
    "external_css": stripped(),
    "css_import": stripped(),
    "css_background": stripped(),
    "inline_style_url": stripped(),
    "iframe_embed": stripped(),
    "object_embed": stripped(),
    "meta_refresh": stripped(),
    "window_open": same(NETWORK),
    "location_navigation": same(NETWORK),
    "link_click": stripped(),
    "form_submit": stripped(),
    "service_worker": same(NETWORK),
    "webrtc": same(NETWORK),
    "web_worker_blob": same(NETWORK),
    "local_storage": same(NETWORK),
    "eval_fetch": same(NETWORK),
    "dynamic_import": same(NETWORK),
    "file_image": stripped(),
    "file_fetch": same(NETWORK),
    "file_iframe": stripped(),
    "metadata_image": stripped(),
    "metadata_fetch": same(NETWORK),
    "metadata_xhr": same(NETWORK),
    "metadata_css": stripped(),
    "metadata_iframe": stripped(),
    "metadata_websocket": same(NETWORK),
    "infinite_loop": same("timeout"),
    "dom_bomb": same("timeout"),
    "memory_bomb": same(MEMORY_LIMIT),
    "oversized_data_uri": stripped("page_error"),
    "uncaught_error": same("page_error"),
}
METADATA_ADDRESS = "169.254.169.254"


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def hostile_sandbox(tools: FfmpegTools, tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[RenderSandbox]:
    config = render_config(
        tools,
        tmp_path_factory.mktemp("hostile"),
        page_load_timeout_seconds=4,
        ready_timeout_seconds=4,
        frame_timeout_seconds=4,
        browser_memory_mb=256,
        shutdown_timeout_seconds=10,
    )
    async with RenderSandbox(config) as started:
        yield started
    assert await leftover_processes(started.process_marker) == []


def load_fixture(name: str, canary: Canary) -> str:
    html = canary.fill((MALICIOUS_ROOT / f"{name}.html").read_text(encoding="utf-8"))
    return html.replace("__OVERSIZED__", "A" * OVERSIZED_PAYLOAD_BYTES)


def hostile_spec(html: str) -> PageSpec:
    narration = tiny_narration()
    single = narration.model_copy(
        update={"scenes": narration.scenes[:1], "total_duration_ms": narration.scenes[0].duration_ms}
    )
    return PageSpec(html=html, narration=single, aspect=Aspect.LANDSCAPE, seed=1)


def accepted(code: str) -> set[str]:
    return ACCEPTED_CODES.get(code, {code})


async def attempt(sandbox: RenderSandbox, html: str) -> str:
    try:
        async with sandbox.page(hostile_spec(html)) as page:
            await page.capture_frame(0)
    except SandboxError as error:
        return error.code
    return "completed"


@pytest.mark.parametrize("name", sorted(EXPECTATIONS))
async def test_the_sanitizer_and_the_sandbox_stop_the_attack_with_zero_outbound_requests(
    hostile_sandbox: RenderSandbox, canary: Canary, name: str
) -> None:
    expected = EXPECTATIONS[name].sanitized
    html = load_fixture(name, canary)
    sanitized = sanitize_composition(html)

    if expected == INVALID:
        assert sanitized.errors, "the sanitizer should reject this composition"
        assert canary.hits == []
        return
    assert sanitized.errors == ()
    assert await attempt(hostile_sandbox, sanitized.html) in accepted(expected)
    assert canary.hits == []


@pytest.mark.parametrize("name", sorted(EXPECTATIONS))
async def test_the_sandbox_alone_stops_the_raw_composition_with_zero_outbound_requests(
    hostile_sandbox: RenderSandbox, canary: Canary, name: str
) -> None:
    html = load_fixture(name, canary)
    loop_started = time.monotonic()

    outcome = await attempt(hostile_sandbox, html)

    assert outcome in accepted(EXPECTATIONS[name].raw)
    assert time.monotonic() - loop_started < HANG_BUDGET_SECONDS
    assert canary.hits == []


@pytest.mark.parametrize(
    "name", [name for name in EXPECTATIONS if name.startswith("metadata_") and name != "metadata_xhr"]
)
async def test_metadata_address_attempts_are_named_in_the_violation(
    hostile_sandbox: RenderSandbox, canary: Canary, name: str
) -> None:
    html = load_fixture(name, canary)

    with pytest.raises(SandboxError, match=METADATA_ADDRESS):
        async with hostile_sandbox.page(hostile_spec(html)) as page:
            await page.capture_frame(0)


async def test_the_runtime_origin_stays_reachable_after_every_attack(hostile_sandbox: RenderSandbox) -> None:
    clean = (
        (MALICIOUS_ROOT / "uncaught_error.html")
        .read_text(encoding="utf-8")
        .replace('throw new Error("composition exploded");', "")
    )

    assert await attempt(hostile_sandbox, clean) == "completed"
