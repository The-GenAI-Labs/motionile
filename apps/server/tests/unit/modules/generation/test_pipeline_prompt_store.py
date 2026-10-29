from uuid import uuid4

import pytest

from motionile.engine.ai.graphs.errors import PipelineError
from motionile.engine.ai.ports import ActivePrompt
from motionile.modules.generation.pipeline_deps import PROMPT_NOT_ACTIVE, PipelinePromptStore
from motionile.modules.prompts import PromptNotActiveError


class MissingPrompts:
    async def active(self, key: str) -> ActivePrompt:
        raise PromptNotActiveError(key)

    async def all_active(self) -> list[ActivePrompt]:
        return []


class FixedPrompts:
    def __init__(self, prompt: ActivePrompt) -> None:
        self.prompt = prompt

    async def active(self, key: str) -> ActivePrompt:
        del key
        return self.prompt

    async def all_active(self) -> list[ActivePrompt]:
        return [self.prompt]


async def test_a_template_without_an_active_version_fails_the_job_with_a_stable_code() -> None:
    store = PipelinePromptStore(MissingPrompts())

    with pytest.raises(PipelineError) as raised:
        await store.active("planner.storyboard")

    assert raised.value.code == PROMPT_NOT_ACTIVE
    assert "planner.storyboard" not in raised.value.message


async def test_an_active_prompt_passes_through_unchanged() -> None:
    prompt = ActivePrompt("guard.input", uuid4(), 1, "body", "canary", ("canary",))

    store = PipelinePromptStore(FixedPrompts(prompt))

    assert await store.active("guard.input") is prompt
    assert await store.all_active() == [prompt]
