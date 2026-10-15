import base64

from motionile.core.config import get_settings
from motionile.core.resources import build_resources
from motionile.core.security.encryption import EncryptedValue
from motionile.core.tasks.registry import Queue, task
from motionile.modules.notifications.service import Notifications


@task(name="notifications.deliver", queue=Queue.DEFAULT)
async def deliver_notification(ciphertext: str, nonce: str, key_version: int) -> None:
    resources = build_resources(get_settings(), application_name="motionile-notifications")
    try:
        await Notifications(resources).deliver(
            EncryptedValue(
                ciphertext=base64.b64decode(ciphertext), nonce=base64.b64decode(nonce), key_version=key_version
            )
        )
    finally:
        await resources.aclose()
