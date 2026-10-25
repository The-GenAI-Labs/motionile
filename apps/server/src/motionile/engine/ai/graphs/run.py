from enum import StrEnum
from typing import Any
from uuid import UUID

import structlog
from langchain_core.runnables.config import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from motionile.engine.ai.graphs.deps import PipelineDependencies
from motionile.engine.ai.graphs.errors import JobCancelled, JobEnded, PipelineError, failure_from_llm
from motionile.engine.ai.graphs.generate_video import CompiledGraph, build_graph
from motionile.engine.ai.graphs.resume import ApprovalResume
from motionile.engine.ai.graphs.state import PipelineState
from motionile.engine.ai.job_options import JobStatus
from motionile.engine.ai.llm.models import LlmError

logger = structlog.get_logger(__name__)


class RunOutcome(StrEnum):
    FINISHED = "finished"
    AWAITING_APPROVAL = "awaiting_approval"
    CANCELLED = "cancelled"
    FAILED = "failed"


OUTCOME_BY_STATUS = {
    JobStatus.COMPLETED: RunOutcome.FINISHED,
    JobStatus.CANCELLED: RunOutcome.CANCELLED,
    JobStatus.FAILED: RunOutcome.FAILED,
}


def thread_config(job_id: UUID, deps: PipelineDependencies) -> RunnableConfig:
    return RunnableConfig(configurable={"thread_id": str(job_id)}, recursion_limit=deps.config.recursion_limit)


async def graph_input(
    graph: CompiledGraph, config: RunnableConfig, job_id: UUID, resume: ApprovalResume | None
) -> PipelineState | Command[Any] | None:
    snapshot = await graph.aget_state(config)
    if not snapshot.values and not snapshot.next:
        return PipelineState(job_id=str(job_id))
    if resume is not None and snapshot.next:
        return Command(resume=resume.model_dump(mode="json"))
    return None


async def fail_job(deps: PipelineDependencies, job_id: UUID, code: str, message: str) -> RunOutcome:
    logger.info("ai.job_failed", job_id=str(job_id), code=code)
    await deps.store.fail(job_id, code, message)
    return RunOutcome.FAILED


async def run_graph(
    deps: PipelineDependencies,
    job_id: UUID,
    checkpointer: BaseCheckpointSaver[Any],
    resume: ApprovalResume | None = None,
) -> RunOutcome:
    graph = build_graph(deps, checkpointer)
    config = thread_config(job_id, deps)
    try:
        await graph.ainvoke(await graph_input(graph, config, job_id, resume), config)  # type: ignore[reportUnknownMemberType]
    except JobCancelled:
        await deps.store.finish_cancellation(job_id)
        return RunOutcome.CANCELLED
    except JobEnded as ended:
        return OUTCOME_BY_STATUS[ended.status]
    except PipelineError as error:
        return await fail_job(deps, job_id, error.code, error.message)
    except LlmError as error:
        failure = failure_from_llm(error)
        return await fail_job(deps, job_id, failure.code, failure.message)
    state = await graph.aget_state(config)
    return RunOutcome.AWAITING_APPROVAL if state.next else RunOutcome.FINISHED
