from typing import Final

import structlog

from motionile.engine.ai.guardrails.decision import GuardDecision, GuardResult
from motionile.engine.ai.guardrails.policy import INPUT_REFUSAL_CODES, PolicyCode
from motionile.engine.ai.guardrails.rules import InputKind, run_input_rules
from motionile.engine.ai.guardrails.sources import ActivePromptSource
from motionile.engine.ai.llm.models import CallContext, LlmCall, LlmClient, LlmTask
from motionile.engine.ai.prompts.delimit import delimit
from motionile.engine.ai.prompts.render import render_active

GUARD_INPUT_KEY: Final = "guard.input"
KIND_TAGS: Final[dict[InputKind, str]] = {
    "query": "user_query",
    "storyboard_edit": "storyboard_edit",
    "instructions": "revision_instructions",
}

logger = structlog.get_logger(__name__)


def log_refusal(code: PolicyCode, context: CallContext, *, stage: str) -> None:
    logger.info(
        "ai.guard_refused",
        stage=stage,
        code=code.value,
        job_id=str(context.job_id) if context.job_id is not None else None,
        user_id=str(context.user_id),
    )


def refusal_code(decision: GuardDecision) -> PolicyCode:
    if decision.code is not None and decision.code in INPUT_REFUSAL_CODES:
        return decision.code
    return PolicyCode.UNSUPPORTED_REQUEST


class InputGuard:
    def __init__(self, llm: LlmClient, prompts: ActivePromptSource) -> None:
        self._llm = llm
        self._prompts = prompts

    async def check(self, text: str, context: CallContext, kind: InputKind) -> GuardResult:
        verdict = run_input_rules(text, kind)
        if verdict is not None:
            log_refusal(verdict.code, context, stage="input_rules")
            return GuardResult.refuse(verdict.code)
        decision = await self.decide(text, context, kind)
        if decision.verdict == "allow":
            return GuardResult.allow()
        code = refusal_code(decision)
        log_refusal(code, context, stage="input_model")
        return GuardResult.refuse(code)

    async def decide(self, text: str, context: CallContext, kind: InputKind) -> GuardDecision:
        prompt = await self._prompts.active(GUARD_INPUT_KEY)
        call = LlmCall(
            task=LlmTask.GUARD,
            context=context,
            system_blocks=[render_active(prompt)],
            user_blocks=[delimit(KIND_TAGS[kind], text)],
        )
        result = await self._llm.generate(call, GuardDecision)
        return result.output
