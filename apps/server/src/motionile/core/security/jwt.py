import base64
from datetime import timedelta
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, ConfigDict, ValidationError

from motionile.core.clock import Clock
from motionile.core.config import AuthSettings
from motionile.core.errors import UnauthorizedError
from motionile.core.ids import new_id
from motionile.core.redis import RedisStore
from motionile.core.security.cookies import ACCESS_SECONDS
from motionile.core.security.rbac import Principal, PrincipalKind
from motionile.core.security.tokens import base64url, token_hash

JWT_LEEWAY = 5


class AccessClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    sub: str
    sid: str
    roles: list[str]
    iss: str
    aud: str
    iat: int
    exp: int
    jti: str


class AccessTokens:
    def __init__(self, settings: AuthSettings, clock: Clock, store: RedisStore) -> None:
        self.settings = settings
        self.clock = clock
        self.store = store
        self.keys = {
            kid: Ed25519PrivateKey.from_private_bytes(base64.b64decode(value.get_secret_value(), validate=True))
            for kid, value in settings.jwt_keys.items()
        }
        if not self.keys:
            self.keys = {"local": Ed25519PrivateKey.from_private_bytes(token_hash("motionile-local-signing-key"))}

    def issue(self, user_id: UUID, family_id: UUID, roles: list[str]) -> str:
        now = int(self.clock.now().timestamp())
        claims = AccessClaims(
            sub=str(user_id),
            sid=str(family_id),
            roles=roles,
            iss=self.settings.jwt_issuer,
            aud=self.settings.jwt_audience,
            iat=now,
            exp=now + ACCESS_SECONDS,
            jti=str(new_id()),
        )
        return jwt.encode(
            claims.model_dump(),
            self.keys[self.settings.jwt_current_kid],
            algorithm="EdDSA",
            headers={"kid": self.settings.jwt_current_kid, "typ": "JWT"},
        )

    def decode(self, token: str) -> AccessClaims:
        try:
            header = jwt.get_unverified_header(token)
            key = self.keys.get(header.get("kid", ""))
            if key is None or header.get("alg") != "EdDSA":
                raise ValueError
            payload = jwt.decode(
                token,
                key.public_key(),
                algorithms=["EdDSA"],
                audience=self.settings.jwt_audience,
                issuer=self.settings.jwt_issuer,
                options={
                    "verify_exp": False,
                    "verify_iat": False,
                    "verify_nbf": False,
                    "require": list(AccessClaims.model_fields),
                },
            )
            claims = AccessClaims.model_validate(payload)
            UUID(claims.sub)
            UUID(claims.sid)
            UUID(claims.jti)
            now = int(self.clock.now().timestamp())
            if claims.iat > now + JWT_LEEWAY or claims.exp - claims.iat != ACCESS_SECONDS:
                raise ValueError
        except (jwt.InvalidTokenError, ValueError, ValidationError, TypeError) as error:
            raise UnauthorizedError(code="unauthenticated") from error
        if claims.exp <= now - JWT_LEEWAY:
            raise UnauthorizedError(code="token_expired")
        return claims

    async def verify(self, token: str) -> Principal:
        claims = self.decode(token)
        family_id = UUID(claims.sid)
        if await self.store.get(self.store.keys.key("auth.revoked", family_id)) is not None:
            raise UnauthorizedError(code="unauthenticated")
        return Principal(
            kind=PrincipalKind.USER, user_id=UUID(claims.sub), session_id=family_id, roles=frozenset(claims.roles)
        )

    async def revoke(self, family_id: UUID) -> None:
        await self.store.set(
            self.store.keys.key("auth.revoked", family_id), "1", ttl=timedelta(seconds=ACCESS_SECONDS + JWT_LEEWAY)
        )

    def jwks(self) -> list[dict[str, str]]:
        return [
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "use": "sig",
                "alg": "EdDSA",
                "kid": kid,
                "x": base64url(key.public_key().public_bytes_raw()),
            }
            for kid, key in self.keys.items()
        ]
