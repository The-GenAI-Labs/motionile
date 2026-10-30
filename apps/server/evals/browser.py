import asyncio
import io
import tempfile
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Final, Protocol

from PIL import Image, ImageOps

from evals.errors import BrowserUnavailableError
from evals.harness import frame_times
from motionile.core.config import Settings
from motionile.engine.ai.ports import CompositionCheck, CompositionIssue, SampledFrame
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.render.models import Aspect, SandboxError, ValidationIssue, issue_from_error
from motionile.engine.render.sanitize import sanitize_composition

if TYPE_CHECKING:
    from motionile.engine.render.models import RenderEngineConfig
    from motionile.engine.render.sandbox import RenderSandbox

SEED: Final = 20261024
MAX_FRAME_WIDTH: Final = 768
SELECTOR_KEY: Final = "selector"
ENGINE_FPS: Final = 15
LOAD_TIMEOUT_SECONDS: Final = 60.0
FRAME_TIMEOUT_SECONDS: Final = 30.0


class BrowserProvider(Protocol):
    def sandbox(self) -> AbstractAsyncContextManager["RenderSandbox"]: ...


def explicit_browser_environment(settings: Settings) -> dict[str, str]:
    process = settings.process_environment
    allowed = {
        "PATH": process.path,
        "HOME": process.home,
        "SYSTEMROOT": process.system_root,
        "TEMP": process.temp,
        "TMP": process.tmp,
        "TMPDIR": process.tmpdir,
    }
    return {name: value for name, value in allowed.items() if value}


def engine_config(directory: Path, environment: Mapping[str, str]) -> "RenderEngineConfig":
    from motionile.engine.render.models import RenderEngineConfig  # noqa: PLC0415

    return RenderEngineConfig(
        fps=ENGINE_FPS,
        parallel_pages=1,
        page_load_timeout_seconds=LOAD_TIMEOUT_SECONDS,
        ready_timeout_seconds=LOAD_TIMEOUT_SECONDS,
        frame_timeout_seconds=FRAME_TIMEOUT_SECONDS,
        work_directory=directory,
        browser_environment=environment,
    )


class LocalBrowser:
    def __init__(self, environment: Mapping[str, str] | None = None) -> None:
        self._environment = dict(environment or {})

    @asynccontextmanager
    async def sandbox(self) -> AsyncGenerator["RenderSandbox"]:
        try:
            from playwright.async_api import Error as PlaywrightError  # noqa: PLC0415

            from motionile.engine.render.sandbox import RenderSandbox  # noqa: PLC0415
        except ImportError as error:
            raise BrowserUnavailableError("Playwright is not installed in this image") from error

        with tempfile.TemporaryDirectory(prefix="motionile-evals-") as directory:
            config = engine_config(Path(directory), self._environment)
            started = RenderSandbox(config)
            try:
                await started.start()
            except PlaywrightError as error:
                reason = error.message.splitlines()[0] if error.message else "launch failed"
                raise BrowserUnavailableError(f"Chromium is not available: {reason}") from error
            try:
                yield started
            finally:
                await started.close()


def issue_of(issue: ValidationIssue) -> CompositionIssue:
    detail = dict(issue.detail)
    if issue.selector is not None:
        detail[SELECTOR_KEY] = issue.selector
    return CompositionIssue(
        code=issue.code,
        severity=issue.severity,
        kind=issue.kind,
        message=issue.message,
        scene_id=issue.scene,
        aspect=issue.aspect,
        time_ms=issue.time_ms,
        detail=detail,
    )


def downscale_png(png: bytes, max_width: int = MAX_FRAME_WIDTH) -> bytes:
    with Image.open(io.BytesIO(png)) as opened:
        if opened.width <= max_width:
            return png
        height = max(1, round(opened.height * max_width / opened.width))
        resized = ImageOps.fit(opened.convert("RGB"), (max_width, height), method=Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


class SandboxChecker:
    def __init__(self, sandbox: "RenderSandbox") -> None:
        self._sandbox = sandbox

    async def check(self, html: str, narration: NarrationDocument, aspects: Sequence[str]) -> CompositionCheck:
        from motionile.engine.render.validate import validate_composition  # noqa: PLC0415

        sanitized = await asyncio.to_thread(
            sanitize_composition, html, scene_ids=[scene.id for scene in narration.scenes]
        )
        issues = [issue_of(finding) for finding in sanitized.findings]
        if not sanitized.errors:
            try:
                report = await validate_composition(
                    self._sandbox, sanitized.html, narration, [Aspect(aspect) for aspect in aspects], seed=SEED
                )
            except SandboxError as error:
                issues.append(issue_of(issue_from_error(error)))
            else:
                issues.extend(issue_of(issue) for issue in report.issues)
        return CompositionCheck(valid=not any(issue.is_blocking for issue in issues), issues=tuple(issues))

    async def sample_frames(
        self, html: str, narration: NarrationDocument, aspects: Sequence[str]
    ) -> list[SampledFrame]:
        from motionile.engine.render.sandbox import PageSpec  # noqa: PLC0415

        sanitized = await asyncio.to_thread(
            sanitize_composition, html, scene_ids=[scene.id for scene in narration.scenes]
        )
        frames: list[SampledFrame] = []
        for aspect in aspects:
            spec = PageSpec(html=sanitized.html, narration=narration, aspect=Aspect(aspect), seed=SEED)
            async with self._sandbox.page(spec) as page:
                for scene_id, time_ms in frame_times(narration):
                    png = await page.capture_at(time_ms)
                    frames.append(
                        SampledFrame(
                            scene_id=scene_id,
                            aspect=aspect,
                            time_ms=time_ms,
                            png=await asyncio.to_thread(downscale_png, png),
                        )
                    )
        return frames
