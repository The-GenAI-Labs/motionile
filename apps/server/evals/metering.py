from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from pydantic import BaseModel

from evals.errors import EvalBudgetExceededError
from motionile.engine.ai.llm.models import CallContext, LlmCall, LlmClient, LlmResult, LlmTask, LlmUsage
from motionile.engine.ai.llm.routing import DEFAULT_ROUTING, HAIKU, OPUS, SONNET

TOKENS_PER_MILLION: Final = 1_000_000
SYNTHETIC_PROVIDERS: Final = frozenset({"fake", "scripted"})
EMBED_STAGE: Final = "embed"

SYNTHETIC_PRICES: Final[Mapping[str, tuple[int, int]]] = {
    HAIKU: (1_000_000, 5_000_000),
    SONNET: (3_000_000, 15_000_000),
    OPUS: (15_000_000, 75_000_000),
}


def synthetic_cost_micros(task: LlmTask, usage: LlmUsage) -> int:
    model = DEFAULT_ROUTING.route(task).primary
    input_price, output_price = SYNTHETIC_PRICES[model]
    return round((usage.input_tokens * input_price + usage.output_tokens * output_price) / TOKENS_PER_MILLION)


@dataclass(slots=True)
class SpendMeter:
    budget_micros: int | None = None
    live_micros: int = 0

    def add(self, micros: int) -> None:
        self.live_micros += micros

    def ensure_available(self) -> None:
        if self.budget_micros is not None and self.live_micros >= self.budget_micros:
            raise EvalBudgetExceededError(
                f"the live spend of {self.live_micros} micro-dollars reached the budget of {self.budget_micros}"
            )


@dataclass(frozen=True, slots=True)
class RecordedCall:
    job_id: UUID | None
    stage: str
    task: LlmTask
    usage: LlmUsage

    @property
    def is_model_call(self) -> bool:
        return self.stage != EMBED_STAGE


@dataclass(slots=True)
class SpendLedger:
    meter: SpendMeter
    records: list[RecordedCall] = field(default_factory=list[RecordedCall])
    seen: set[str] = field(default_factory=set[str])

    async def record(self, context: CallContext, task: LlmTask, usage: LlmUsage) -> None:
        if context.call_key in self.seen:
            return
        self.seen.add(context.call_key)
        synthetic = usage.provider in SYNTHETIC_PROVIDERS
        priced = LlmUsage(
            provider=usage.provider,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            cost_micros_usd=synthetic_cost_micros(task, usage) if synthetic else usage.cost_micros_usd,
        )
        self.records.append(RecordedCall(context.job_id, context.stage, task, priced))
        if not synthetic:
            self.meter.add(priced.cost_micros_usd)

    async def tokens_used(self, job_id: UUID) -> int:
        return sum(record.usage.total_tokens for record in self.records if record.job_id == job_id)

    def calls_for(self, job_id: UUID) -> list[RecordedCall]:
        return [record for record in self.records if record.job_id == job_id and record.is_model_call]

    def tokens_for(self, job_id: UUID) -> int:
        return sum(record.usage.total_tokens for record in self.records if record.job_id == job_id)

    def cost_for(self, job_id: UUID) -> int:
        return sum(record.usage.cost_micros_usd for record in self.records if record.job_id == job_id)

    @property
    def live_cost_micros(self) -> int:
        return sum(
            record.usage.cost_micros_usd for record in self.records if record.usage.provider not in SYNTHETIC_PROVIDERS
        )


class MeteredLlm:
    def __init__(self, inner: LlmClient, meter: SpendMeter) -> None:
        self._inner = inner
        self._meter = meter

    async def generate[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]:
        self._meter.ensure_available()
        result = await self._inner.generate(call, output)
        self._meter.ensure_available()
        return result
