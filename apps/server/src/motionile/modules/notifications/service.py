from motionile.core.resources import Resources
from motionile.core.security.encryption import EncryptedValue
from motionile.modules.notifications.providers import (
    EmailSender,
    FakeDelivery,
    FakeEmailSender,
    FakeWhatsAppSender,
    MetaWhatsAppSender,
    SesEmailSender,
    SmtpEmailSender,
    WhatsAppSender,
)
from motionile.modules.notifications.rendering import TEMPLATES, render_email
from motionile.modules.notifications.schemas import Notification

NOTIFICATION_AAD = b"motionile.notification.v1"


class Notifications:
    def __init__(self, resources: Resources) -> None:
        self.resources = resources
        settings = resources.settings
        self.fake = FakeDelivery(resources.redis_store)
        self.email: EmailSender
        self.whatsapp: WhatsAppSender
        if settings.is_fake_providers:
            self.email = FakeEmailSender()
            self.whatsapp = FakeWhatsAppSender()
        else:
            self.email = (
                SesEmailSender(settings.notifications)
                if settings.notifications.email_backend == "ses"
                else SmtpEmailSender(settings.notifications)
            )
            self.whatsapp = MetaWhatsAppSender(settings.notifications, resources.provider_clients["whatsapp"])

    async def deliver(self, encrypted: EncryptedValue) -> None:
        payload = self.resources.key_ring.decrypt(encrypted, associated_data=NOTIFICATION_AAD)
        message = Notification.model_validate_json(payload)
        try:
            if message.channel == "email":
                await self.email.send(message.destination, render_email(message))
            elif message.code is not None:
                await self.whatsapp.send(message.destination, message.code)
            else:
                await self.whatsapp.send_notice(message.destination, TEMPLATES[message.template][1])
            if self.resources.settings.is_fake_providers:
                await self.fake.record(message)
        except Exception:
            raise RuntimeError("Notification delivery failed") from None
