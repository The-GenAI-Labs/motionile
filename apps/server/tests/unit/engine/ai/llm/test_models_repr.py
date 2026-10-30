from uuid import uuid4

from tests.unit.engine.ai.llm.support import context

from motionile.engine.ai.llm.models import LlmCall, LlmTask
from motionile.engine.ai.ports import LoadedSkill, SkillLayer, SkillSummary

PROMPT_TEXT = "SYSTEM PROMPT BODY canary-xyz"
NARRATION_TEXT = "USER NARRATION TEXT"
BODY_TEXT = "SKILL BODY TEXT"


def test_the_repr_of_a_call_hides_prompts_and_user_text() -> None:
    call = LlmCall(task=LlmTask.PLAN, context=context(), system_blocks=[PROMPT_TEXT], user_blocks=[NARRATION_TEXT])

    shown = repr(call)

    assert PROMPT_TEXT not in shown
    assert NARRATION_TEXT not in shown
    assert "plan" in shown.lower()


def test_the_repr_of_a_loaded_skill_hides_its_body() -> None:
    summary = SkillSummary(slug="a", name="A", description="d", layer=SkillLayer.STYLE, version_id=uuid4())
    skill = LoadedSkill(summary=summary, body=BODY_TEXT, tokens={}, token_count=3)

    assert BODY_TEXT not in repr(skill)
