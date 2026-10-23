from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.core.config import Settings
from motionile.core.storage.base import Storage
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.audio.providers.base import Transcriber
from motionile.engine.render.models import ValidationReport
from motionile.modules.media.assets import AssetService
from motionile.modules.media.domain import RenderStage
from motionile.modules.media.music import MusicService
from motionile.modules.media.pipeline.ports import RenderToolchain, SpeechPort
from motionile.modules.media.pipeline.progress import CancelWatch, ProgressReporter
from motionile.modules.media.pipeline.reports import report_from_bytes
from motionile.modules.media.pipeline.workspace import Workspace
from motionile.modules.media.ports import Transaction
from motionile.modules.media.render_events import RenderEvents
from motionile.modules.media.render_options import RenderOptions
from motionile.modules.media.render_repository import RenderJobStore

type CommitHook = Callable[[AsyncSession], Awaitable[Mapping[str, Any]]]
type JobStoreFactory = Callable[[AsyncSession], RenderJobStore]

SANITIZE_REPORT = "sanitize-report"
CLEAN_COMPOSITION = "clean-composition"
NARRATION = "narration"
VALIDATION_REPORT = "validation-report"
UPLOAD_CHECKPOINT = "upload"
PADDING_FIELD = "paddingMs"
FRAMES_FIELD = "totalFrames"


@dataclass
class PipelineDeps:
    transaction: Transaction
    storage: Storage
    assets: AssetService
    speech: SpeechPort
    music: MusicService
    transcriber: Transcriber
    toolchain_for: Callable[[int], RenderToolchain]
    events: RenderEvents
    settings: Settings
    clock: Clock
    store_factory: JobStoreFactory


@dataclass
class StageResult:
    keys: dict[str, str] = field(default_factory=dict[str, str])
    data: dict[str, Any] = field(default_factory=dict[str, Any])
    columns: dict[str, Any] = field(default_factory=dict[str, Any])
    commit: CommitHook | None = None


@dataclass
class RenderRun:
    render_id: UUID
    owner_id: UUID
    options: RenderOptions
    composition_asset_id: UUID
    checkpoints: dict[str, Any]
    workspace: Workspace
    progress: ProgressReporter
    cancel: CancelWatch
    seed: int
    toolchain: RenderToolchain
    narration: NarrationDocument | None = None
    clean_html: str | None = None
    sanitize_report: ValidationReport | None = None
    timings: dict[str, int] = field(default_factory=dict[str, int])

    def checkpoint_keys(self, stage: str) -> Mapping[str, str]:
        recorded: Mapping[str, Any] = self.checkpoints.get(stage, {})
        keys: Mapping[str, str] = recorded.get("keys", {})
        return keys

    def checkpoint_value(self, stage: str, name: str) -> Any:
        recorded: Mapping[str, Any] = self.checkpoints.get(stage, {})
        return recorded.get(name)

    async def checkpoint(self) -> None:
        await self.cancel.raise_if_requested()

    async def load_narration(self) -> NarrationDocument:
        if self.narration is None:
            raw = await self.workspace.get_bytes(self.checkpoint_keys(RenderStage.VOICING.value)[NARRATION])
            self.narration = NarrationDocument.model_validate_json(raw)
        return self.narration

    async def load_clean_html(self) -> str:
        if self.clean_html is None:
            raw = await self.workspace.get_bytes(self.checkpoint_keys(RenderStage.PREPARING.value)[CLEAN_COMPOSITION])
            self.clean_html = raw.decode("utf-8")
        return self.clean_html

    async def load_sanitize_report(self) -> ValidationReport:
        if self.sanitize_report is None:
            raw = await self.workspace.get_bytes(self.checkpoint_keys(RenderStage.PREPARING.value)[SANITIZE_REPORT])
            self.sanitize_report = report_from_bytes(raw)
        return self.sanitize_report


class Stage(Protocol):
    stage: RenderStage

    async def execute(self, run: RenderRun) -> StageResult: ...
