import asyncio
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID

from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel
from tests.fakes.llm import InMemoryUsageLedger
from tests.fakes.pipeline import (
    FakeNarrator,
    FakeRenderGateway,
    InMemoryPipelineStore,
    IssueRule,
    ScriptedChecker,
    StaticSkillCatalog,
    StaticSkillRouter,
    make_job,
)
from tests.unit.engine.ai.llm.support import FIXTURES_ROOT
from tests.unit.engine.ai.support import USAGE, StaticPrompts

from motionile.engine.ai.graphs.deps import PipelineConfig, PipelineDependencies
from motionile.engine.ai.graphs.resume import ApprovalResume
from motionile.engine.ai.graphs.run import RunOutcome, run_graph
from motionile.engine.ai.guardrails.input_guard import InputGuard
from motionile.engine.ai.guardrails.output_guard import OutputGuard
from motionile.engine.ai.llm.config import StaticBudget
from motionile.engine.ai.llm.fake import FakeLlm, FakeScript
from motionile.engine.ai.llm.models import LlmCall, LlmResult, LlmTask
from motionile.engine.ai.ports import JobSnapshot
from motionile.engine.ai.prompts.canary import OutputScanner

SCENE_TASKS = frozenset({LlmTask.SCENE, LlmTask.REPAIR})
SCENE_COUNT_FOR_THIRTY_SECONDS = 3


class FakeClock:
    def __init__(self) -> None:
        self._ticks = 0.0

    def monotonic(self) -> float:
        self._ticks += 0.25
        return self._ticks

    def now(self) -> datetime:
        return datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


class SpyLlm:
    def __init__(
        self,
        inner: FakeLlm,
        *,
        overrides: Mapping[LlmTask, Sequence[BaseModel | Exception]] | None = None,
        before_call: Callable[[LlmCall], None] | None = None,
        fail_call: tuple[LlmTask, int, Exception] | None = None,
    ) -> None:
        self.inner = inner
        self.calls: list[LlmCall] = []
        self.in_flight = 0
        self.max_in_flight = 0
        self._overrides = {task: list(items) for task, items in (overrides or {}).items()}
        self._before_call = before_call
        self._fail_call = fail_call
        self._seen: Counter[LlmTask] = Counter()

    async def generate[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]:
        self.calls.append(call)
        index = self._seen[call.task]
        self._seen[call.task] += 1
        if self._before_call is not None:
            self._before_call(call)
        if self._fail_call is not None and self._fail_call[0] is call.task and self._fail_call[1] == index:
            raise self._fail_call[2]
        scripted = self._overrides.get(call.task)
        if scripted:
            item = scripted.pop(0)
            if isinstance(item, Exception):
                raise item
            if not isinstance(item, output):
                raise TypeError("the scripted output does not match the requested model")
            return LlmResult(output=item, usage=USAGE, attempts=1, fallback_used=False)
        if call.task in SCENE_TASKS:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
            try:
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                return await self.inner.generate(call, output)
            finally:
                self.in_flight -= 1
        return await self.inner.generate(call, output)

    def script(self, task: LlmTask, *items: BaseModel | Exception) -> None:
        self._overrides.setdefault(task, []).extend(items)

    def calls_of(self, task: LlmTask) -> list[LlmCall]:
        return [call for call in self.calls if call.task is task]

    @property
    def tasks(self) -> Counter[LlmTask]:
        return Counter(call.task for call in self.calls)


@dataclass
class Harness:
    job: JobSnapshot
    store: InMemoryPipelineStore
    narrator: FakeNarrator
    checker: ScriptedChecker
    renders: FakeRenderGateway
    router: StaticSkillRouter
    catalog: StaticSkillCatalog
    prompts: StaticPrompts
    saver: InMemorySaver
    config: PipelineConfig
    script: FakeScript | None
    budget: int
    overrides: Mapping[LlmTask, Sequence[BaseModel | Exception]] | None
    before_call: Callable[[LlmCall], None] | None
    fail_call: tuple[LlmTask, int, Exception] | None
    ledger: InMemoryUsageLedger = field(default_factory=InMemoryUsageLedger)
    llm: SpyLlm = field(init=False)
    deps: PipelineDependencies = field(init=False)

    def __post_init__(self) -> None:
        fake = FakeLlm(
            fixtures_root=FIXTURES_ROOT, ledger=self.ledger, budget=StaticBudget(self.budget), script=self.script
        )
        self.llm = SpyLlm(fake, overrides=self.overrides, before_call=self.before_call, fail_call=self.fail_call)
        scanner = OutputScanner(list(self.prompts.prompts.values()), self.router.selected.all)
        self.deps = PipelineDependencies(
            store=self.store,
            narrator=self.narrator,
            checker=self.checker,
            renders=self.renders,
            prompts=self.prompts,
            skill_router=self.router,
            catalog=self.catalog,
            llm=self.llm,
            input_guard=InputGuard(self.llm, self.prompts),
            output_guard=OutputGuard(self.llm, self.prompts, scanner),
            config=self.config,
            clock=FakeClock(),
        )

    async def run(self, resume: ApprovalResume | None = None) -> RunOutcome:
        return await run_graph(self.deps, self.job.id, self.saver, resume)

    def restarted(self, *, script: FakeScript | None = None) -> "Harness":
        return replace(
            self,
            script=script,
            ledger=InMemoryUsageLedger(),
            overrides=None,
            before_call=None,
            fail_call=None,
        )

    @property
    def job_id(self) -> UUID:
        return self.job.id

    @property
    def tasks(self) -> Counter[LlmTask]:
        return self.llm.tasks

    def storyboard_ids(self) -> list[str]:
        return [scene.id for scene in self.store.storyboards[-1].content.scenes]


def build_harness(  # noqa: PLR0913
    *,
    job: JobSnapshot | None = None,
    script: FakeScript | None = None,
    rules: Sequence[IssueRule] = (),
    config: PipelineConfig | None = None,
    narrator: FakeNarrator | None = None,
    renders: FakeRenderGateway | None = None,
    budget: int = 2_000_000,
    overrides: Mapping[LlmTask, Sequence[BaseModel | Exception]] | None = None,
    before_call: Callable[[LlmCall], None] | None = None,
    fail_call: tuple[LlmTask, int, Exception] | None = None,
) -> Harness:
    resolved = job or make_job(duration_seconds=30)
    return Harness(
        job=resolved,
        store=InMemoryPipelineStore(resolved),
        narrator=narrator or FakeNarrator(),
        checker=ScriptedChecker(*rules),
        renders=renders or FakeRenderGateway(),
        router=StaticSkillRouter(),
        catalog=StaticSkillCatalog(),
        prompts=StaticPrompts(),
        saver=InMemorySaver(),
        config=config or PipelineConfig(render_poll_seconds=0.001),
        script=script,
        budget=budget,
        overrides=overrides,
        before_call=before_call,
        fail_call=fail_call,
    )
