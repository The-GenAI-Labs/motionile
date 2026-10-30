import asyncio
from collections.abc import Callable
from typing import Final
from uuid import UUID

import structlog

from motionile.modules.prompts.domain import ERROR_CODE_FORMAT
from motionile.modules.prompts.eval_runs import EvalRunService
from motionile.modules.prompts.exceptions import EvalRunInvalidError
from motionile.modules.prompts.executor import EvalExecutionError, EvalExecutor

EXECUTION_TIMEOUT_SECONDS: Final = 30 * 60
UNAVAILABLE_CODE: Final = "eval_executor_unavailable"
FAILED_CODE: Final = "eval_executor_failed"
TIMEOUT_CODE: Final = "eval_timeout"
INVALID_OUTCOME_CODE: Final = "eval_outcome_invalid"

logger = structlog.get_logger(__name__)

type ExecutorSource = Callable[[], EvalExecutor | None]


class EvalRunner:
    def __init__(
        self,
        runs: EvalRunService,
        executor: ExecutorSource,
        *,
        timeout_seconds: float = EXECUTION_TIMEOUT_SECONDS,
    ) -> None:
        self._runs = runs
        self._executor = executor
        self._timeout_seconds = timeout_seconds

    async def run(self, run_id: UUID) -> None:
        run = await self._runs.running(run_id)
        if run is None:
            logger.info("prompts.eval_run_skipped", run_id=str(run_id))
            return
        executor = self._executor()
        if executor is None:
            await self._runs.fail(run_id, UNAVAILABLE_CODE)
            return
        try:
            async with asyncio.timeout(self._timeout_seconds):
                outcome = await executor.execute(run.id, run.suite, run.prompt_version_ids)
        except TimeoutError:
            await self._runs.fail(run_id, TIMEOUT_CODE)
            return
        except EvalExecutionError as error:
            await self._runs.fail(run_id, error.code if ERROR_CODE_FORMAT.fullmatch(error.code) else FAILED_CODE)
            return
        except Exception:
            logger.exception("prompts.eval_executor_failed", run_id=str(run_id), suite=run.suite)
            await self._runs.fail(run_id, FAILED_CODE)
            return
        try:
            await self._runs.finish(run_id, outcome)
        except EvalRunInvalidError:
            await self._runs.fail(run_id, INVALID_OUTCOME_CODE)
