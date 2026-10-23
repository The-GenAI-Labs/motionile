from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import UUID

from motionile.engine.audio.mix import MixPlan
from motionile.engine.audio.models import SynthesisOptions, VoiceRef
from motionile.engine.audio.narration import NormalizedAudio
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.audio.synthesis import NarratedAudio
from motionile.engine.render.models import Aspect, RenderEngineConfig, ValidationReport
from motionile.engine.render.thumbnails import PosterFiles

type CancelProbe = Callable[[], Awaitable[bool]]
type FrameProgress = Callable[[int, int], Awaitable[None]]
type SegmentUploaded = Callable[[int, Path | None], Awaitable[None]]


class SpeechPort(Protocol):
    def default_options(self, provider: str, language: str) -> SynthesisOptions: ...

    async def synthesize_text(
        self, voice: VoiceRef, text: str, options: SynthesisOptions, *, user_id: UUID, job_id: UUID | None = None
    ) -> NarratedAudio: ...


@dataclass(frozen=True)
class SegmentPlan:
    total_frames: int
    segments: tuple[Path, ...]
    fingerprint: str


@dataclass(frozen=True)
class CaptureJob:
    html: str
    narration: NarrationDocument
    aspect: Aspect
    seed: int
    segment_directory: Path
    completed_chunks: frozenset[int] = frozenset()
    on_segment: SegmentUploaded | None = None
    on_progress: FrameProgress | None = None
    should_cancel: CancelProbe | None = None


@dataclass(frozen=True)
class AssembleJob:
    segments: tuple[Path, ...]
    audio: Path
    aspect: Aspect
    total_frames: int
    directory: Path
    ass_path: Path | None = None
    fonts_directory: Path | None = None


@dataclass(frozen=True)
class PosterJob:
    video: Path
    directory: Path
    aspect: Aspect
    duration_ms: int


@dataclass(frozen=True)
class BrowserValidation:
    html: str
    narration: NarrationDocument
    aspects: Sequence[Aspect]
    seed: int
    should_cancel: CancelProbe | None = None


class RenderBrowser(Protocol):
    async def validate(self, job: BrowserValidation) -> ValidationReport: ...

    async def capture(self, job: CaptureJob) -> None: ...


class AudioNormalizer(Protocol):
    async def normalize(self, source: bytes, destination: Path) -> NormalizedAudio: ...


class RenderToolchain(AudioNormalizer, Protocol):
    @property
    def config(self) -> RenderEngineConfig: ...

    def plan_segments(self, narration: NarrationDocument, aspect: Aspect, directory: Path) -> SegmentPlan: ...

    async def mix(self, plan: MixPlan, destination: Path) -> None: ...

    def browser(self) -> AbstractAsyncContextManager[RenderBrowser]: ...

    async def assemble(self, job: AssembleJob) -> Path: ...

    async def posters(self, job: PosterJob) -> PosterFiles: ...

    async def write_fonts(self, directory: Path) -> Path: ...
