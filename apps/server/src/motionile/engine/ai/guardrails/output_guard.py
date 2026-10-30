from collections.abc import Iterator
from typing import Final

import structlog

from motionile.engine.ai.guardrails.decision import GuardDecision, GuardResult
from motionile.engine.ai.guardrails.input_guard import log_refusal
from motionile.engine.ai.guardrails.personal_data import contains_personal_data
from motionile.engine.ai.guardrails.policy import PolicyCode
from motionile.engine.ai.guardrails.sources import ActivePromptSource
from motionile.engine.ai.llm.models import CallContext, LlmCall, LlmClient, LlmTask, OutputBlockedError
from motionile.engine.ai.prompts.canary import OutputScanner
from motionile.engine.ai.prompts.delimit import delimit
from motionile.engine.ai.prompts.render import render_active
from motionile.engine.ai.storyboard import Storyboard, StoryboardScene

GUARD_OUTPUT_KEY: Final = "guard.output"
SCAN_SOURCE: Final = "output_guard"

logger = structlog.get_logger(__name__)


def spoken_and_shown_texts(storyboard: Storyboard) -> Iterator[str]:
    yield storyboard.title
    yield storyboard.summary
    for scene in storyboard.scenes:
        yield scene.narration
        yield from scene.on_screen_text
        yield from scene.key_terms


def internal_texts(storyboard: Storyboard) -> Iterator[str]:
    for scene in storyboard.scenes:
        yield scene.goal
        yield scene.visual_brief
        yield from scene.layout_notes.values()


def render_scene(scene: StoryboardScene) -> str:
    lines = [f"scene: {scene.id}", scene.narration]
    if scene.on_screen_text:
        lines.append("onScreenText:")
        lines.extend(f"- {line}" for line in scene.on_screen_text)
    return "\n".join(lines)


def render_header(storyboard: Storyboard) -> str:
    return "\n".join(
        [
            f"title: {storyboard.title}",
            f"summary: {storyboard.summary}",
            f"language: {storyboard.language}",
            f"audienceLevel: {storyboard.audience_level}",
        ]
    )


class OutputGuard:
    def __init__(self, llm: LlmClient, prompts: ActivePromptSource, scanner: OutputScanner) -> None:
        self._llm = llm
        self._prompts = prompts
        self._scanner = scanner

    async def check_storyboard(self, storyboard: Storyboard, context: CallContext) -> GuardResult:
        if self.deterministic_violation(storyboard):
            log_refusal(PolicyCode.OUTPUT_BLOCKED, context, stage="output_rules")
            return GuardResult.refuse(PolicyCode.OUTPUT_BLOCKED)
        decision = await self.decide(storyboard, context)
        if decision.verdict == "allow":
            return GuardResult.allow()
        log_refusal(PolicyCode.OUTPUT_BLOCKED, context, stage="output_model")
        return GuardResult.refuse(PolicyCode.OUTPUT_BLOCKED)

    def deterministic_violation(self, storyboard: Storyboard) -> bool:
        if any(contains_personal_data(text) for text in spoken_and_shown_texts(storyboard)):
            return True
        try:
            for text in (*spoken_and_shown_texts(storyboard), *internal_texts(storyboard)):
                self._scanner.ensure_clean_text(text, source=SCAN_SOURCE)
        except OutputBlockedError:
            return True
        return False

    async def decide(self, storyboard: Storyboard, context: CallContext) -> GuardDecision:
        prompt = await self._prompts.active(GUARD_OUTPUT_KEY)
        call = LlmCall(
            task=LlmTask.GUARD,
            context=context,
            system_blocks=[render_active(prompt)],
            user_blocks=[
                delimit("context", render_header(storyboard)),
                *(delimit("narration", render_scene(scene)) for scene in storyboard.scenes),
            ],
        )
        result = await self._llm.generate(call, GuardDecision)
        return result.output
