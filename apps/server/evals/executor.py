import importlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from evals.browser import BrowserProvider, LocalBrowser, explicit_browser_environment
from evals.cassette import CassetteStore
from evals.clients import LiveSettings, LlmSessions
from evals.context import EvalSuite, SuiteContext
from evals.datasets import load_datasets
from evals.errors import EvalError
from evals.metering import SpendMeter
from evals.modes import RunMode, Selection
from evals.prompts import OverridingPromptStore
from evals.report import model_configuration
from evals.runner import EVALS_PACKAGE, discover_suites, run_suites
from evals.thresholds import THRESHOLDS_PATH, Thresholds, load_thresholds
from motionile.core.resources import Resources
from motionile.engine.ai.llm.config import ProviderKeys, StaticRouting
from motionile.engine.ai.llm.models import RoutingConfig
from motionile.engine.ai.llm.routing import parse_routing
from motionile.engine.ai.ports import ActivePrompt, PromptStore
from motionile.engine.ai.storyboard import StoryboardLimits
from motionile.modules.generation import settings_read_for
from motionile.modules.platform import SettingValue
from motionile.modules.prompts import (
    DatabasePromptStore,
    EvalExecutionError,
    EvalOutcome,
    prompts_under_evaluation,
)

ADMIN_BUDGET_FACTOR: Final = 5
BUDGET_KEY: Final = "evals.ci_live_budget_micros_usd"
ROUTING_KEY: Final = "ai.model_routing"
JOB_LIMIT_SETTING: Final = "ai.job_token_budget"
RATE_MIN_KEY: Final = "ai.speaking_rate_min_milli_wps"
RATE_MAX_KEY: Final = "ai.speaking_rate_max_milli_wps"
MILLI: Final = 1_000
UNKNOWN_SUITE_CODE: Final = "eval_unknown_suite"
CASE_FAILED_CODE: Final = "eval_case_failed"

type SettingReader = Callable[[str], Awaitable[SettingValue]]
type CandidateLoader = Callable[[Sequence[UUID]], Awaitable[list[ActivePrompt]]]


@dataclass(frozen=True, slots=True)
class ExecutionInputs:
    keys: ProviderKeys
    embedding_model: str
    embedding_dimensions: int
    read_setting: SettingReader
    base_prompts: PromptStore
    load_candidates: CandidateLoader


def integer_of(key: str, value: SettingValue) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"setting {key} is not an integer")
    return value


def text_of(key: str, value: SettingValue) -> str:
    if not isinstance(value, str):
        raise TypeError(f"setting {key} is not a string")
    return value


class SuiteExecutor:
    def __init__(
        self,
        inputs: ExecutionInputs,
        *,
        browser: BrowserProvider | None = None,
        suites: Sequence[EvalSuite] | None = None,
        thresholds: Thresholds | None = None,
    ) -> None:
        self._inputs = inputs
        self._browser = browser or LocalBrowser()
        self._suites = list(suites) if suites is not None else discover_suites(importlib.import_module(EVALS_PACKAGE))
        self._thresholds = thresholds if thresholds is not None else load_thresholds(THRESHOLDS_PATH)

    def _suite(self, name: str) -> EvalSuite:
        for suite in self._suites:
            if suite.name == name:
                return suite
        raise EvalExecutionError(UNKNOWN_SUITE_CODE)

    async def _context(self, version_ids: Sequence[UUID], meter: SpendMeter) -> tuple[SuiteContext, RoutingConfig]:
        inputs = self._inputs
        read = inputs.read_setting
        routing = parse_routing(text_of(ROUTING_KEY, await read(ROUTING_KEY)))
        limits = StoryboardLimits(
            min_words_per_second=integer_of(RATE_MIN_KEY, await read(RATE_MIN_KEY)) / MILLI,
            max_words_per_second=integer_of(RATE_MAX_KEY, await read(RATE_MAX_KEY)) / MILLI,
        )
        live = LiveSettings(
            keys=inputs.keys,
            routing=StaticRouting(routing),
            job_token_budget=integer_of(JOB_LIMIT_SETTING, await read(JOB_LIMIT_SETTING)),
            embedding_model=inputs.embedding_model,
            embedding_dimensions=inputs.embedding_dimensions,
        )
        datasets = load_datasets()
        candidates = await inputs.load_candidates(version_ids)
        sessions = LlmSessions(mode=RunMode.LIVE, meter=meter, datasets=datasets, cassettes=CassetteStore(), live=live)
        context = SuiteContext(
            mode=RunMode.LIVE,
            selection=Selection.FULL,
            datasets=datasets,
            sessions=sessions,
            prompts=OverridingPromptStore(inputs.base_prompts, {prompt.key: prompt for prompt in candidates}),
            browser=self._browser,
            limits=limits,
        )
        return context, routing

    async def execute(self, run_id: UUID, suite: str, version_ids: Sequence[UUID]) -> EvalOutcome:
        del run_id
        selected = self._suite(suite)
        budget = integer_of(BUDGET_KEY, await self._inputs.read_setting(BUDGET_KEY)) * ADMIN_BUDGET_FACTOR
        meter = SpendMeter(budget_micros=budget)
        try:
            context, routing = await self._context(version_ids, meter)
            execution = await run_suites(context, [selected], self._thresholds)
        except EvalError as error:
            raise EvalExecutionError(error.code) from error
        if execution.aborted is not None:
            raise EvalExecutionError(execution.aborted.code)
        (run,) = execution.runs
        if run.result.errors:
            raise EvalExecutionError(CASE_FAILED_CODE)
        return EvalOutcome(
            scores=run.result.metrics,
            passed=run.passed,
            dataset_version=run.result.dataset_label,
            model_configuration={
                "mode": RunMode.LIVE.value,
                "routing": {
                    task: route.model_dump(by_alias=True) for task, route in model_configuration(routing).items()
                },
                "measuredCases": run.result.measured,
                "liveSpendMicrosUsd": meter.live_micros,
            },
        )


def build_eval_executor(resources: Resources) -> SuiteExecutor:
    settings = resources.settings

    async def load_candidates(version_ids: Sequence[UUID]) -> list[ActivePrompt]:
        if not version_ids:
            return []
        async with resources.database.transaction() as session:
            return await prompts_under_evaluation(session, version_ids)

    inputs = ExecutionInputs(
        keys=ProviderKeys(anthropic=settings.ai.anthropic_api_key, openai=settings.openai.api_key),
        embedding_model=settings.ai.embedding_model,
        embedding_dimensions=settings.ai.embedding_dimensions,
        read_setting=settings_read_for(resources),
        base_prompts=DatabasePromptStore(resources.database.transaction),
        load_candidates=load_candidates,
    )
    return SuiteExecutor(inputs, browser=LocalBrowser(explicit_browser_environment(settings)))
