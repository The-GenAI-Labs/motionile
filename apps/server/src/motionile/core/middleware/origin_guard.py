from collections.abc import Iterable
from http import HTTPStatus
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from motionile.core.errors import ProblemDetails, problem_response, request_id_of

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def origin_of(url: str) -> str | None:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme}://{parts.netloc}".lower()


class OriginGuardMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        allowed_origins: Iterable[str],
        exempt_path_prefixes: Iterable[str] = (),
        require_origin: bool = False,
    ) -> None:
        self.app = app
        self.allowed_origins = frozenset(origin.lower().rstrip("/") for origin in allowed_origins)
        self.exempt_path_prefixes = tuple(exempt_path_prefixes)
        self.require_origin = require_origin

    def is_exempt(self, path: str) -> bool:
        return any(path == prefix or path.startswith(f"{prefix.rstrip('/')}/") for prefix in self.exempt_path_prefixes)

    def request_origin(self, request: Request) -> str | None:
        origin = request.headers.get("origin")
        if origin is not None and origin != "null":
            return origin.lower().rstrip("/")
        if origin == "null":
            return "null"
        referer = request.headers.get("referer")
        return origin_of(referer) if referer else None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") not in UNSAFE_METHODS:
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        if self.is_exempt(request.url.path):
            await self.app(scope, receive, send)
            return
        origin = self.request_origin(request)
        if origin is None and not self.require_origin:
            await self.app(scope, receive, send)
            return
        if origin is not None and origin in self.allowed_origins:
            await self.app(scope, receive, send)
            return
        problem = ProblemDetails(
            status=HTTPStatus.FORBIDDEN,
            code="origin_not_allowed",
            title="Origin not allowed",
            detail="State-changing requests must come from an allowed origin.",
            instance=request.url.path,
            request_id=request_id_of(request),
        )
        response = problem_response(problem)
        await response(scope, receive, send)
