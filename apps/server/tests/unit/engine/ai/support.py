from collections.abc import Sequence
from uuid import UUID, uuid4

from pydantic import BaseModel

from motionile.engine.ai.llm.models import CallContext, LlmCall, LlmResult, LlmUsage
from motionile.engine.ai.ports import ActivePrompt
from motionile.engine.ai.prompts import PromptSource, load_prompt_sources, new_canary
from motionile.engine.ai.storyboard import Storyboard, StoryboardScene

USAGE = LlmUsage(
    provider="stub", model="stub", input_tokens=1, output_tokens=1, cached_input_tokens=0, cost_micros_usd=0
)


class ScriptedClient:
    def __init__(self, *script: BaseModel | Exception) -> None:
        self._script = list(script)
        self.calls: list[LlmCall] = []

    async def generate[OutputT: BaseModel](self, call: LlmCall, output: type[OutputT]) -> LlmResult[OutputT]:
        self.calls.append(call)
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        if not isinstance(item, output):
            raise TypeError("the scripted output does not match the requested model")
        return LlmResult(output=item, usage=USAGE, attempts=1, fallback_used=False)


def active_prompt_from(source: PromptSource) -> ActivePrompt:
    return ActivePrompt(
        key=source.key,
        version_id=uuid4(),
        version=source.version,
        body=source.body,
        canary=new_canary(),
        variables=source.variables,
    )


class StaticPrompts:
    def __init__(self) -> None:
        self.prompts = {source.key: active_prompt_from(source) for source in load_prompt_sources()}
        self.requested: list[str] = []

    async def active(self, key: str) -> ActivePrompt:
        self.requested.append(key)
        return self.prompts[key]

    async def all_active(self) -> list[ActivePrompt]:
        return list(self.prompts.values())


def call_context(job_id: UUID | None = None) -> CallContext:
    return CallContext(user_id=uuid4(), job_id=job_id or uuid4(), stage="guard", call_key="guard-1")


def scene(
    identifier: str,
    position: int,
    narration: str,
    on_screen_text: Sequence[str] = (),
    visual_brief: str = "Show a simple labeled diagram.",
) -> StoryboardScene:
    return StoryboardScene(
        id=identifier,
        position=position,
        goal="Understand the idea.",
        narration=narration,
        visual_brief=visual_brief,
        layout_notes={"16:9": "Side by side.", "9:16": "Stacked."},
        on_screen_text=list(on_screen_text),
        target_duration_ms=10_000,
    )


def storyboard(*scenes: StoryboardScene, title: str = "How a request travels") -> Storyboard:
    return Storyboard(
        title=title,
        summary="A request goes from a browser to a server and back.",
        audience_level="beginner",
        language="en",
        target_duration_ms=20_000,
        aspects=["16:9", "9:16"],
        style_skill="minimal-dark",
        scenes=list(scenes),
    )


def clean_storyboard() -> Storyboard:
    return storyboard(
        scene(
            "hook",
            0,
            "Every time you open a website a small conversation happens between your browser and a faraway server.",
            ["Browser", "Server"],
        ),
        scene(
            "recap",
            1,
            "The browser asks, the server answers, and the page appears in front of you within a blink.",
            ["Ask", "Answer"],
        ),
    )
