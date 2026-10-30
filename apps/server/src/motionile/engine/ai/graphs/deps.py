import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from motionile.engine.ai.guardrails.input_guard import InputGuard
from motionile.engine.ai.guardrails.output_guard import OutputGuard
from motionile.engine.ai.job_options import MAX_DURATION_SECONDS
from motionile.engine.ai.llm.models import LlmClient
from motionile.engine.ai.ports import (
    ActivePrompt,
    CompositionChecker,
    ContextProvider,
    LoadedSkill,
    Narrator,
    PipelineStore,
    PromptStore,
    RenderGateway,
    SkillCatalog,
    SkillRouter,
)
from motionile.engine.ai.prompts.canary import OutputScanner
from motionile.engine.ai.storyboard import StoryboardLimits

type ScannerFactory = Callable[[Sequence[ActivePrompt], Sequence[LoadedSkill]], OutputScanner]

MS_PER_SECOND = 1000


class Clock(Protocol):
    def monotonic(self) -> float: ...

    def now(self) -> datetime: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def now(self) -> datetime:
        return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    max_repairs: int = 2
    scene_concurrency: int = 4
    skill_token_budget: int = 12_000
    limits: StoryboardLimits = field(default_factory=StoryboardLimits)
    visual_review_enabled: bool = True
    render_poll_seconds: float = 2.0
    render_timeout_seconds: float = 1_800.0
    approval_timeout_hours: int = 168
    max_duration_ms: int = MAX_DURATION_SECONDS * MS_PER_SECOND

    @property
    def recursion_limit(self) -> int:
        return 40 + 12 * (self.max_repairs + 1)


@dataclass(frozen=True, slots=True)
class PipelineDependencies:
    store: PipelineStore
    narrator: Narrator
    checker: CompositionChecker
    renders: RenderGateway
    prompts: PromptStore
    skill_router: SkillRouter
    catalog: SkillCatalog
    llm: LlmClient
    input_guard: InputGuard
    output_guard: OutputGuard
    providers: Sequence[ContextProvider] = ()
    config: PipelineConfig = field(default_factory=PipelineConfig)
    clock: Clock = field(default_factory=SystemClock)
    scanner_factory: ScannerFactory = OutputScanner
