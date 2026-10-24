import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final, Self

from pydantic import BaseModel, ValidationError

from motionile.engine.ai.job_options import AspectName
from motionile.engine.ai.llm.config import BudgetProvider, RoutingProvider, StaticRouting
from motionile.engine.ai.llm.fake_planner import PlannerRequest, planner_fixture_for, scale_storyboard
from motionile.engine.ai.llm.metadata import CallMetadataKey, split_aspects
from motionile.engine.ai.llm.models import (
    LlmCall,
    LlmError,
    LlmResult,
    LlmTask,
    LlmUsage,
    ModelOutputInvalidError,
    Tracer,
    UsageLedger,
)
from motionile.engine.ai.llm.prompt import summarize_user_blocks
from motionile.engine.ai.llm.redaction import trace_text
from motionile.engine.ai.llm.routing import DEFAULT_ROUTING
from motionile.engine.ai.llm.tracing import NoopTracer
from motionile.engine.ai.llm.usage import BudgetGuard, estimate_blocks_tokens, estimate_tokens, usage_context
from motionile.engine.ai.storyboard import Storyboard, StoryboardLimits

type FakeStep = str | LlmError

SCENE_ID_PLACEHOLDER: Final = "{{sceneId}}"
DEFAULT_KEY: Final = "default"
DEFAULT_PLAN_DURATION_MS: Final = 60_000
ASPECT_NAMES: Final[tuple[AspectName, ...]] = ("16:9", "9:16", "1:1")
DEFAULT_ASPECTS: Final[tuple[AspectName, ...]] = ("16:9",)
SCENE_TASKS: Final = frozenset({LlmTask.SCENE, LlmTask.REPAIR})

FIXTURE_DIRECTORIES: Final[Mapping[LlmTask, str]] = {
    LlmTask.GUARD: "guard",
    LlmTask.ROUTE: "route",
    LlmTask.PLAN: "plan",
    LlmTask.CRITIQUE: "critique",
    LlmTask.SCENE: "scene",
    LlmTask.REPAIR: "scene",
    LlmTask.VISION_REVIEW: "review",
    LlmTask.CAPTION: "caption",
}
DEFAULT_FIXTURES: Final[Mapping[LlmTask, str]] = {
    LlmTask.GUARD: "allow",
    LlmTask.ROUTE: "default",
    LlmTask.PLAN: "default",
    LlmTask.CRITIQUE: "pass",
    LlmTask.SCENE: "default",
    LlmTask.REPAIR: "default",
    LlmTask.VISION_REVIEW: "clean",
    LlmTask.CAPTION: "default",
}


class FakeFixtureMissingError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class FakeScript:
    fixtures: Mapping[tuple[LlmTask, str], str] = field(default_factory=dict[tuple[LlmTask, str], str])
    scene_attempts: Mapping[str, tuple[FakeStep, ...]] = field(default_factory=dict[str, tuple[FakeStep, ...]])
    task_attempts: Mapping[LlmTask, tuple[FakeStep, ...]] = field(default_factory=dict[LlmTask, tuple[FakeStep, ...]])

    @classmethod
    def for_scene(cls, scene_id: str, attempts: Sequence[FakeStep]) -> Self:
        return cls().with_scene(scene_id, attempts)

    @classmethod
    def for_task(cls, task: LlmTask, attempts: Sequence[FakeStep]) -> Self:
        return cls().with_task(task, attempts)

    def with_scene(self, scene_id: str, attempts: Sequence[FakeStep]) -> Self:
        return type(self)(self.fixtures, {**self.scene_attempts, scene_id: tuple(attempts)}, self.task_attempts)

    def with_task(self, task: LlmTask, attempts: Sequence[FakeStep]) -> Self:
        return type(self)(self.fixtures, self.scene_attempts, {**self.task_attempts, task: tuple(attempts)})

    def with_fixture(self, task: LlmTask, key: str, fixture: str) -> Self:
        return type(self)({**self.fixtures, (task, key): fixture}, self.scene_attempts, self.task_attempts)

    def fixture_name(self, task: LlmTask, key: str) -> str:
        scripted = self.fixtures.get((task, key))
        if scripted is not None:
            return scripted
        return DEFAULT_FIXTURES[task] if key == DEFAULT_KEY else key


class FixtureLibrary:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._cache: dict[Path, str] = {}

    async def text(self, task: LlmTask, name: str) -> str:
        path = self._root / FIXTURE_DIRECTORIES[task] / f"{name}.json"
        cached = self._cache.get(path)
        if cached is not None:
            return cached
        try:
            text = await asyncio.to_thread(path.read_text, encoding="utf-8")
        except FileNotFoundError:
            raise FakeFixtureMissingError(f"no fixture {FIXTURE_DIRECTORIES[task]}/{name}.json") from None
        self._cache[path] = text
        return text


def pick(attempts: Sequence[FakeStep], index: int) -> FakeStep:
    return attempts[min(index, len(attempts) - 1)]


def planner_request(call: LlmCall) -> PlannerRequest:
    metadata = call.metadata
    duration = metadata.get(CallMetadataKey.DURATION_MS.value)
    aspects = parse_aspects(metadata.get(CallMetadataKey.ASPECTS.value, ""))
    return PlannerRequest(
        duration_ms=int(duration) if duration is not None else DEFAULT_PLAN_DURATION_MS,
        aspects=aspects or list(DEFAULT_ASPECTS),
        language=metadata.get(CallMetadataKey.LANGUAGE.value, "en"),
        style=metadata.get(CallMetadataKey.STYLE.value),
    )


def parse_aspects(raw: str) -> list[AspectName]:
    return [name for part in split_aspects(raw) for name in ASPECT_NAMES if name == part]


class FakeLlm:
    def __init__(  # noqa: PLR0913
        self,
        *,
        fixtures_root: Path,
        ledger: UsageLedger,
        budget: BudgetProvider,
        script: FakeScript | None = None,
        routing: RoutingProvider | None = None,
        tracer: Tracer | None = None,
        limits: StoryboardLimits | None = None,
    ) -> None:
        self._library = FixtureLibrary(fixtures_root)
        self._ledger = ledger
        self._guard = BudgetGuard(ledger, budget)
        self._script = script or FakeScript()
        self._routing: RoutingProvider = routing or StaticRouting(DEFAULT_ROUTING)
        self._tracer: Tracer = tracer or NoopTracer()
        self._limits = limits or StoryboardLimits()
        self._scene_calls: dict[str, int] = {}
        self._task_calls: dict[LlmTask, int] = {}
        self.calls: list[LlmCall] = []

    async def generate[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]:
        self.calls.append(call)
        route = (await self._routing.routing()).route(call.task)
        input_tokens = estimate_blocks_tokens(call.system_blocks, call.user_blocks)
        await self._guard.ensure(call.context, input_tokens=input_tokens, max_output_tokens=route.max_output_tokens)
        span = self._tracer.span(
            call.context, f"{call.task.value}.{call.context.stage}", trace_text(summarize_user_blocks(call.user_blocks))
        )
        try:
            result = await self._produce(call, output, input_tokens)
        except LlmError as error:
            span.fail(error.code.value)
            raise
        else:
            span.set_usage(result.usage)
            span.set_output(trace_text(result.output.model_dump_json(by_alias=True)))
            return result
        finally:
            span.end()

    async def _produce[OutputT: BaseModel](
        self, call: LlmCall, output: type[OutputT], input_tokens: int
    ) -> LlmResult[OutputT]:
        text = await self._respond(call)
        try:
            parsed = output.model_validate_json(text)
        except ValidationError:
            raise ModelOutputInvalidError from None
        usage = LlmUsage(
            provider="fake",
            model=f"fake/{call.task.value}",
            input_tokens=input_tokens,
            output_tokens=estimate_tokens(text),
            cached_input_tokens=0,
            cost_micros_usd=0,
        )
        await self._ledger.record(usage_context(call.context, usage.model, 0), call.task, usage)
        return LlmResult(output=parsed, usage=usage, attempts=1, fallback_used=False)

    def _next_step(self, call: LlmCall) -> FakeStep | None:
        scene_id = call.metadata.get(CallMetadataKey.SCENE_ID.value)
        if call.task in SCENE_TASKS and scene_id is not None and scene_id in self._script.scene_attempts:
            index = self._scene_calls.get(scene_id, 0)
            self._scene_calls[scene_id] = index + 1
            return pick(self._script.scene_attempts[scene_id], index)
        task_attempts = self._script.task_attempts.get(call.task)
        if task_attempts is not None:
            index = self._task_calls.get(call.task, 0)
            self._task_calls[call.task] = index + 1
            return pick(task_attempts, index)
        return None

    def _fixture_key(self, call: LlmCall) -> str:
        explicit = call.metadata.get(CallMetadataKey.FIXTURE.value)
        if explicit is not None:
            return explicit
        if call.task is LlmTask.PLAN:
            topic = call.metadata.get(CallMetadataKey.TOPIC.value)
            return planner_fixture_for(topic) if topic is not None else DEFAULT_KEY
        return DEFAULT_KEY

    async def _respond(self, call: LlmCall) -> str:
        step = self._next_step(call)
        if isinstance(step, LlmError):
            raise step
        name = step if step is not None else self._script.fixture_name(call.task, self._fixture_key(call))
        text = await self._library.text(call.task, name)
        if call.task is LlmTask.PLAN:
            return self._scaled_storyboard(text, call)
        scene_id = call.metadata.get(CallMetadataKey.SCENE_ID.value)
        if call.task in SCENE_TASKS and scene_id is not None:
            return text.replace(SCENE_ID_PLACEHOLDER, scene_id)
        return text

    def _scaled_storyboard(self, text: str, call: LlmCall) -> str:
        source = Storyboard.model_validate_json(text)
        return scale_storyboard(source, planner_request(call), self._limits).model_dump_json(by_alias=True)
