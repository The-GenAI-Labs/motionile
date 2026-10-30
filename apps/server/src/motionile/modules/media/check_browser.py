import asyncio
import io
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from typing import Final

from PIL import Image, ImageOps

from motionile.core.config import Settings
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.render.models import Aspect, ValidationReport
from motionile.engine.render.sandbox import PageSpec, RenderSandbox
from motionile.engine.render.validate import validate_composition
from motionile.modules.media.composition_check import (
    MAX_FRAME_WIDTH,
    BrowserOpenerFactory,
    CapturedFrame,
    CheckBrowser,
    FrameSample,
)
from motionile.modules.media.pipeline.toolchain import engine_config

PNG_FORMAT: Final = "PNG"


def downscale_png(png: bytes, max_width: int = MAX_FRAME_WIDTH) -> bytes:
    with Image.open(io.BytesIO(png)) as opened:
        if opened.width <= max_width:
            return png
        height = max(1, round(opened.height * max_width / opened.width))
        resized = ImageOps.fit(opened.convert("RGB"), (max_width, height), method=Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, format=PNG_FORMAT, optimize=True)
    return buffer.getvalue()


class EngineCheckBrowser:
    def __init__(self, sandbox: RenderSandbox) -> None:
        self._sandbox = sandbox

    async def validate(
        self, html: str, narration: NarrationDocument, aspects: Sequence[Aspect], seed: int
    ) -> ValidationReport:
        return await validate_composition(self._sandbox, html, narration, aspects, seed=seed)

    async def capture(
        self, html: str, narration: NarrationDocument, aspect: Aspect, seed: int, samples: Sequence[FrameSample]
    ) -> list[CapturedFrame]:
        frames: list[CapturedFrame] = []
        async with self._sandbox.page(PageSpec(html=html, narration=narration, aspect=aspect, seed=seed)) as page:
            for sample in samples:
                png = await page.capture_at(sample.time_ms)
                scaled = await asyncio.to_thread(downscale_png, png)
                frames.append(CapturedFrame(sample.scene_id, aspect, sample.time_ms, scaled))
        return frames


def check_browser_opener(settings: Settings) -> BrowserOpenerFactory:
    @asynccontextmanager
    async def open_browser() -> AsyncGenerator[CheckBrowser]:
        config = engine_config(settings, settings.render.fps)
        async with RenderSandbox(config) as sandbox:
            yield EngineCheckBrowser(sandbox)

    return open_browser
