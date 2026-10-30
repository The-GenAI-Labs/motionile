from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.config import get_settings
from motionile.core.resources import Resources, build_resources
from motionile.core.tasks.registry import Queue, defer_after_commit, task
from motionile.modules.prompts.domain import EvalQueue
from motionile.modules.prompts.eval_runs import EvalRunService
from motionile.modules.prompts.executor import eval_executor_for
from motionile.modules.prompts.gate import ActivationGate
from motionile.modules.prompts.repository import SqlPromptRepository
from motionile.modules.prompts.runner import EvalRunner


async def execute_eval(run_id: str) -> None:
    resources = build_resources(get_settings(), application_name="motionile-prompts-eval")
    try:
        runner = EvalRunner(build_eval_run_service(resources), lambda: eval_executor_for(resources))
        await runner.run(UUID(run_id))
    finally:
        await resources.aclose()


@task(name="prompts.run_eval", queue=Queue.GENERATION, retry=False)
async def run_eval(run_id: str) -> None:
    await execute_eval(run_id)


@task(name="prompts.run_eval_browser", queue=Queue.RENDER, retry=False)
async def run_eval_browser(run_id: str) -> None:
    await execute_eval(run_id)


def defer_eval_run(session: AsyncSession, run_id: UUID, queue: EvalQueue) -> None:
    body = run_eval_browser if queue is EvalQueue.BROWSER else run_eval
    defer_after_commit(session, body, run_id=str(run_id))


def build_eval_run_service(resources: Resources) -> EvalRunService:
    return EvalRunService(
        transaction=resources.database.transaction,
        store_factory=SqlPromptRepository,
        gate=ActivationGate(SqlPromptRepository),
        clock=resources.clock,
        enqueue=defer_eval_run,
    )
