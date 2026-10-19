import httpx
from starlette.types import ASGIApp

from motionile.modules.billing.razorpay.fake_events import BuiltWebhook

WEBHOOK_PATH = "/v1/webhooks/razorpay"
DELIVERY_BASE_URL = "http://test"


async def deliver_webhook(app: ASGIApp, webhook: BuiltWebhook, *, deliveries: int = 1) -> list[int]:
    statuses: list[int] = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=DELIVERY_BASE_URL) as client:
        for _ in range(deliveries):
            response = await client.post(WEBHOOK_PATH, content=webhook.body, headers=webhook.headers)
            statuses.append(response.status_code)
    return statuses
