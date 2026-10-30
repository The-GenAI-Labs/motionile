import asyncio
import hashlib
import json
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Final, Literal, Protocol, cast
from uuid import UUID

import structlog
from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel

from motionile.core.storage.base import Storage
from motionile.engine.audio.narration_models import NarrationDocument
from motionile.engine.render.models import (
    Aspect,
    SandboxError,
    ValidationReport,
    ValidationStats,
    issue_from_error,
)
from motionile.engine.render.sanitize import sanitize_composition
from motionile.modules.media.keys import composition_check_key
from motionile.modules.media.pipeline.workspace import bytes_chunks

CHECK_REQUEST_NAME: Final = "request.json"
CHECK_RESULT_NAME: Final = "result.json"
FRAMES_FOLDER: Final = "frames"
JSON_CONTENT_TYPE: Final = "application/json"
PNG_CONTENT_TYPE: Final = "image/png"
FRAME_PERCENTS: Final[tuple[int, ...]] = (25, 75)
MAX_FRAME_WIDTH: Final = 768
SEED_HEX_DIGITS: Final = 8
SEED_MASK: Final = 0x7FFFFFFF
RESULT_VERSION: Final = 1
MODE_VALIDATE: Final = "validate"
MODE_FRAMES: Final = "frames"
HASH_SEPARATOR: Final = b"\x00"

logger = structlog.get_logger(__name__)


class CompositionCheckMismatchError(ValueError):
    pass


class CheckModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        extra="forbid",
        frozen=True,
    )


class CompositionCheckRequest(CheckModel):
    html: str
    narration: NarrationDocument
    aspects: tuple[Aspect, ...]
    want_frames: bool = False

    @property
    def check_id(self) -> str:
        return composition_check_id(self.html, self.narration, self.aspects, want_frames=self.want_frames)

    @property
    def scene_ids(self) -> list[str]:
        return [scene.id for scene in self.narration.scenes]


class FrameEntry(CheckModel):
    scene_id: str
    aspect: Aspect
    time_ms: int
    key: str


class CompositionCheckResult(CheckModel):
    version: Literal[1] = RESULT_VERSION
    check_id: str
    report: ValidationReport
    frames: tuple[FrameEntry, ...] = ()

    @field_validator("report", mode="before")
    @classmethod
    def drop_computed_validity(cls, value: object) -> object:
        if isinstance(value, dict):
            document = cast("dict[str, object]", value)
            return {name: item for name, item in document.items() if name != "valid"}
        return value


@dataclass(frozen=True, slots=True)
class FrameSample:
    scene_id: str
    time_ms: int


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    scene_id: str
    aspect: Aspect
    time_ms: int
    png: bytes


class CheckBrowser(Protocol):
    async def validate(
        self, html: str, narration: NarrationDocument, aspects: Sequence[Aspect], seed: int
    ) -> ValidationReport: ...

    async def capture(
        self, html: str, narration: NarrationDocument, aspect: Aspect, seed: int, samples: Sequence[FrameSample]
    ) -> list[CapturedFrame]: ...


class BrowserOpenerFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[CheckBrowser]: ...


def composition_check_id(
    html: str, narration: NarrationDocument, aspects: Sequence[Aspect | str], *, want_frames: bool
) -> str:
    digest = hashlib.sha256()
    parts = (
        html,
        narration.model_dump_json(by_alias=True),
        ",".join(Aspect(aspect).value for aspect in aspects),
        MODE_FRAMES if want_frames else MODE_VALIDATE,
    )
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(HASH_SEPARATOR)
    return digest.hexdigest()


def seed_for_check(check_id: str) -> int:
    return int(check_id[:SEED_HEX_DIGITS], 16) & SEED_MASK


def frame_samples(narration: NarrationDocument) -> list[FrameSample]:
    return [
        FrameSample(scene.id, scene.start_ms + scene.duration_ms * percent // 100)
        for scene in narration.scenes
        for percent in FRAME_PERCENTS
    ]


def frame_name(index: int) -> str:
    return f"{index:04d}.png"


def encode_json(model: BaseModel) -> bytes:
    return json.dumps(model.model_dump(mode="json", by_alias=True), separators=(",", ":")).encode("utf-8")


class CompositionCheckService:
    def __init__(self, storage: Storage, open_browser: BrowserOpenerFactory, *, timeout_seconds: float) -> None:
        self._storage = storage
        self._open_browser = open_browser
        self._timeout_seconds = timeout_seconds

    async def run(self, job_id: UUID, check_id: str) -> CompositionCheckResult:
        existing = await self._stored_result(job_id, check_id)
        if existing is not None:
            logger.info("media.composition_check_reused", job_id=str(job_id))
            return existing
        request = await self._request(job_id, check_id)
        async with asyncio.timeout(self._timeout_seconds):
            result = await self._execute(job_id, check_id, request)
        await self._storage.put(
            composition_check_key(job_id, check_id, CHECK_RESULT_NAME),
            bytes_chunks(encode_json(result)),
            content_type=JSON_CONTENT_TYPE,
        )
        logger.info(
            "media.composition_check_finished",
            job_id=str(job_id),
            errors=len(result.report.errors),
            warnings=len(result.report.warnings),
            frames=len(result.frames),
        )
        return result

    async def _stored_result(self, job_id: UUID, check_id: str) -> CompositionCheckResult | None:
        key = composition_check_key(job_id, check_id, CHECK_RESULT_NAME)
        if not await self._storage.exists(key):
            return None
        raw = b"".join([chunk async for chunk in self._storage.get(key)])
        return CompositionCheckResult.model_validate_json(raw)

    async def _request(self, job_id: UUID, check_id: str) -> CompositionCheckRequest:
        key = composition_check_key(job_id, check_id, CHECK_REQUEST_NAME)
        raw = b"".join([chunk async for chunk in self._storage.get(key)])
        request = CompositionCheckRequest.model_validate_json(raw)
        if request.check_id != check_id:
            raise CompositionCheckMismatchError("the stored request does not match its check ID")
        return request

    async def _execute(self, job_id: UUID, check_id: str, request: CompositionCheckRequest) -> CompositionCheckResult:
        sanitized = await asyncio.to_thread(sanitize_composition, request.html, scene_ids=request.scene_ids)
        sanitize_report = ValidationReport(
            issues=sanitized.findings, stats=ValidationStats(scenes=len(request.narration.scenes))
        )
        if sanitized.errors:
            return CompositionCheckResult(check_id=check_id, report=sanitize_report)
        seed = seed_for_check(check_id)
        try:
            async with self._open_browser() as browser:
                if request.want_frames:
                    frames = await self._frames(job_id, check_id, browser, sanitized.html, request, seed)
                    return CompositionCheckResult(check_id=check_id, report=sanitize_report, frames=tuple(frames))
                found = await browser.validate(sanitized.html, request.narration, request.aspects, seed)
                return CompositionCheckResult(check_id=check_id, report=ValidationReport.merge(sanitize_report, found))
        except SandboxError as error:
            failure = ValidationReport(issues=(issue_from_error(error),))
            return CompositionCheckResult(check_id=check_id, report=ValidationReport.merge(sanitize_report, failure))

    async def _frames(  # noqa: PLR0913, PLR0917
        self,
        job_id: UUID,
        check_id: str,
        browser: CheckBrowser,
        html: str,
        request: CompositionCheckRequest,
        seed: int,
    ) -> list[FrameEntry]:
        samples = frame_samples(request.narration)
        entries: list[FrameEntry] = []
        for aspect in request.aspects:
            for frame in await browser.capture(html, request.narration, aspect, seed, samples):
                key = composition_check_key(job_id, check_id, FRAMES_FOLDER, frame_name(len(entries)))
                await self._storage.put(key, bytes_chunks(frame.png), content_type=PNG_CONTENT_TYPE)
                entries.append(FrameEntry(scene_id=frame.scene_id, aspect=frame.aspect, time_ms=frame.time_ms, key=key))
        return entries
