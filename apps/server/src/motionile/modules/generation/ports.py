from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.engine.ai.guardrails import GuardResult
from motionile.engine.render.models import ValidationReport
from motionile.modules.catalog import TopicBrief
from motionile.modules.media import CompositionCheckRequest
from motionile.modules.platform import SettingValue


class ResumeKind(StrEnum):
    APPROVE = "approve"
    REGENERATE = "regenerate"


type RunDispatch = Callable[[AsyncSession, UUID], None]
type ResumeDispatch = Callable[[AsyncSession, UUID, ResumeKind, str | None], None]


@dataclass(frozen=True, slots=True)
class JobDispatch:
    run: RunDispatch
    resume: ResumeDispatch


@dataclass(frozen=True, slots=True)
class UserPreferences:
    default_style: str | None = None
    language: str | None = None
    default_voice_id: UUID | None = None
    default_aspect: str | None = None
    captions_enabled: bool | None = None


@dataclass(frozen=True, slots=True)
class ChosenVoice:
    voice_id: UUID
    is_cloned: bool


@dataclass(frozen=True, slots=True)
class CheckedFrame:
    scene_id: str
    aspect: str
    time_ms: int
    png: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class CheckOutcome:
    report: ValidationReport
    frames: tuple[CheckedFrame, ...] = ()


class CompositionCheckGateway(Protocol):
    async def run(self, job_id: UUID, request: CompositionCheckRequest) -> CheckOutcome: ...


class PipelineRunner(Protocol):
    async def run(self, job_id: UUID) -> None: ...

    async def resume(self, job_id: UUID, kind: ResumeKind, instructions: str | None) -> None: ...


class SkillLookup(Protocol):
    async def style_exists(self, session: AsyncSession, slug: str) -> bool: ...


class EditGuard(Protocol):
    async def check_edit(self, user_id: UUID, job_id: UUID, texts: Sequence[str]) -> GuardResult: ...

    async def check_instructions(self, user_id: UUID, job_id: UUID, text: str) -> GuardResult: ...


class PreferencesLookup(Protocol):
    async def for_user(self, session: AsyncSession, user_id: UUID) -> UserPreferences: ...


class TopicLookup(Protocol):
    async def published(self, session: AsyncSession, topic_id: UUID) -> TopicBrief | None: ...


class VoiceChoices(Protocol):
    async def choose(self, session: AsyncSession, user_id: UUID, voice_id: UUID) -> ChosenVoice: ...

    async def default_for(
        self, session: AsyncSession, user_id: UUID, preferred: UUID | None, language: str
    ) -> ChosenVoice: ...


class MusicCheck(Protocol):
    async def require_active(self, session: AsyncSession, track_id: UUID) -> object: ...


class RenderCleanup(Protocol):
    async def delete_render(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> None: ...


class SettingsReader(Protocol):
    async def value(self, session: AsyncSession, key: str) -> SettingValue: ...
