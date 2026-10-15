import base64

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.resources import Resources
from motionile.core.tasks.registry import defer_after_commit
from motionile.modules.notifications.schemas import Notification
from motionile.modules.notifications.tasks import deliver_notification

NOTIFICATION_AAD = b"motionile.notification.v1"


def enqueue_notification(resources: Resources, session: AsyncSession, message: Notification) -> None:
    encrypted = resources.key_ring.encrypt(message.model_dump_json().encode(), associated_data=NOTIFICATION_AAD)
    defer_after_commit(
        session,
        deliver_notification,
        priority=10 if message.code else 0,
        ciphertext=base64.b64encode(encrypted.ciphertext).decode(),
        nonce=base64.b64encode(encrypted.nonce).decode(),
        key_version=encrypted.key_version,
    )
