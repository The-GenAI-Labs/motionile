from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
}
NO_STORE = "no-store"
HEADERS_TO_STRIP = ("server", "x-powered-by")


def security_headers(*, hsts_max_age_seconds: int) -> dict[str, str]:
    headers = dict(BASE_SECURITY_HEADERS)
    if hsts_max_age_seconds > 0:
        headers["Strict-Transport-Security"] = f"max-age={hsts_max_age_seconds}; includeSubDomains"
    return headers


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts_max_age_seconds: int = 0) -> None:
        self.app = app
        self.headers = security_headers(hsts_max_age_seconds=hsts_max_age_seconds)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name in HEADERS_TO_STRIP:
                    if name in headers:
                        del headers[name]
                for name, value in self.headers.items():
                    headers.setdefault(name, value)
                headers.setdefault("Cache-Control", NO_STORE)
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
