import hmac
from datetime import timedelta
from http import HTTPStatus
from typing import Literal, Protocol
from urllib.parse import urlencode
from uuid import UUID

import jwt
from pydantic import BaseModel, Field, SecretStr

from motionile.core.config import AuthSettings
from motionile.core.errors import UnauthorizedError
from motionile.core.http.safe_client import SafeHttpClient
from motionile.core.redis import RedisStore
from motionile.core.security.tokens import base64url, token_hash

ProviderName = Literal["google", "github", "microsoft"]
MICROSOFT_PERSONAL_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"


class ProviderIdentity(BaseModel):
    subject: str = Field(min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=254)
    email_verified: bool = False
    name: str = Field(default="Motionile user", max_length=120)


class ProviderTokens(BaseModel):
    access_token: SecretStr
    id_token: SecretStr | None = None


class OAuthProvider(Protocol):
    def authorization_url(self, state: str, verifier: str, nonce: str) -> str: ...
    async def exchange_code(self, code: str, verifier: str) -> ProviderTokens: ...
    async def fetch_identity(self, tokens: ProviderTokens, nonce: str) -> ProviderIdentity: ...


class JwksDocument(BaseModel):
    keys: list[dict[str, object]]


class ProviderSpec(BaseModel):
    authorize: str
    exchange_url: str
    scopes: str
    jwks: str | None = None


SPECS: dict[ProviderName, ProviderSpec] = {
    "google": ProviderSpec(
        authorize="https://accounts.google.com/o/oauth2/v2/auth",
        exchange_url="https://oauth2.googleapis.com/token",
        scopes="openid email profile",
        jwks="https://www.googleapis.com/oauth2/v3/certs",
    ),
    "github": ProviderSpec(
        authorize="https://github.com/login/oauth/authorize",
        exchange_url="https://github.com/login/oauth/access_token",
        scopes="read:user user:email",
    ),
    "microsoft": ProviderSpec(
        authorize="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        exchange_url="https://login.microsoftonline.com/common/oauth2/v2.0/token",
        scopes="openid email profile",
        jwks="https://login.microsoftonline.com/common/discovery/v2.0/keys",
    ),
}


def verified_email(provider: ProviderName, claims: dict[str, object]) -> bool:
    if provider == "google":
        return claims.get("email_verified") is True
    if provider == "microsoft":
        return claims.get("tid") == MICROSOFT_PERSONAL_TENANT or claims.get("xms_edov") is True
    return claims.get("verified") is True and claims.get("primary") is True


class LiveOAuthProvider:
    def __init__(
        self, provider: ProviderName, settings: AuthSettings, client: SafeHttpClient, store: RedisStore
    ) -> None:
        self.provider: ProviderName = provider
        self.settings = settings
        self.client = client
        self.store = store
        self.spec = SPECS[provider]
        self.client_id: str = getattr(settings, f"{provider}_client_id") or ""
        self.client_secret: SecretStr | None = getattr(settings, f"{provider}_client_secret")
        self.redirect_uri = f"{settings.api_origin}/v1/auth/oauth/{provider}/callback"

    def authorization_url(self, state: str, verifier: str, nonce: str) -> str:
        if not self.client_id:
            raise UnauthorizedError(code="oauth_unavailable")
        return (
            self.spec.authorize
            + "?"
            + urlencode(
                {
                    "client_id": self.client_id,
                    "redirect_uri": self.redirect_uri,
                    "response_type": "code",
                    "scope": self.spec.scopes,
                    "state": state,
                    "nonce": nonce,
                    "code_challenge": base64url(token_hash(verifier)),
                    "code_challenge_method": "S256",
                }
            )
        )

    async def exchange_code(self, code: str, verifier: str) -> ProviderTokens:
        if self.client_secret is None:
            raise UnauthorizedError(code="oauth_unavailable")
        response = await self.client.post_form(
            self.spec.exchange_url,
            {
                "client_id": self.client_id,
                "client_secret": self.client_secret.get_secret_value(),
                "code": code,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            },
            headers={"Accept": "application/json"},
        )
        if response.status_code != HTTPStatus.OK:
            raise UnauthorizedError(code="oauth_failed")
        return ProviderTokens.model_validate_json(response.content)

    async def fetch_identity(self, tokens: ProviderTokens, nonce: str) -> ProviderIdentity:
        if self.provider == "github":
            return await self.github_identity(tokens)
        if tokens.id_token is None:
            raise UnauthorizedError(code="oauth_failed")
        claims = await self.verify_id_token(tokens.id_token.get_secret_value(), nonce)
        return ProviderIdentity.model_validate(
            {
                "subject": f"{claims['tid']}:{claims['sub']}" if self.provider == "microsoft" else claims["sub"],
                "email": claims.get("email"),
                "email_verified": verified_email(self.provider, claims),
                "name": claims.get("name", "Motionile user"),
            }
        )

    async def github_identity(self, tokens: ProviderTokens) -> ProviderIdentity:
        headers = {
            "Authorization": f"Bearer {tokens.access_token.get_secret_value()}",
            "Accept": "application/vnd.github+json",
        }
        user = await self.client.get("https://api.github.com/user", headers=headers)
        emails = await self.client.get("https://api.github.com/user/emails", headers=headers)
        if user.status_code != HTTPStatus.OK or emails.status_code != HTTPStatus.OK:
            raise UnauthorizedError(code="oauth_failed")
        profile = user.json()
        primary = next((item for item in emails.json() if verified_email("github", item)), None)
        return ProviderIdentity(
            subject=str(profile["id"]),
            email=primary["email"] if primary else None,
            email_verified=primary is not None,
            name=(profile.get("name") or profile["login"])[:120],
        )

    async def verify_id_token(self, token: str, nonce: str) -> dict[str, object]:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise UnauthorizedError(code="oauth_failed")
        unverified = jwt.decode(token, options={"verify_signature": False})
        if self.provider == "google":
            issuer = unverified.get("iss")
            if issuer not in {"https://accounts.google.com", "accounts.google.com"}:
                raise UnauthorizedError(code="oauth_failed")
        else:
            tenant = str(UUID(unverified.get("tid", "")))
            issuer = f"https://login.microsoftonline.com/{tenant}/v2.0"
        key = await self.signing_key(header["kid"], issuer)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            audience=self.client_id,
            issuer=issuer,
            leeway=5,
            options={"require": ["sub", "iss", "aud", "exp", "iat", "nonce"]},
        )
        received_nonce = claims.get("nonce")
        if not isinstance(received_nonce, str) or not hmac.compare_digest(received_nonce.encode(), nonce.encode()):
            raise UnauthorizedError(code="oauth_failed")
        if claims.get("azp", self.client_id) != self.client_id:
            raise UnauthorizedError(code="oauth_failed")
        return claims

    async def signing_key(self, kid: str, issuer: str) -> jwt.PyJWK:
        cache_key = self.store.keys.key("oauth.jwks", self.provider)
        cached = await self.store.get(cache_key)
        for attempt in range(2):
            if cached is None or attempt:
                if self.spec.jwks is None:
                    raise UnauthorizedError(code="oauth_failed")
                response = await self.client.get(self.spec.jwks)
                if response.status_code != HTTPStatus.OK:
                    raise UnauthorizedError(code="oauth_failed")
                cached = response.content
                await self.store.set(cache_key, cached, ttl=timedelta(hours=1))
            keys = JwksDocument.model_validate_json(cached)
            for data in keys.keys:
                if data.get("kid") != kid or data.get("use") not in {None, "sig"}:
                    continue
                if self.provider == "microsoft":
                    key_issuer = data.get("issuer")
                    tenant = issuer.split("/")[-2]
                    if not isinstance(key_issuer, str) or key_issuer.replace("{tenantid}", tenant) != issuer:
                        continue
                return jwt.PyJWK.from_dict(data, algorithm="RS256")
        raise UnauthorizedError(code="oauth_failed")
