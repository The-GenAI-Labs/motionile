import math
from collections.abc import Sequence
from dataclasses import replace

from motionile.engine.ai.llm.config import BudgetProvider
from motionile.engine.ai.llm.models import (
    BudgetExceededError,
    CallContext,
    ImageBlock,
    LlmUsage,
    UsageLedger,
    UserBlock,
)

CHARS_PER_TOKEN = 3
DEFAULT_IMAGE_TOKENS = 1_600


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def estimate_blocks_tokens(
    system_blocks: Sequence[str], user_blocks: Sequence[UserBlock], image_tokens: int = DEFAULT_IMAGE_TOKENS
) -> int:
    total = sum(estimate_tokens(block) for block in system_blocks)
    for block in user_blocks:
        if isinstance(block, ImageBlock):
            total += image_tokens + estimate_tokens(block.label)
        else:
            total += estimate_tokens(block)
    return total


def usage_context(context: CallContext, model: str, round_index: int) -> CallContext:
    return replace(context, call_key=f"{context.call_key}:{round_index}:{model}")


def combine_usage(first: LlmUsage, second: LlmUsage) -> LlmUsage:
    return LlmUsage(
        provider=second.provider,
        model=second.model,
        input_tokens=first.input_tokens + second.input_tokens,
        output_tokens=first.output_tokens + second.output_tokens,
        cached_input_tokens=first.cached_input_tokens + second.cached_input_tokens,
        cost_micros_usd=first.cost_micros_usd + second.cost_micros_usd,
    )


class BudgetGuard:
    def __init__(self, ledger: UsageLedger, budget: BudgetProvider) -> None:
        self._ledger = ledger
        self._budget = budget

    async def ensure(self, context: CallContext, *, input_tokens: int, max_output_tokens: int) -> None:
        if context.job_id is None:
            return
        limit = await self._budget.job_token_budget()
        used = await self._ledger.tokens_used(context.job_id)
        if used + input_tokens + max_output_tokens > limit:
            raise BudgetExceededError("the job token budget would be exceeded by this call")
