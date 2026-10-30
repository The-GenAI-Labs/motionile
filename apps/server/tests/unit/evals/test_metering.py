from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel

from evals.errors import EvalBudgetExceededError
from evals.metering import MeteredLlm, SpendLedger, SpendMeter, synthetic_cost_micros
from motionile.engine.ai.guardrails.decision import GuardDecision
from motionile.engine.ai.llm.models import CallContext, LlmCall, LlmResult, LlmTask, LlmUsage


def context(job_id: UUID | None = None, key: str = "k", stage: str = "plan") -> CallContext:
    return CallContext(user_id=uuid4(), job_id=job_id, stage=stage, call_key=key)


class PricedLlm:
    def __init__(self, meter: SpendMeter, cost: int) -> None:
        self._meter = meter
        self._cost = cost
        self.calls = 0

    async def generate[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]:
        del call
        self.calls += 1
        self._meter.add(self._cost)
        usage = LlmUsage("anthropic", "m", 1, 1, 0, self._cost)
        answer = GuardDecision(verdict="allow").model_dump(by_alias=True)
        return LlmResult(output=output.model_validate(answer), usage=usage, attempts=1, fallback_used=False)


def guard_call() -> LlmCall:
    return LlmCall(LlmTask.GUARD, context(), ["s"], ["u"])


def test_synthetic_prices_follow_the_routed_model_tier() -> None:
    usage = LlmUsage("fake", "fake/plan", 1_000_000, 1_000_000, 0, 0)

    assert synthetic_cost_micros(LlmTask.GUARD, usage) == 6_000_000
    assert synthetic_cost_micros(LlmTask.PLAN, usage) == 18_000_000


async def test_fake_usage_is_priced_synthetically_and_never_counts_as_live_spend() -> None:
    meter = SpendMeter(budget_micros=1)
    ledger = SpendLedger(meter)
    job = uuid4()

    await ledger.record(context(job, "a"), LlmTask.GUARD, LlmUsage("fake", "fake/guard", 2_000_000, 0, 0, 0))

    assert ledger.cost_for(job) == 2_000_000
    assert meter.live_micros == 0
    assert ledger.live_cost_micros == 0


async def test_provider_usage_keeps_its_cost_and_counts_as_live_spend() -> None:
    meter = SpendMeter()
    ledger = SpendLedger(meter)
    job = uuid4()

    await ledger.record(context(job, "a"), LlmTask.PLAN, LlmUsage("anthropic", "m", 100, 50, 0, 1234))

    assert meter.live_micros == 1234
    assert ledger.cost_for(job) == 1234
    assert ledger.tokens_for(job) == 150
    assert await ledger.tokens_used(job) == 150


async def test_the_ledger_deduplicates_by_call_key_and_ignores_embedding_calls_in_the_call_count() -> None:
    ledger = SpendLedger(SpendMeter())
    job = uuid4()
    usage = LlmUsage("fake", "fake/plan", 10, 10, 0, 0)

    await ledger.record(context(job, "same"), LlmTask.PLAN, usage)
    await ledger.record(context(job, "same"), LlmTask.PLAN, usage)
    await ledger.record(context(job, "embed-1", "embed"), LlmTask.ROUTE, usage)

    assert len(ledger.records) == 2
    assert len(ledger.calls_for(job)) == 1


async def test_a_runaway_stops_with_eval_budget_exceeded_before_the_next_call() -> None:
    meter = SpendMeter(budget_micros=1_000)
    inner = PricedLlm(meter, 600)
    llm = MeteredLlm(inner, meter)

    await llm.generate(guard_call(), GuardDecision)
    with pytest.raises(EvalBudgetExceededError) as stopped:
        await llm.generate(guard_call(), GuardDecision)

    assert stopped.value.code == "eval_budget_exceeded"
    assert inner.calls == 2


async def test_a_call_that_crosses_the_budget_raises_immediately_and_blocks_the_next_one() -> None:
    meter = SpendMeter(budget_micros=500)
    inner = PricedLlm(meter, 800)
    llm = MeteredLlm(inner, meter)

    with pytest.raises(EvalBudgetExceededError):
        await llm.generate(guard_call(), GuardDecision)
    with pytest.raises(EvalBudgetExceededError):
        await llm.generate(guard_call(), GuardDecision)

    assert inner.calls == 1


async def test_without_a_budget_nothing_is_enforced() -> None:
    meter = SpendMeter()
    llm = MeteredLlm(PricedLlm(meter, 10**9), meter)

    await llm.generate(guard_call(), GuardDecision)
    await llm.generate(guard_call(), GuardDecision)

    assert meter.live_micros == 2 * 10**9
