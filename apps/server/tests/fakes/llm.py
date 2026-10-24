from dataclasses import dataclass, field
from uuid import UUID

from motionile.engine.ai.llm.models import CallContext, LlmTask, LlmUsage


@dataclass(frozen=True, slots=True)
class RecordedUsage:
    context: CallContext
    task: LlmTask
    usage: LlmUsage


@dataclass
class InMemoryUsageLedger:
    records: list[RecordedUsage] = field(default_factory=list[RecordedUsage])
    seen_keys: set[str] = field(default_factory=set[str])

    async def record(self, context: CallContext, task: LlmTask, usage: LlmUsage) -> None:
        if context.call_key in self.seen_keys:
            return
        self.seen_keys.add(context.call_key)
        self.records.append(RecordedUsage(context, task, usage))

    async def tokens_used(self, job_id: UUID) -> int:
        return sum(record.usage.total_tokens for record in self.records if record.context.job_id == job_id)

    @property
    def keys(self) -> list[str]:
        return [record.context.call_key for record in self.records]
