from collections.abc import Sequence
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.engine.ai.ports import ActivePrompt
from motionile.modules.prompts.exceptions import PromptTemplateNotFoundError, PromptVersionNotFoundError
from motionile.modules.prompts.repository import SqlPromptRepository, StoreFactory


async def prompts_under_evaluation(
    session: AsyncSession, version_ids: Sequence[UUID], *, store_factory: StoreFactory = SqlPromptRepository
) -> list[ActivePrompt]:
    repository = store_factory(session)
    wanted = list(dict.fromkeys(version_ids))
    versions = await repository.versions_by_ids(wanted)
    if len(versions) != len(wanted):
        raise PromptVersionNotFoundError
    prompts: list[ActivePrompt] = []
    for version in versions:
        template = await repository.template_by_id(version.template_id)
        if template is None:
            raise PromptTemplateNotFoundError
        prompts.append(
            ActivePrompt(
                key=template.key,
                version_id=version.id,
                version=version.version,
                body=version.body,
                canary=version.canary,
                variables=tuple(version.variables),
            )
        )
    return prompts
