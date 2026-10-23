import hashlib
from collections.abc import AsyncGenerator, AsyncIterable, Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from tests.fakes.media import EPOCH, World
from tests.fakes.storage import InMemoryStorage

from motionile.core.ids import new_id
from motionile.core.storage.base import ObjectInfo
from motionile.engine.audio.mix import MixPlan
from motionile.engine.audio.models import SynthesisOptions, VoiceRef
from motionile.engine.audio.narration import NormalizedAudio
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.audio.providers.fake import FakeTTSProvider
from motionile.engine.audio.synthesis import NarratedAudio
from motionile.engine.audio.wav import parse_wav
from motionile.engine.render.models import Aspect, CaptureCancelledError, RenderEngineConfig, ValidationReport
from motionile.engine.render.thumbnails import PosterFiles
from motionile.modules.media.domain import TERMINAL_RENDER_STATUSES, RenderStage, RenderStatus
from motionile.modules.media.models import Render, Rendition
from motionile.modules.media.pipeline.ports import (
    AssembleJob,
    BrowserValidation,
    CaptureJob,
    PosterJob,
    RenderBrowser,
    SegmentPlan,
)
from motionile.modules.media.render_repository import Advance, CancelOutcome, Finish, NewRender, NewRendition

ACTIVE = {status.value for status in RenderStatus} - {status.value for status in TERMINAL_RENDER_STATUSES}
STAGES = {stage.value for stage in RenderStage}


def write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def read_file(path: Path) -> bytes:
    return path.read_bytes()


def make_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


class InMemoryRenderJobStore:
    def __init__(self, world: World) -> None:
        self._world = world

    async def insert(self, row: NewRender) -> Render:
        render = Render(
            id=row.id,
            owner_user_id=row.owner_user_id,
            source=row.source,
            status="queued",
            stage=None,
            progress=0,
            options=dict(row.options),
            composition_asset_id=row.composition_asset_id,
            mixed_audio_asset_id=None,
            subtitles_vtt_asset_id=None,
            subtitles_srt_asset_id=None,
            duration_ms=None,
            validation_report=None,
            stage_timings={},
            checkpoints=dict(row.checkpoints),
            error_code=None,
            error_message=None,
            cancel_requested_at=None,
            started_at=None,
            completed_at=None,
            created_at=EPOCH,
            updated_at=EPOCH,
        )
        self._world.renders[render.id] = render
        return render

    async def get_unscoped(self, render_id: UUID) -> Render | None:
        return self._world.renders.get(render_id)

    async def advance(self, render_id: UUID, change: Advance) -> Render | None:
        render = self._world.renders.get(render_id)
        if render is None or render.status != change.expected.value:
            return None
        render.status = change.target.value
        render.progress = change.progress
        render.checkpoints = {**render.checkpoints, **change.checkpoint}
        render.stage_timings = {**render.stage_timings, **change.timings}
        if change.stage is not None:
            render.stage = change.stage.value
        for name, value in change.columns.items():
            setattr(render, name, value)
        render.updated_at = datetime.now(UTC)
        return render

    async def finish(self, render_id: UUID, finish: Finish) -> Render | None:
        render = self._world.renders.get(render_id)
        if render is None or render.status not in ACTIVE:
            return None
        if finish.stalled_before is not None and render.updated_at >= finish.stalled_before:
            return None
        render.status = finish.target.value
        render.completed_at = finish.at
        render.error_code = finish.error_code
        render.error_message = finish.error_message
        render.stage_timings = {**render.stage_timings, **finish.timings}
        if finish.validation_report is not None:
            render.validation_report = dict(finish.validation_report)
        return render

    async def touch(self, render_id: UUID, *, progress: int | None = None, stage: RenderStage | None = None) -> bool:
        render = self._world.renders.get(render_id)
        if render is None or render.status not in STAGES:
            return False
        if progress is not None:
            render.progress = max(render.progress, progress)
        if stage is not None:
            render.stage = stage.value
        render.updated_at = datetime.now(UTC)
        return True

    async def request_cancel(self, owner_user_id: UUID, render_id: UUID, now: datetime) -> CancelOutcome | None:
        render = self._world.renders.get(render_id)
        if render is None or render.owner_user_id != owner_user_id:
            return None
        if render.status not in ACTIVE:
            return CancelOutcome(render, cancelled_now=False)
        render.cancel_requested_at = render.cancel_requested_at or now
        if render.status == "queued":
            render.status = "cancelled"
            render.completed_at = now
            return CancelOutcome(render, cancelled_now=True)
        return CancelOutcome(render, cancelled_now=False)

    async def set_validation_report(self, render_id: UUID, report: Mapping[str, Any]) -> None:
        self._world.renders[render_id].validation_report = dict(report)

    async def stalled(self, before: datetime, limit: int) -> list[UUID]:
        found = [r for r in self._world.renders.values() if r.status in ACTIVE and r.updated_at < before]
        return [render.id for render in sorted(found, key=lambda item: item.updated_at)[:limit]]

    async def add_rendition(self, row: NewRendition) -> Rendition:
        rendition = Rendition(
            id=new_id(),
            render_id=row.render_id,
            aspect=row.aspect,
            width=row.width,
            height=row.height,
            asset_id=row.asset_id,
            poster_webp_asset_id=row.poster_webp_asset_id,
            poster_jpeg_asset_id=row.poster_jpeg_asset_id,
            status="ready",
            duration_ms=row.duration_ms,
            burned_in_subtitles=row.burned_in_subtitles,
            created_at=EPOCH,
            updated_at=EPOCH,
        )
        self._world.renditions[rendition.id] = rendition
        return rendition


class FlakyStorage(InMemoryStorage):
    def __init__(self) -> None:
        super().__init__()
        self.fail_on: str | None = None
        self.fail_after = 0
        self.puts: list[str] = []

    async def put(
        self,
        key: str,
        chunks: AsyncIterable[bytes],
        *,
        content_type: str,
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectInfo:
        if self.fail_on is not None and self.fail_on in key:
            if self.fail_after <= 0:
                raise ConnectionError("injected storage failure")
            self.fail_after -= 1
        self.puts.append(key)
        return await super().put(key, chunks, content_type=content_type, metadata=metadata)


class FakeSpeech:
    def __init__(self) -> None:
        self.provider = FakeTTSProvider()
        self.calls: list[str] = []
        self.cache: dict[tuple[str, str], NarratedAudio] = {}

    def default_options(self, provider: str, language: str) -> SynthesisOptions:
        del provider
        return SynthesisOptions(language=language, output_format="wav")

    async def synthesize_text(
        self, voice: VoiceRef, text: str, options: SynthesisOptions, *, user_id: UUID, job_id: UUID | None = None
    ) -> NarratedAudio:
        del user_id, job_id
        self.calls.append(text)
        result = await self.provider.synthesize(text, voice, options)
        return NarratedAudio(
            cache_key=hashlib.sha256(text.encode()).digest(),
            provider="fake",
            model=result.model,
            audio=result.audio,
            content_type=result.content_type,
            duration_ms=result.duration_ms,
            words=result.words,
            characters=result.characters,
            cache_hit=False,
        )


@dataclass
class FakeBrowser:
    toolchain: "FakeToolchain"

    async def validate(self, job: BrowserValidation) -> ValidationReport:
        del job
        self.toolchain.validations += 1
        if self.toolchain.validation_failure is not None:
            raise self.toolchain.validation_failure
        return self.toolchain.report

    async def capture(self, job: CaptureJob) -> None:
        plan = self.toolchain.plan_segments(job.narration, job.aspect, job.segment_directory)
        total = len(plan.segments)
        for index, path in enumerate(plan.segments):
            if index in job.completed_chunks:
                continue
            if job.should_cancel is not None and await job.should_cancel():
                raise CaptureCancelledError("cancelled")
            if self.toolchain.capture_failure_at == (job.aspect, index):
                raise self.toolchain.capture_failure
            write_file(path, f"segment-{job.aspect.label}-{index}".encode())
            self.toolchain.captured.append((job.aspect, index))
            if job.on_segment is not None:
                await job.on_segment(index, path)
            if job.on_progress is not None:
                await job.on_progress(index + 1, total)


@dataclass
class FakeToolchain:
    fps: int = 24
    tail_ms: int = 1000
    chunk_ms: int = 2000
    report: ValidationReport = field(default_factory=ValidationReport)
    validation_failure: Exception | None = None
    capture_failure: Exception = field(default_factory=lambda: ConnectionError("capture crashed"))
    capture_failure_at: tuple[Aspect, int] | None = None
    validations: int = 0
    captured: list[tuple[Aspect, int]] = field(default_factory=list[tuple[Aspect, int]])
    assembled: list[Aspect] = field(default_factory=list[Aspect])
    mixes: list[MixPlan] = field(default_factory=list[MixPlan])
    after_mix: Callable[[], None] | None = None
    assemble_failure: Aspect | None = None

    @property
    def config(self) -> RenderEngineConfig:
        return RenderEngineConfig(fps=self.fps, tail_ms=self.tail_ms, chunk_seconds=self.chunk_ms // 1000)

    def plan_segments(self, narration: NarrationDocument, aspect: Aspect, directory: Path) -> SegmentPlan:
        total_ms = narration.total_duration_ms + self.tail_ms
        frames = max(1, -(-total_ms * self.fps // 1000))
        chunk_frames = self.fps * self.chunk_ms // 1000
        count = -(-frames // chunk_frames)
        paths = tuple(directory / aspect.label / f"{index:05d}.mp4" for index in range(count))
        return SegmentPlan(frames, paths, f"plan-{self.fps}-{frames}")

    async def normalize(self, source: bytes, destination: Path) -> NormalizedAudio:
        write_file(destination, source)
        return NormalizedAudio(destination, parse_wav(source).duration_ms)

    async def mix(self, plan: MixPlan, destination: Path) -> None:
        self.mixes.append(plan)
        write_file(destination, b"mixed-audio")
        if self.after_mix is not None:
            self.after_mix()

    @asynccontextmanager
    async def browser(self) -> AsyncGenerator[RenderBrowser]:
        yield FakeBrowser(self)

    async def assemble(self, job: AssembleJob) -> Path:
        if self.assemble_failure is job.aspect:
            raise ConnectionError("assemble crashed")
        self.assembled.append(job.aspect)
        output = job.directory / f"{job.aspect.label}.mp4"
        write_file(output, b"video-" + b"".join(read_file(path) for path in job.segments))
        return output

    async def posters(self, job: PosterJob) -> PosterFiles:
        files = PosterFiles(
            webp=job.directory / f"poster-{job.aspect.label}.webp",
            jpeg=job.directory / f"poster-{job.aspect.label}.jpg",
        )
        write_file(files.webp, b"webp")
        write_file(files.jpeg, b"jpeg")
        return files

    async def write_fonts(self, directory: Path) -> Path:
        make_directory(directory)
        return directory
