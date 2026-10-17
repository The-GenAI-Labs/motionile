from json import JSONDecodeError
from typing import Annotated, cast
from uuid import UUID

import httpx
import jwt
from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.params import Depends as Dependency
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from motionile.core.bot.turnstile import require_turnstile
from motionile.core.errors import AppError, ProblemDetails, problem_responses
from motionile.core.http.safe_client import OutboundRequestBlockedError, ResponseTooLargeError
from motionile.core.ratelimit.limiter import rate_limit
from motionile.core.security.cookies import CSRF_COOKIE, OAUTH_COOKIE, TICKET_COOKIE, CookieManager
from motionile.core.security.identifiers import normalize_identifier
from motionile.modules.auth.contracts import protection
from motionile.modules.auth.dependencies import (
    AuthRuntimeDep,
    AuthServiceDep,
    CurrentPrincipalDep,
    OAuthPrincipalDep,
    RefreshTokenDep,
    VerificationTicketDep,
    enforce_csrf,
)
from motionile.modules.auth.exceptions import VerificationProblem
from motionile.modules.auth.oauth.providers import ProviderName
from motionile.modules.auth.oauth.service import OAuthService
from motionile.modules.auth.routes import AuthRoute
from motionile.modules.auth.schemas import (
    ChallengeResponse,
    ChangePasswordRequest,
    CodeRequest,
    IdentifierRequest,
    JwksResponse,
    LoginRequest,
    OAuthCallbackQuery,
    OAuthStartQuery,
    OAuthStartResponse,
    RegisterRequest,
    ResetPasswordRequest,
    SessionListQuery,
    SessionsResponse,
    SessionUser,
)


async def request_identifier(request: Request) -> str | None:
    try:
        body: object = await request.json()
    except JSONDecodeError:
        return None
    if not isinstance(body, dict):
        return None
    fields = cast("dict[str, object]", body)
    value = fields.get("identifier") or fields.get("email") or fields.get("phone")
    return normalize_identifier(value).value if isinstance(value, str) else None


async def ticket_identifier(request: Request) -> str | None:
    return request.cookies.get(TICKET_COOKIE)


auth_router = APIRouter(
    prefix="/auth",
    route_class=AuthRoute,
    tags=["auth"],
    dependencies=[Depends(enforce_csrf)],
    responses=problem_responses(400, 401, 403, 409, 422, 429, 503),
)


def policies(
    policy: str, *, turnstile: str | None = None, identifier: bool = False, ticket: bool = False
) -> list[Dependency]:
    resolver = request_identifier if identifier else ticket_identifier if ticket else None
    result = [] if policy in {"auth.otp.send", "auth.refresh"} else [Depends(rate_limit(policy, identifier=resolver))]
    if turnstile:
        result.append(Depends(require_turnstile(turnstile)))
    return result


def cookie_manager(runtime: AuthRuntimeDep) -> CookieManager:
    return CookieManager(runtime.resources.settings.auth.cookie_domain)


CookieManagerDep = Annotated[CookieManager, Depends(cookie_manager)]


@auth_router.post(
    "/register",
    response_model=ChallengeResponse,
    status_code=202,
    summary="Request registration verification",
    dependencies=policies("auth.register", turnstile="register", identifier=True),
    openapi_extra=protection(
        "auth.register",
        csrf="origin",
        errors={422: ["invalid_identifier", "password_breached", "password_policy"]},
        turnstile="register",
        cookie=None,
    ),
)
async def register(
    body: RegisterRequest, response: Response, service: AuthServiceDep, cookies: CookieManagerDep
) -> ChallengeResponse:
    ticket, result = await service.register(
        body.name, normalize_identifier(body.email or body.phone or ""), body.password.get_secret_value()
    )
    cookies.set_ticket(response, ticket)
    return result


@auth_router.post(
    "/verify",
    response_model=SessionUser,
    status_code=200,
    summary="Verify a registration contact",
    dependencies=policies("auth.otp.verify", ticket=True),
    openapi_extra=protection(
        "auth.otp.verify",
        csrf="origin",
        errors={401: ["invalid_challenge"], 409: ["verification_conflict"]},
        turnstile=None,
        cookie="__Secure-mo_vt",
    ),
)
async def verify(
    body: CodeRequest,
    ticket: VerificationTicketDep,
    response: Response,
    service: AuthServiceDep,
    cookies: CookieManagerDep,
) -> SessionUser:
    result, tokens = await service.verify_contact(ticket, body.code)
    cookies.set_session(response, tokens)
    return result


@auth_router.post(
    "/login",
    response_model=SessionUser,
    status_code=200,
    summary="Sign in with a password",
    dependencies=policies("auth.login", turnstile="login", identifier=True),
    openapi_extra=protection(
        "auth.login",
        csrf="origin",
        errors={401: ["invalid_credentials"], 403: ["verification_required", "account_suspended"]},
        turnstile="login",
        cookie=None,
    ),
    responses={
        403: {
            "model": VerificationProblem | ProblemDetails,
            "description": "verification_required (with challenge) or account_suspended",
        }
    },
)
async def login(
    body: LoginRequest, response: Response, service: AuthServiceDep, cookies: CookieManagerDep
) -> SessionUser:
    result, tokens = await service.password_login(
        normalize_identifier(body.identifier), body.password.get_secret_value()
    )
    cookies.set_session(response, tokens)
    return result


@auth_router.post(
    "/otp/request",
    response_model=ChallengeResponse,
    status_code=202,
    summary="Request a sign-in code",
    dependencies=policies("auth.otp.send", turnstile="otp_request", identifier=True),
    openapi_extra=protection("auth.otp.send", csrf="origin", errors={}, turnstile="otp_request", cookie=None),
)
async def request_otp(
    body: IdentifierRequest, response: Response, service: AuthServiceDep, cookies: CookieManagerDep
) -> ChallengeResponse:
    ticket, result = await service.request_otp(normalize_identifier(body.identifier), "login")
    cookies.set_ticket(response, ticket)
    return result


@auth_router.post(
    "/otp/verify",
    response_model=SessionUser,
    status_code=200,
    summary="Sign in with a code",
    dependencies=policies("auth.otp.verify", ticket=True),
    openapi_extra=protection(
        "auth.otp.verify",
        csrf="origin",
        errors={401: ["invalid_challenge", "invalid_credentials"], 403: ["account_suspended"]},
        turnstile=None,
        cookie="__Secure-mo_vt",
    ),
)
async def verify_otp(
    body: CodeRequest,
    ticket: VerificationTicketDep,
    response: Response,
    service: AuthServiceDep,
    cookies: CookieManagerDep,
) -> SessionUser:
    result, tokens = await service.otp_login(ticket, body.code)
    cookies.set_session(response, tokens)
    return result


@auth_router.post(
    "/otp/resend",
    response_model=ChallengeResponse,
    status_code=202,
    summary="Resend the current code",
    dependencies=policies("auth.otp.send", ticket=True),
    openapi_extra=protection(
        "auth.otp.send", csrf="origin", errors={401: ["invalid_challenge"]}, turnstile=None, cookie="__Secure-mo_vt"
    ),
)
async def resend_otp(
    ticket: VerificationTicketDep, response: Response, service: AuthServiceDep, cookies: CookieManagerDep
) -> ChallengeResponse:
    ticket, result = await service.resend(ticket)
    cookies.set_ticket(response, ticket)
    return result


@auth_router.post(
    "/refresh",
    response_model=None,
    status_code=204,
    summary="Rotate the current refresh token",
    dependencies=policies("auth.refresh"),
    openapi_extra=protection(
        "auth.refresh",
        csrf="refresh",
        errors={
            401: ["unauthenticated", "refresh_conflict", "refresh_reused", "session_expired"],
            403: ["account_suspended"],
        },
        turnstile=None,
        cookie="__Secure-mo_rt",
    ),
)
async def refresh(
    request: Request,
    refresh_token: RefreshTokenDep,
    response: Response,
    service: AuthServiceDep,
    cookies: CookieManagerDep,
) -> None:
    tokens = await service.refresh(refresh_token, request.cookies.get(CSRF_COOKIE), request.headers.get("X-CSRF-Token"))
    cookies.set_session(response, tokens)


@auth_router.post(
    "/logout",
    response_model=None,
    status_code=204,
    summary="Revoke the current session family",
    dependencies=policies("api.default"),
    openapi_extra=protection(
        "api.default",
        csrf="session",
        errors={401: ["unauthenticated", "token_expired"]},
        turnstile=None,
        cookie="__Secure-mo_at",
    ),
)
async def logout(
    response: Response, principal: CurrentPrincipalDep, service: AuthServiceDep, cookies: CookieManagerDep
) -> None:
    await service.logout(principal)
    cookies.clear(response)


@auth_router.post(
    "/logout-all",
    response_model=None,
    status_code=204,
    summary="Revoke every session family",
    dependencies=policies("api.default"),
    openapi_extra=protection(
        "api.default",
        csrf="session",
        errors={401: ["unauthenticated", "token_expired"]},
        turnstile=None,
        cookie="__Secure-mo_at",
    ),
)
async def logout_all(
    response: Response, principal: CurrentPrincipalDep, service: AuthServiceDep, cookies: CookieManagerDep
) -> None:
    await service.logout(principal, everywhere=True)
    cookies.clear(response)


@auth_router.get(
    "/me",
    response_model=SessionUser,
    status_code=200,
    summary="Read the signed-in user",
    dependencies=policies("api.default"),
    openapi_extra=protection(
        "api.default",
        csrf="none",
        errors={401: ["unauthenticated", "token_expired"]},
        turnstile=None,
        cookie="__Secure-mo_at",
    ),
)
async def me(principal: CurrentPrincipalDep, service: AuthServiceDep) -> SessionUser:
    return await service.me(principal)


@auth_router.get(
    "/sessions",
    response_model=SessionsResponse,
    status_code=200,
    summary="List active session families",
    dependencies=policies("api.default"),
    openapi_extra=protection(
        "api.default",
        csrf="none",
        errors={422: ["invalid_cursor"], 401: ["unauthenticated", "token_expired"]},
        turnstile=None,
        cookie="__Secure-mo_at",
    ),
)
async def sessions(
    principal: CurrentPrincipalDep, service: AuthServiceDep, query: Annotated[SessionListQuery, Query()]
) -> SessionsResponse:
    return await service.sessions(principal, query)


@auth_router.delete(
    "/sessions/{sessionId}",
    response_model=None,
    status_code=204,
    summary="Revoke an owned session family",
    dependencies=policies("api.default"),
    openapi_extra=protection(
        "api.default",
        csrf="session",
        errors={401: ["unauthenticated", "token_expired"], 404: ["not_found"]},
        turnstile=None,
        cookie="__Secure-mo_at",
    ),
)
async def revoke_session(
    session_id: Annotated[UUID, Path(alias="sessionId")],
    principal: CurrentPrincipalDep,
    service: AuthServiceDep,
    response: Response,
    cookies: CookieManagerDep,
) -> None:
    await service.logout(principal, family_id=session_id)
    if session_id == principal.session_id:
        cookies.clear(response)


@auth_router.post(
    "/password/forgot",
    response_model=ChallengeResponse,
    status_code=202,
    summary="Request a password reset code",
    dependencies=policies("auth.otp.send", turnstile="password_forgot", identifier=True),
    openapi_extra=protection("auth.otp.send", csrf="origin", errors={}, turnstile="password_forgot", cookie=None),
)
async def forgot_password(
    body: IdentifierRequest, response: Response, service: AuthServiceDep, cookies: CookieManagerDep
) -> ChallengeResponse:
    ticket, result = await service.request_otp(normalize_identifier(body.identifier), "password_reset")
    cookies.set_ticket(response, ticket)
    return result


@auth_router.post(
    "/password/reset",
    response_model=None,
    status_code=204,
    summary="Reset a password using a code",
    dependencies=policies("auth.otp.verify", ticket=True),
    openapi_extra=protection(
        "auth.otp.verify",
        csrf="origin",
        errors={401: ["invalid_challenge"], 422: ["password_breached", "password_policy"]},
        turnstile=None,
        cookie="__Secure-mo_vt",
    ),
)
async def reset_password(
    body: ResetPasswordRequest,
    ticket: VerificationTicketDep,
    response: Response,
    service: AuthServiceDep,
    cookies: CookieManagerDep,
) -> None:
    await service.reset_password(ticket, body.code, body.new_password.get_secret_value())
    cookies.clear(response)


@auth_router.post(
    "/password/change",
    response_model=None,
    status_code=204,
    summary="Change a password and revoke other sessions",
    dependencies=policies("auth.password.change"),
    openapi_extra=protection(
        "auth.password.change",
        csrf="session",
        errors={
            401: ["invalid_credentials", "unauthenticated", "token_expired"],
            422: ["password_breached", "password_policy"],
        },
        turnstile=None,
        cookie="__Secure-mo_at",
    ),
)
async def change_password(body: ChangePasswordRequest, principal: CurrentPrincipalDep, service: AuthServiceDep) -> None:
    await service.change_password(
        principal, body.current_password.get_secret_value(), body.new_password.get_secret_value()
    )


@auth_router.post(
    "/password/set/request",
    response_model=ChallengeResponse,
    status_code=202,
    summary="Request a code to add a password",
    dependencies=policies("auth.otp.send"),
    openapi_extra=protection(
        "auth.otp.send",
        csrf="session",
        errors={401: ["unauthenticated", "token_expired"], 409: ["password_already_set", "verified_contact_required"]},
        turnstile=None,
        cookie="__Secure-mo_at",
    ),
)
async def request_password(
    principal: CurrentPrincipalDep, response: Response, service: AuthServiceDep, cookies: CookieManagerDep
) -> ChallengeResponse:
    ticket, result = await service.request_password(principal)
    cookies.set_ticket(response, ticket)
    return result


@auth_router.post(
    "/password/set",
    response_model=None,
    status_code=204,
    summary="Set the first password using a code",
    dependencies=policies("auth.otp.verify", ticket=True),
    openapi_extra=protection(
        "auth.otp.verify",
        csrf="session",
        errors={
            401: ["invalid_challenge", "unauthenticated", "token_expired"],
            409: ["password_already_set"],
            422: ["password_breached", "password_policy"],
        },
        turnstile=None,
        cookie="__Secure-mo_at",
    ),
)
async def set_password(
    body: ResetPasswordRequest,
    ticket: VerificationTicketDep,
    response: Response,
    principal: CurrentPrincipalDep,
    service: AuthServiceDep,
) -> None:
    cookies = CookieManager(service.resources.settings.auth.cookie_domain)
    await service.reset_password(ticket, body.code, body.new_password.get_secret_value(), principal)
    cookies.clear_ticket(response)


@auth_router.get(
    "/jwks.json",
    response_model=JwksResponse,
    status_code=200,
    summary="Publish active access-token verification keys",
    dependencies=policies("api.default"),
    openapi_extra=protection("api.default", csrf="none", errors={}, turnstile=None, cookie=None),
)
async def jwks(response: Response, runtime: AuthRuntimeDep) -> JwksResponse:
    response.headers["Cache-Control"] = "public, max-age=300"
    return JwksResponse(keys=runtime.tokens.jwks())


@auth_router.get(
    "/oauth/{provider}/start",
    response_model=None,
    status_code=302,
    summary="Begin provider sign-in or linking",
    dependencies=policies("api.default"),
    openapi_extra=protection(
        "api.default",
        csrf="link",
        errors={401: ["unauthenticated", "oauth_unavailable"], 422: ["invalid_redirect"]},
        turnstile=None,
        cookie=None,
    ),
)
async def oauth_start(
    provider: ProviderName,
    request: Request,
    principal: OAuthPrincipalDep,
    service: AuthServiceDep,
    query: Annotated[OAuthStartQuery, Query()],
) -> RedirectResponse:
    cookies = CookieManager(service.resources.settings.auth.cookie_domain)
    if query.intent == "link" and principal and principal.session_id:
        service.runtime.csrf.verify(
            principal.session_id, request.cookies.get(CSRF_COOKIE), request.headers.get("X-CSRF-Token")
        )
    location, browser = await OAuthService(service).start(provider, query.next, query.intent, principal)
    response = RedirectResponse(location, status_code=302)
    cookies.set_oauth(response, browser)
    return response


@auth_router.post(
    "/oauth/{provider}/start",
    response_model=OAuthStartResponse,
    status_code=200,
    summary="Begin an authenticated provider flow without following redirects",
    dependencies=policies("api.default"),
    openapi_extra=protection(
        "api.default", csrf="session", errors={401: ["unauthenticated"], 422: ["invalid_redirect"]}, turnstile=None
    ),
)
async def oauth_start_authenticated(
    provider: ProviderName,
    body: OAuthStartQuery,
    response: Response,
    principal: CurrentPrincipalDep,
    service: AuthServiceDep,
) -> OAuthStartResponse:
    location, browser = await OAuthService(service).start(provider, body.next, body.intent, principal)
    CookieManager(service.resources.settings.auth.cookie_domain).set_oauth(response, browser)
    return OAuthStartResponse(url=location)


@auth_router.get(
    "/oauth/{provider}/callback",
    response_model=None,
    status_code=302,
    summary="Complete provider sign-in or linking",
    dependencies=policies("api.default"),
    openapi_extra=protection(
        "api.default", csrf="none", errors={302: ["oauth_failed"]}, turnstile=None, cookie="__Secure-mo_oauth"
    ),
)
async def oauth_callback(
    provider: ProviderName,
    request: Request,
    principal: OAuthPrincipalDep,
    service: AuthServiceDep,
    query: Annotated[OAuthCallbackQuery, Query()],
) -> RedirectResponse:
    cookies = CookieManager(service.resources.settings.auth.cookie_domain)
    try:
        location, tokens = await OAuthService(service).callback(
            provider, query.state, query.code, request.cookies.get(OAUTH_COOKIE), principal
        )
    except (
        AppError,
        ValueError,
        ValidationError,
        jwt.InvalidTokenError,
        httpx.HTTPError,
        IntegrityError,
        OutboundRequestBlockedError,
        ResponseTooLargeError,
    ):
        async with service.resources.database.transaction() as session:
            await service.audit(session, "oauth.failed")
        response = RedirectResponse(
            service.resources.settings.auth.web_origin + "/login?error=oauth_failed", status_code=302
        )
        cookies.clear_oauth(response)
        return response
    response = RedirectResponse(location, status_code=302)
    cookies.clear_oauth(response)
    if tokens:
        cookies.set_session(response, tokens)
    return response


@auth_router.delete(
    "/oauth/{provider}",
    response_model=None,
    status_code=204,
    summary="Unlink a sign-in provider",
    dependencies=policies("auth.password.change"),
    openapi_extra=protection(
        "auth.password.change",
        csrf="session",
        errors={401: ["unauthenticated", "token_expired"], 409: ["last_sign_in_method"]},
        turnstile=None,
        cookie="__Secure-mo_at",
    ),
)
async def unlink_oauth(provider: ProviderName, principal: CurrentPrincipalDep, service: AuthServiceDep) -> None:
    await OAuthService(service).unlink(principal, provider)
