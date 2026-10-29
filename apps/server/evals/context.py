from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import structlog

from evals.browser import BrowserProvider
from evals.clients import LlmSessions
from evals.datasets import Datasets
from evals.errors import EvalAbortError, EvalError
from evals.modes import RunMode, Selection
from evals.results import CaseResult, SuiteResult
from motionile.engine.ai.llm.models import LlmError
from motionile.engine.ai.ports import PromptStore
from motionile.engine.ai.storyboard import StoryboardLimits


@dataclass(slots=True)
class SuiteContext:
    mode: RunMode
    selection: Selection
    datasets: Datasets
    sessions: LlmSessions
    prompts: PromptStore
    browser: BrowserProvider
    limits: StoryboardLimits = field(default_factory=StoryboardLimits)
    allow_browser_skip: bool = False
    memo: dict[str, object] = field(default_factory=dict[str, object])

    @property
    def judged(self) -> bool:
        return self.mode is not RunMode.DETERMINISTIC

    @property
    def changed(self) -> bool:
        return self.selection is Selection.CHANGED_AI


@runtime_checkable
class EvalSuite(Protocol):
    @property
    def name(self) -> str: ...

    async def run(self, context: SuiteContext) -> SuiteResult: ...


logger = structlog.get_logger(__name__)

type CaseBody = Callable[[], Awaitable[CaseResult]]


async def guarded(case_id: str, body: CaseBody) -> CaseResult:
    try:
        return await body()
    except EvalAbortError:
        raise
    except EvalError as error:
        return CaseResult(case_id, error=error.code)
    except LlmError as error:
        return CaseResult(case_id, error=error.code.value)
    except Exception as error:
        logger.warning("evals.case_failed", case=case_id, error=type(error).__name__)
        return CaseResult(case_id, error=type(error).__name__)
