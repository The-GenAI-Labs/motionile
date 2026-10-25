from uuid import UUID

import structlog

from motionile.engine.ai.llm.models import CallContext, LlmTask, LlmUsage

logger = structlog.get_logger(__name__)


class LoggedUsageLedger:
    async def record(self, context: CallContext, task: LlmTask, usage: LlmUsage) -> None:
        logger.info(
            "skills.embedding_usage",
            stage=context.stage,
            task=task.value,
            model=usage.model,
            input_tokens=usage.input_tokens,
            cost_micros_usd=usage.cost_micros_usd,
        )

    async def tokens_used(self, job_id: UUID) -> int:
        del job_id
        return 0
