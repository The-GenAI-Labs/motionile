from collections.abc import Awaitable, Callable
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, Request
from fastapi.security import APIKeyCookie

from motionile.core.errors import ForbiddenError, UnauthorizedError
from motionile.core.security.cookies import ACCESS_COOKIE, CSRF_COOKIE, REFRESH_COOKIE, TICKET_COOKIE
from motionile.core.security.rbac import Principal
from motionile.modules.audit import context_from_request
from motionile.modules.auth.runtime import AuthRuntime
from motionile.modules.auth.service import AuthService

COOKIE_SECURITY = APIKeyCookie(name=ACCESS_COOKIE, scheme_name="SessionCookie", auto_error=False)
RefreshTokenDep = Annotated[
    str | None, Depends(APIKeyCookie(name=REFRESH_COOKIE, scheme_name="RefreshCookie", auto_error=False))
]
VerificationTicketDep = Annotated[
    str | None, Depends(APIKeyCookie(name=TICKET_COOKIE, scheme_name="VerificationTicket", auto_error=False))
]

CSRF_EXEMPT_PATHS = frozenset(
    {
        "/v1/auth/register",
        "/v1/auth/login",
        "/v1/auth/verify",
        "/v1/auth/otp/request",
        "/v1/auth/otp/verify",
        "/v1/auth/otp/resend",
        "/v1/auth/password/forgot",
        "/v1/auth/password/reset",
        "/v1/auth/refresh",
    }
)


def get_runtime(request: Request) -> AuthRuntime:
    runtime: object = getattr(request.app.state, "auth_runtime", None)
    if not isinstance(runtime, AuthRuntime):
        raise RuntimeError("Auth runtime is not configured")
    return runtime


AuthRuntimeDep = Annotated[AuthRuntime, Depends(get_runtime)]


async def optional_principal(
    request: Request, runtime: AuthRuntimeDep, cookie: Annotated[str | None, Depends(COOKIE_SECURITY)]
) -> Principal | None:
    if not cookie:
        return None
    principal = await runtime.tokens.verify(cookie)
    request.state.principal = principal
    return principal


OptionalPrincipalDep = Annotated[Principal | None, Depends(optional_principal)]


async def oauth_principal(
    request: Request, runtime: AuthRuntimeDep, cookie: Annotated[str | None, Depends(COOKIE_SECURITY)]
) -> Principal | None:
    try:
        return await optional_principal(request, runtime, cookie)
    except UnauthorizedError:
        return None


OAuthPrincipalDep = Annotated[Principal | None, Depends(oauth_principal)]


async def current_principal(principal: OptionalPrincipalDep) -> Principal:
    if principal is None:
        raise UnauthorizedError(code="unauthenticated")
    return principal


CurrentPrincipalDep = Annotated[Principal, Depends(current_principal)]


def require_roles(*roles: str) -> Callable[..., Awaitable[Principal]]:
    async def check(principal: CurrentPrincipalDep) -> Principal:
        if not principal.roles.intersection(roles):
            raise ForbiddenError(code="role_required")
        return principal

    return check


RequireRolesDep = Annotated[Principal, Depends(require_roles("admin", "super_admin"))]


async def enforce_csrf(request: Request, runtime: AuthRuntimeDep) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("origin")
    if origin is None and request.headers.get("referer"):
        referer = urlsplit(request.headers["referer"])
        origin = f"{referer.scheme}://{referer.netloc}"
    if origin not in runtime.resources.settings.cors.allowed_origins:
        raise ForbiddenError(code="origin_forbidden")
    if request.url.path in CSRF_EXEMPT_PATHS:
        return
    cookie = request.cookies.get(ACCESS_COOKIE)
    if cookie is None:
        raise UnauthorizedError(code="unauthenticated")
    principal = await runtime.tokens.verify(cookie)
    request.state.principal = principal
    if principal.session_id is None:
        raise UnauthorizedError(code="unauthenticated")
    runtime.csrf.verify(principal.session_id, request.cookies.get(CSRF_COOKIE), request.headers.get("X-CSRF-Token"))


def get_auth_service(request: Request, runtime: AuthRuntimeDep) -> AuthService:
    return AuthService(runtime, context_from_request(request))


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def identify_for_rate_limit(request: Request, runtime: AuthRuntimeDep) -> None:
    cookie = request.cookies.get(ACCESS_COOKIE)
    if cookie:
        try:
            request.state.principal = await runtime.tokens.verify(cookie)
        except UnauthorizedError:
            request.state.principal = None
