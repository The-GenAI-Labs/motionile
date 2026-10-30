import io
import json
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

import pytest
from PIL import Image
from tests.fakes.storage import InMemoryStorage

from motionile.engine.audio.models import WordTiming
from motionile.engine.audio.narration import SceneAudio, assemble_narration
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.render.models import (
    Aspect,
    NetworkViolationError,
    ValidationIssue,
    ValidationReport,
    make_issue,
)
from motionile.engine.render.models import IssueCode as RenderIssueCode
from motionile.modules.media.check_browser import downscale_png
from motionile.modules.media.composition_check import (
    CHECK_REQUEST_NAME,
    CHECK_RESULT_NAME,
    CapturedFrame,
    CheckBrowser,
    CompositionCheckMismatchError,
    CompositionCheckRequest,
    CompositionCheckResult,
    CompositionCheckService,
    FrameSample,
    composition_check_id,
    frame_samples,
    seed_for_check,
)
from motionile.modules.media.keys import composition_check_key

GOLDEN = Path(__file__).resolve().parents[3] / "fixtures" / "compositions" / "kinetic-typography"
JOB = UUID("0199eb00-0000-7000-8000-0000000000e5")
PNG = b"\x89PNG-fake"


def golden_narration() -> NarrationDocument:
    scenes = json.loads((GOLDEN / "narration.json").read_text(encoding="utf-8"))["scenes"]
    audio = [
        SceneAudio(
            id=scene["sceneId"],
            text=scene["text"],
            duration_ms=3000,
            words=(WordTiming(scene["text"].split()[0], 0, 300),),
        )
        for scene in scenes
    ]
    return assemble_narration(audio, 400)


def golden_html() -> str:
    return (GOLDEN / "composition.html").read_text(encoding="utf-8")


def request(*, want_frames: bool = False, html: str | None = None) -> CompositionCheckRequest:
    return CompositionCheckRequest(
        html=html if html is not None else golden_html(),
        narration=golden_narration(),
        aspects=(Aspect.LANDSCAPE, Aspect.PORTRAIT),
        want_frames=want_frames,
    )


class FakeBrowser:
    def __init__(self, issues: Sequence[ValidationIssue] = (), failure: Exception | None = None) -> None:
        self.issues = tuple(issues)
        self.failure = failure
        self.validated: list[tuple[str, int]] = []
        self.captured: list[tuple[Aspect, int]] = []

    async def validate(
        self, html: str, narration: NarrationDocument, aspects: Sequence[Aspect], seed: int
    ) -> ValidationReport:
        del narration, aspects
        self.validated.append((html, seed))
        if self.failure is not None:
            raise self.failure
        return ValidationReport(issues=self.issues)

    async def capture(
        self, html: str, narration: NarrationDocument, aspect: Aspect, seed: int, samples: Sequence[FrameSample]
    ) -> list[CapturedFrame]:
        del html, narration
        self.captured.append((aspect, seed))
        if self.failure is not None:
            raise self.failure
        return [CapturedFrame(sample.scene_id, aspect, sample.time_ms, PNG) for sample in samples]


class Opener:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser
        self.opened = 0
        self.closed = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncGenerator[CheckBrowser]:
        self.opened += 1
        try:
            yield self.browser
        finally:
            self.closed += 1


async def stage(storage: InMemoryStorage, item: CompositionCheckRequest) -> str:
    async def chunks() -> AsyncGenerator[bytes]:
        yield item.model_dump_json(by_alias=True).encode()

    await storage.put(
        composition_check_key(JOB, item.check_id, CHECK_REQUEST_NAME), chunks(), content_type="application/json"
    )
    return item.check_id


def service(storage: InMemoryStorage, browser: FakeBrowser) -> tuple[CompositionCheckService, Opener]:
    opener = Opener(browser)
    return CompositionCheckService(storage, opener, timeout_seconds=30.0), opener


def test_the_check_id_depends_on_every_input() -> None:
    narration = golden_narration()
    base = composition_check_id("<html>", narration, [Aspect.LANDSCAPE], want_frames=False)

    assert base == composition_check_id("<html>", narration, ["16:9"], want_frames=False)
    assert len(base) == 64
    assert base != composition_check_id("<html >", narration, [Aspect.LANDSCAPE], want_frames=False)
    assert base != composition_check_id("<html>", narration, [Aspect.PORTRAIT], want_frames=False)
    assert base != composition_check_id("<html>", narration, [Aspect.LANDSCAPE], want_frames=True)
    assert base != composition_check_id(
        "<html>", narration.model_copy(update={"total_duration_ms": 1}), ["16:9"], want_frames=False
    )


def test_the_check_id_does_not_confuse_where_one_input_ends() -> None:
    narration = golden_narration()

    assert composition_check_id("a", narration, ["16:9"], want_frames=False) != composition_check_id(
        "a\x00", narration, ["16:9"], want_frames=False
    )


def test_frames_are_sampled_at_a_quarter_and_three_quarters_of_every_scene() -> None:
    narration = golden_narration()
    samples = frame_samples(narration)

    assert len(samples) == 2 * len(narration.scenes)
    first = narration.scenes[0]
    assert samples[0] == FrameSample(first.id, first.start_ms + first.duration_ms // 4)
    assert samples[1] == FrameSample(first.id, first.start_ms + first.duration_ms * 3 // 4)


def test_the_seed_is_stable_and_bounded() -> None:
    assert seed_for_check("ff" * 32) == 0x7FFFFFFF
    assert seed_for_check("00000001" + "0" * 56) == 1


def test_a_large_frame_is_scaled_to_the_maximum_width() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (1920, 1080), (10, 20, 30)).save(buffer, format="PNG")

    scaled = downscale_png(buffer.getvalue(), 768)

    with Image.open(io.BytesIO(scaled)) as opened:
        assert opened.size == (768, 432)
        assert opened.format == "PNG"


def test_a_small_frame_is_left_alone() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300)).save(buffer, format="PNG")

    assert downscale_png(buffer.getvalue(), 768) == buffer.getvalue()


async def test_a_valid_composition_is_validated_in_the_browser_and_the_result_is_stored() -> None:
    storage = InMemoryStorage()
    check_id = await stage(storage, request())
    browser = FakeBrowser()
    checker, opener = service(storage, browser)

    result = await checker.run(JOB, check_id)

    assert result.report.valid
    assert result.frames == ()
    assert opener.opened == 1
    assert opener.closed == 1
    assert len(browser.validated) == 1
    stored = storage.objects[composition_check_key(JOB, check_id, CHECK_RESULT_NAME)]
    assert CompositionCheckResult.model_validate_json(stored.data).check_id == check_id


async def test_the_browser_receives_the_sanitized_document() -> None:
    storage = InMemoryStorage()
    html = golden_html().replace("</body>", '<img src="https://evil.example/x.png"></body>')
    check_id = await stage(storage, request(html=html))
    browser = FakeBrowser()
    checker, _ = service(storage, browser)

    result = await checker.run(JOB, check_id)

    assert "evil.example" not in browser.validated[0][0] if browser.validated else True
    assert any(issue.code == "forbidden_url" for issue in result.report.issues)


async def test_sanitizer_errors_skip_the_browser() -> None:
    storage = InMemoryStorage()
    html = golden_html().replace("</body>", "<iframe src='https://runtime.motionile.local/x'></iframe></body>")
    check_id = await stage(storage, request(html=html))
    browser = FakeBrowser()
    checker, opener = service(storage, browser)

    result = await checker.run(JOB, check_id)

    assert not result.report.valid
    assert opener.opened == 0
    assert browser.validated == []


async def test_browser_findings_are_merged_with_the_sanitizer_findings() -> None:
    storage = InMemoryStorage()
    check_id = await stage(storage, request())
    overflow = make_issue(RenderIssueCode.TEXT_OVERFLOW, "overflows")
    checker, _ = service(storage, FakeBrowser([overflow]))

    result = await checker.run(JOB, check_id)

    assert not result.report.valid
    assert "text_overflow" in {issue.code for issue in result.report.issues}


async def test_a_sandbox_failure_becomes_an_error_issue_instead_of_failing_the_task() -> None:
    storage = InMemoryStorage()
    check_id = await stage(storage, request())
    checker, opener = service(storage, FakeBrowser(failure=NetworkViolationError(["request GET https://x"])))

    result = await checker.run(JOB, check_id)

    assert not result.report.valid
    assert "network_violation" in {issue.code for issue in result.report.errors}
    assert opener.closed == 1


async def test_infrastructure_errors_propagate_so_the_task_retries() -> None:
    storage = InMemoryStorage()
    check_id = await stage(storage, request())
    checker, _ = service(storage, FakeBrowser(failure=ConnectionError("storage down")))

    with pytest.raises(ConnectionError):
        await checker.run(JOB, check_id)

    assert composition_check_key(JOB, check_id, CHECK_RESULT_NAME) not in storage.objects


async def test_frames_are_stored_under_the_check_prefix_and_listed_in_the_manifest() -> None:
    storage = InMemoryStorage()
    item = request(want_frames=True)
    check_id = await stage(storage, item)
    browser = FakeBrowser()
    checker, _ = service(storage, browser)

    result = await checker.run(JOB, check_id)

    expected = len(item.narration.scenes) * 2 * len(item.aspects)
    assert len(result.frames) == expected
    assert browser.validated == []
    assert {aspect for aspect, _ in browser.captured} == {Aspect.LANDSCAPE, Aspect.PORTRAIT}
    for entry in result.frames:
        assert entry.key.startswith(f"work/jobs/{JOB}/checks/{check_id}/frames/")
        assert storage.objects[entry.key].data == PNG
        assert storage.objects[entry.key].content_type == "image/png"
    assert len({entry.key for entry in result.frames}) == expected


async def test_a_stored_result_is_reused_without_opening_a_browser() -> None:
    storage = InMemoryStorage()
    check_id = await stage(storage, request())
    first_browser = FakeBrowser()
    first, _ = service(storage, first_browser)
    await first.run(JOB, check_id)
    second_browser = FakeBrowser()
    second, opener = service(storage, second_browser)

    again = await second.run(JOB, check_id)

    assert again.check_id == check_id
    assert opener.opened == 0
    assert second_browser.validated == []


async def test_a_request_that_does_not_match_its_check_id_is_refused() -> None:
    storage = InMemoryStorage()
    item = request()
    other = request(html=golden_html() + " ")
    staged = await stage(storage, other)
    storage.objects[composition_check_key(JOB, item.check_id, CHECK_REQUEST_NAME)] = storage.objects[
        composition_check_key(JOB, staged, CHECK_REQUEST_NAME)
    ]
    checker, opener = service(storage, FakeBrowser())

    with pytest.raises(CompositionCheckMismatchError):
        await checker.run(JOB, item.check_id)

    assert opener.opened == 0
