from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr

from evals.context import SuiteContext
from evals.errors import BrowserUnavailableError, EvalBudgetExceededError
from evals.executor import ADMIN_BUDGET_FACTOR, ExecutionInputs, SuiteExecutor
from evals.modes import RunMode, Selection
from evals.prompts import FilePromptStore
from evals.results import CaseResult, Measurement, SuiteResult
from evals.thresholds import Bound, MetricThreshold
from motionile.engine.ai.llm.config import ProviderKeys
from motionile.engine.ai.llm.routing import DEFAULT_ROUTING_JSON
from motionile.engine.ai.ports import ActivePrompt
from motionile.modules.generation.runtime_settings import MILLI
from motionile.modules.platform import SettingValue
from motionile.modules.prompts import EvalExecutionError

SETTINGS: dict[str, SettingValue] = {
    "ai.model_routing": DEFAULT_ROUTING_JSON,
    "ai.speaking_rate_min_milli_wps": 2100,
    "ai.speaking_rate_max_milli_wps": 2700,
    "ai.job_token_budget": 123_456,
    "evals.ci_live_budget_micros_usd": 1_000_000,
}
KEYS = ProviderKeys(anthropic=SecretStr("a"), openai=SecretStr("o"))


@dataclass
class RecordingSuite:
    name: str = "planner"
    metrics: dict[str, float] = field(default_factory=lambda: {"plan_success_rate": 0.97})
    error: Exception | None = None
    case_error: str | None = None
    seen: list[SuiteContext] = field(default_factory=list[SuiteContext])

    async def run(self, context: SuiteContext) -> SuiteResult:
        self.seen.append(context)
        if self.error is not None:
            raise self.error
        scores = {name: Measurement(value) for name, value in self.metrics.items()}
        cases = (CaseResult("case-1", scores), CaseResult("case-2", error=self.case_error))
        return SuiteResult(self.name, cases if self.case_error else cases[:1], {"golden": "2026-10-24.1"})


async def settings_reader(key: str) -> SettingValue:
    return SETTINGS[key]


def executor(
    suite: RecordingSuite,
    *,
    keys: ProviderKeys = KEYS,
    candidates: list[ActivePrompt] | None = None,
    thresholds: dict[str, dict[str, MetricThreshold]] | None = None,
) -> SuiteExecutor:
    async def load(version_ids: Sequence[UUID]) -> list[ActivePrompt]:
        del version_ids
        return candidates or []

    inputs = ExecutionInputs(
        keys=keys,
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1536,
        read_setting=settings_reader,
        base_prompts=FilePromptStore(),
        load_candidates=load,
    )
    return SuiteExecutor(inputs, suites=[suite], thresholds=thresholds or {})


async def test_a_run_executes_the_suite_live_and_returns_the_outcome() -> None:
    suite = RecordingSuite()

    outcome = await executor(suite).execute(uuid4(), "planner", [uuid4()])

    (context,) = suite.seen
    assert context.mode is RunMode.LIVE
    assert context.selection is Selection.FULL
    assert context.allow_browser_skip is False
    assert context.limits.min_words_per_second == 2100 / MILLI
    assert context.limits.max_words_per_second == 2700 / MILLI
    assert context.sessions.meter.budget_micros == 1_000_000 * ADMIN_BUDGET_FACTOR
    assert outcome.scores == {"plan_success_rate": 0.97}
    assert outcome.passed is True
    assert outcome.dataset_version == "2026-10-24.1"
    assert outcome.model_configuration["mode"] == "live"
    assert outcome.model_configuration["routing"]["plan"]["primary"]


async def test_the_versions_under_test_replace_the_active_prompts_of_their_keys_only() -> None:
    base = FilePromptStore()
    active_planner = await base.active("planner.storyboard")
    draft = ActivePrompt(
        key="planner.storyboard",
        version_id=uuid4(),
        version=active_planner.version + 1,
        body="Draft {{ canary }}",
        canary="mo-canary-draft-0000000000",
        variables=("canary",),
    )
    suite = RecordingSuite()

    await executor(suite, candidates=[draft]).execute(uuid4(), "planner", [draft.version_id])

    prompts = suite.seen[0].prompts
    assert (await prompts.active("planner.storyboard")).version_id == draft.version_id
    assert await prompts.active("critic.storyboard") == await base.active("critic.storyboard")
    assert [prompt.version_id for prompt in await prompts.all_active()].count(draft.version_id) == 1


async def test_a_failing_threshold_produces_an_unsuccessful_outcome() -> None:
    thresholds = {"planner": {"plan_success_rate": MetricThreshold(live=Bound(min=0.99))}}

    outcome = await executor(RecordingSuite(), thresholds=thresholds).execute(uuid4(), "planner", [uuid4()])

    assert outcome.passed is False


async def test_a_metric_above_its_maximum_produces_an_unsuccessful_outcome() -> None:
    suite = RecordingSuite(name="cost", metrics={"tokens_per_job": 500_000.0})
    thresholds = {"cost": {"tokens_per_job": MetricThreshold(default=Bound(max=450_000))}}

    outcome = await executor(suite, thresholds=thresholds).execute(uuid4(), "cost", [uuid4()])

    assert outcome.passed is False


async def test_missing_provider_keys_end_the_run_with_a_stable_code() -> None:
    with pytest.raises(EvalExecutionError) as stopped:
        await executor(RecordingSuite(), keys=ProviderKeys()).execute(uuid4(), "planner", [uuid4()])

    assert stopped.value.code == "eval_keys_missing"


async def test_an_unknown_suite_ends_the_run_with_a_stable_code() -> None:
    with pytest.raises(EvalExecutionError) as stopped:
        await executor(RecordingSuite()).execute(uuid4(), "nope", [uuid4()])

    assert stopped.value.code == "eval_unknown_suite"


async def test_a_budget_stop_ends_the_run_with_eval_budget_exceeded() -> None:
    suite = RecordingSuite(error=EvalBudgetExceededError("over"))

    with pytest.raises(EvalExecutionError) as stopped:
        await executor(suite).execute(uuid4(), "planner", [uuid4()])

    assert stopped.value.code == "eval_budget_exceeded"


async def test_a_missing_browser_ends_the_run_with_a_stable_code() -> None:
    suite = RecordingSuite(name="scenes", error=BrowserUnavailableError("no chromium"))

    with pytest.raises(EvalExecutionError) as stopped:
        await executor(suite).execute(uuid4(), "scenes", [uuid4()])

    assert stopped.value.code == "eval_browser_unavailable"


async def test_errored_cases_end_the_run_instead_of_recording_a_misleading_score() -> None:
    suite = RecordingSuite(case_error="LlmError")

    with pytest.raises(EvalExecutionError) as stopped:
        await executor(suite).execute(uuid4(), "planner", [uuid4()])

    assert stopped.value.code == "eval_case_failed"
