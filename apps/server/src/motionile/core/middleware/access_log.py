import time

import structlog
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = structlog.get_logger("motionile.access")


def route_template(scope: Scope) -> str | None:
    route: object = scope.get("route")
    path: object = getattr(route, "path", None)
    return path if isinstance(path, str) else None


def client_ip(scope: Scope) -> str | None:
    client = Request(scope).client
    return client.host if client is not None else None


class AccessLogMiddleware:
    def __init__(self, app: ASGIApp, *, enabled: bool = True) -> None:
        self.app = app
        self.enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status_code = 500

        async def send_capturing_status(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, receive, send_capturing_status)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "http.request",
                method=scope.get("method"),
                path=scope.get("path"),
                route=route_template(scope),
                status=status_code,
                duration_ms=duration_ms,
                client_ip=client_ip(scope),
            )
