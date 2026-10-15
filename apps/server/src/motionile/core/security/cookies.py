from dataclasses import dataclass
from datetime import datetime

from starlette.responses import Response

ACCESS_COOKIE = "__Secure-mo_at"
REFRESH_COOKIE = "__Secure-mo_rt"
TICKET_COOKIE = "__Secure-mo_vt"
CSRF_COOKIE = "mo_csrf"
HINT_COOKIE = "mo_auth"
OAUTH_COOKIE = "__Secure-mo_oauth"
ACCESS_SECONDS = 900
TICKET_SECONDS = 600


@dataclass(frozen=True)
class SessionCookies:
    access: str
    refresh: str
    csrf: str
    expires_at: datetime
    refresh_max_age: int


class CookieManager:
    def __init__(self, domain: str | None) -> None:
        self.domain = domain

    def set_session(self, response: Response, tokens: SessionCookies) -> None:
        response.set_cookie(
            ACCESS_COOKIE,
            tokens.access,
            max_age=ACCESS_SECONDS,
            domain=self.domain,
            secure=True,
            httponly=True,
            samesite="lax",
        )
        response.set_cookie(
            REFRESH_COOKIE,
            tokens.refresh,
            max_age=tokens.refresh_max_age,
            path="/v1/auth",
            secure=True,
            httponly=True,
            samesite="strict",
        )
        response.set_cookie(CSRF_COOKIE, tokens.csrf, domain=self.domain, secure=True, samesite="lax")
        response.set_cookie(
            HINT_COOKIE,
            str(int(tokens.expires_at.timestamp())),
            max_age=ACCESS_SECONDS,
            domain=self.domain,
            secure=True,
            samesite="lax",
        )
        self.clear_ticket(response)

    def set_ticket(self, response: Response, ticket: str) -> None:
        response.set_cookie(
            TICKET_COOKIE,
            ticket,
            max_age=TICKET_SECONDS,
            path="/v1/auth",
            secure=True,
            httponly=True,
            samesite="strict",
        )

    def set_oauth(self, response: Response, value: str) -> None:
        response.set_cookie(
            OAUTH_COOKIE, value, max_age=TICKET_SECONDS, path="/v1/auth", secure=True, httponly=True, samesite="lax"
        )

    def clear_oauth(self, response: Response) -> None:
        response.delete_cookie(OAUTH_COOKIE, path="/v1/auth", secure=True, httponly=True, samesite="lax")

    def clear_ticket(self, response: Response) -> None:
        response.delete_cookie(TICKET_COOKIE, path="/v1/auth", secure=True, httponly=True, samesite="strict")

    def clear(self, response: Response) -> None:
        response.delete_cookie(ACCESS_COOKIE, domain=self.domain, secure=True, httponly=True, samesite="lax")
        response.delete_cookie(REFRESH_COOKIE, path="/v1/auth", secure=True, httponly=True, samesite="strict")
        response.delete_cookie(CSRF_COOKIE, domain=self.domain, secure=True, samesite="lax")
        response.delete_cookie(HINT_COOKIE, domain=self.domain, secure=True, samesite="lax")
        self.clear_ticket(response)
        self.clear_oauth(response)
