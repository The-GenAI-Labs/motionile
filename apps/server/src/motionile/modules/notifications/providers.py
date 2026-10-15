import asyncio
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from http import HTTPStatus
from typing import Protocol

import boto3
import orjson

from motionile.core.config import NotificationSettings
from motionile.core.http.safe_client import SafeHttpClient
from motionile.core.redis import RedisStore
from motionile.core.security.tokens import token_hash
from motionile.modules.notifications.schemas import Notification, RenderedEmail


class EmailSender(Protocol):
    async def send(self, destination: str, message: RenderedEmail) -> None: ...


class WhatsAppSender(Protocol):
    async def send(self, destination: str, code: str) -> None: ...
    async def send_notice(self, destination: str, message: str) -> None: ...


class SmtpEmailSender:
    def __init__(self, settings: NotificationSettings) -> None:
        self.settings = settings

    def _send(self, destination: str, rendered: RenderedEmail) -> None:
        message = EmailMessage()
        message["From"] = self.settings.sender
        message["To"] = destination
        message["Subject"] = rendered.subject
        message.set_content(rendered.text)
        message.add_alternative(rendered.html, subtype="html")
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as client:
            if self.settings.smtp_starttls:
                client.starttls(context=ssl.create_default_context())
            if self.settings.smtp_username and self.settings.smtp_password:
                client.login(self.settings.smtp_username, self.settings.smtp_password.get_secret_value())
            client.send_message(message)

    async def send(self, destination: str, message: RenderedEmail) -> None:
        await asyncio.to_thread(self._send, destination, message)


class SesEmailSender:
    def __init__(self, settings: NotificationSettings) -> None:
        self.settings = settings
        self.client = boto3.client("sesv2", region_name=settings.ses_region)

    async def send(self, destination: str, message: RenderedEmail) -> None:
        await asyncio.to_thread(
            self.client.send_email,
            FromEmailAddress=self.settings.sender,
            Destination={"ToAddresses": [destination]},
            **(
                {"ConfigurationSetName": self.settings.ses_configuration_set}
                if self.settings.ses_configuration_set
                else {}
            ),
            Content={
                "Simple": {
                    "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                    "Body": {
                        "Text": {"Data": message.text, "Charset": "UTF-8"},
                        "Html": {"Data": message.html, "Charset": "UTF-8"},
                    },
                }
            },
        )


class MetaWhatsAppSender:
    def __init__(self, settings: NotificationSettings, client: SafeHttpClient) -> None:
        self.settings = settings
        self.client = client

    async def send(self, destination: str, code: str) -> None:
        secret = self.settings.whatsapp_token
        if secret is None:
            raise RuntimeError("WhatsApp is not configured")
        payload = {
            "messaging_product": "whatsapp",
            "to": destination.lstrip("+"),
            "type": "template",
            "template": {
                "name": self.settings.whatsapp_template,
                "language": {"code": self.settings.whatsapp_language},
                "components": [
                    {"type": "body", "parameters": [{"type": "text", "text": code}]},
                    {"type": "button", "sub_type": "url", "index": "0", "parameters": [{"type": "text", "text": code}]},
                ],
            },
        }
        response = await self.client.request(
            "POST",
            f"https://graph.facebook.com/{self.settings.whatsapp_api_version}/{self.settings.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {secret.get_secret_value()}", "Content-Type": "application/json"},
            content=orjson.dumps(payload),
        )
        if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
            raise RuntimeError("WhatsApp delivery failed")

    async def send_notice(self, destination: str, message: str) -> None:
        secret = self.settings.whatsapp_token
        if secret is None:
            raise RuntimeError("WhatsApp is not configured")
        payload = {
            "messaging_product": "whatsapp",
            "to": destination.lstrip("+"),
            "type": "template",
            "template": {
                "name": self.settings.whatsapp_notice_template,
                "language": {"code": self.settings.whatsapp_language},
                "components": [{"type": "body", "parameters": [{"type": "text", "text": message}]}],
            },
        }
        response = await self.client.request(
            "POST",
            f"https://graph.facebook.com/{self.settings.whatsapp_api_version}/{self.settings.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {secret.get_secret_value()}", "Content-Type": "application/json"},
            content=orjson.dumps(payload),
        )
        if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
            raise RuntimeError("WhatsApp delivery failed")


class FakeDelivery:
    def __init__(self, store: RedisStore) -> None:
        self.store = store
        self.messages: list[Notification] = []

    def inbox_key(self, destination: str) -> str:
        return self.store.keys.key("test.inbox", token_hash(destination.casefold()).hex())

    async def record(self, notification: Notification) -> None:
        self.messages.append(notification)
        key = self.inbox_key(notification.destination)
        async with self.store.client.pipeline(transaction=True) as pipeline:
            pipeline.lpush(key, notification.model_dump_json())
            pipeline.ltrim(key, 0, 19)
            pipeline.expire(key, int(timedelta(hours=1).total_seconds()))
            await pipeline.execute()

    async def inbox(self, destination: str) -> list[Notification]:
        entries = await self.store.client.lrange(self.inbox_key(destination), 0, 19)
        return [Notification.model_validate_json(entry) for entry in entries]


class FakeEmailSender:
    def __init__(self) -> None:
        self.messages: list[tuple[str, RenderedEmail]] = []

    async def send(self, destination: str, message: RenderedEmail) -> None:
        self.messages.append((destination, message))


class FakeWhatsAppSender:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send(self, destination: str, code: str) -> None:
        self.messages.append((destination, code))

    async def send_notice(self, destination: str, message: str) -> None:
        self.messages.append((destination, message))
