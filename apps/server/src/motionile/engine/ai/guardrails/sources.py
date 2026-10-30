from typing import Protocol

from motionile.engine.ai.ports import ActivePrompt


class ActivePromptSource(Protocol):
    async def active(self, key: str) -> ActivePrompt: ...
