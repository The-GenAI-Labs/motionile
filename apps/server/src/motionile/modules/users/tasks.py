import io
import json
import zipfile
from collections.abc import AsyncIterable
from datetime import timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.config import get_settings
from motionile.core.resources import build_resources
from motionile.core.tasks.registry import Queue, defer_after_commit, task
from motionile.modules.notifications import Notification, enqueue_notification
from motionile.modules.users.events import UserPurged
from motionile.modules.users.exporters import registry
from motionile.modules.users.models import User, UserContact


@task(name="users.export", queue=Queue.DEFAULT)
async def export_user_data(user_id: str) -> None:
    settings = get_settings()
    resources = build_resources(settings, application_name="motionile-user-export")
    try:
        parsed_id = UUID(user_id)
        async with resources.database.transaction() as session:
            data = await registry.export(session, parsed_id)
            contact = await session.scalar(
                select(UserContact)
                .where(
                    UserContact.user_id == parsed_id,
                    UserContact.verified_at.is_not(None),
                    UserContact.is_primary.is_(True),
                )
                .order_by(UserContact.kind)
            )
            if contact is None:
                return
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, value in data.items():
                archive.writestr(f"{name}.json", json.dumps(value, default=str, ensure_ascii=False, indent=2))
        key = f"exports/{user_id}/{resources.clock.now().strftime('%Y%m%dT%H%M%SZ')}.zip"

        async def chunks() -> AsyncIterable[bytes]:
            yield buffer.getvalue()

        await resources.storage.put(key, chunks(), content_type="application/zip")
        link = await resources.storage.presigned_get_url(
            key, expires_in=timedelta(hours=24), download_filename="motionile-data-export.zip"
        )
        async with resources.database.transaction() as session:
            enqueue_notification(
                resources,
                session,
                Notification(
                    destination=str(contact.value),
                    channel="email" if contact.kind == "email" else "whatsapp",
                    template="data_export_ready",
                    link=link,
                ),
            )
    finally:
        await resources.aclose()


def defer_export(session: AsyncSession, user_id: UUID) -> None:
    defer_after_commit(session, export_user_data, user_id=str(user_id))


@task(name="users.purge", queue=Queue.DEFAULT)
async def purge_deleted_users() -> None:
    settings = get_settings()
    resources = build_resources(settings, application_name="motionile-user-purge")
    try:
        threshold = resources.clock.now() - timedelta(days=30)
        async with resources.database.transaction() as session:
            users = list(
                await session.scalars(
                    select(User).where(User.status == "deleted", User.deleted_at <= threshold).with_for_update()
                )
            )
            for user in users:
                await resources.storage.delete_prefix(f"avatars/{user.id}/")
                await resources.storage.delete_prefix(f"exports/{user.id}/")
                await session.delete(user)
                resources.events.publish_after_commit(session, UserPurged(user_id=user.id))
    finally:
        await resources.aclose()
