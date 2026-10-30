from collections.abc import Mapping
from typing import Final
from uuid import UUID, uuid5

from motionile.engine.ai.ports import ActivePrompt, PromptStore
from motionile.engine.ai.prompts import PromptSource, load_prompt_sources

PROMPT_NAMESPACE: Final = UUID("0f4c1f0e-7a0e-4f4e-8a3c-6a5d2c1b9e10")
CANARY_PREFIX: Final = "mo-canary-eval-"
CANARY_DIGEST_CHARS: Final = 16


def active_prompt_of(source: PromptSource) -> ActivePrompt:
    digest = source.checksum.hex()
    return ActivePrompt(
        key=source.key,
        version_id=uuid5(PROMPT_NAMESPACE, f"{source.key}:{digest}"),
        version=source.version,
        body=source.body,
        canary=f"{CANARY_PREFIX}{digest[:CANARY_DIGEST_CHARS]}",
        variables=source.variables,
    )


class FilePromptStore:
    def __init__(self) -> None:
        self._prompts = {source.key: active_prompt_of(source) for source in load_prompt_sources()}

    async def active(self, key: str) -> ActivePrompt:
        return self._prompts[key]

    async def all_active(self) -> list[ActivePrompt]:
        return list(self._prompts.values())


class OverridingPromptStore:
    def __init__(self, base: PromptStore, overrides: Mapping[str, ActivePrompt]) -> None:
        self._base = base
        self._overrides = dict(overrides)

    async def active(self, key: str) -> ActivePrompt:
        override = self._overrides.get(key)
        return override if override is not None else await self._base.active(key)

    async def all_active(self) -> list[ActivePrompt]:
        base = await self._base.all_active()
        return [self._overrides.get(prompt.key, prompt) for prompt in base]

    @property
    def version_ids(self) -> list[UUID]:
        return [prompt.version_id for prompt in self._overrides.values()]
