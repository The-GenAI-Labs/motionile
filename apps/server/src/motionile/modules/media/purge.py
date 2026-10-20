from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.resources import Resources
from motionile.modules.media.keys import render_work_prefix, user_media_prefix, user_voice_prefix
from motionile.modules.media.repository import SqlRenderRepository
from motionile.modules.users import purge_registry

PURGE_HOOK_NAME = "media"


async def purge_media(resources: Resources, session: AsyncSession, user_id: UUID) -> None:
    render_ids = await SqlRenderRepository(session).render_ids_of(user_id)
    await resources.storage.delete_prefix(user_media_prefix(user_id))
    for render_id in render_ids:
        await resources.storage.delete_prefix(render_work_prefix(render_id))
    await resources.storage.delete_prefix(user_voice_prefix(user_id))


purge_registry.register(PURGE_HOOK_NAME, purge_media)
