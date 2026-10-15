import hmac
from datetime import timedelta
from urllib.parse import urlencode

from pydantic import BaseModel, SecretStr

from motionile.core.errors import UnauthorizedError
from motionile.core.redis import RedisStore
from motionile.core.security.tokens import base64url, random_token, token_hash
from motionile.modules.auth.oauth.providers import ProviderIdentity, ProviderName, ProviderTokens


class FakeGrant(BaseModel):
    challenge: str
    nonce: str
    identity: ProviderIdentity


class FakeOAuthProvider:
    def __init__(self, provider: ProviderName, api_origin: str, store: RedisStore) -> None:
        self.provider: ProviderName = provider
        self.api_origin = api_origin
        self.store = store

    def authorization_url(self, state: str, verifier: str, nonce: str) -> str:
        return f"{self.api_origin}/v1/_test/oauth/{self.provider}/authorize?" + urlencode(
            {
                "state": state,
                "challenge": base64url(token_hash(verifier)),
                "nonce": nonce,
            }
        )

    async def authorize(self, state: str, grant: FakeGrant) -> str:
        code = random_token()
        await self.store.set(
            self.store.keys.key("oauth.fake_code", token_hash(code).hex()),
            grant.model_dump_json(),
            ttl=timedelta(minutes=5),
        )
        return f"{self.api_origin}/v1/auth/oauth/{self.provider}/callback?" + urlencode({"state": state, "code": code})

    async def exchange_code(self, code: str, verifier: str) -> ProviderTokens:
        raw = await self.store.client.getdel(self.store.keys.key("oauth.fake_code", token_hash(code).hex()))
        if raw is None:
            raise UnauthorizedError(code="oauth_failed")
        grant = FakeGrant.model_validate_json(raw)
        if not hmac.compare_digest(grant.challenge, base64url(token_hash(verifier))):
            raise UnauthorizedError(code="oauth_failed")
        return ProviderTokens(access_token=SecretStr(grant.model_dump_json()))

    async def fetch_identity(self, tokens: ProviderTokens, nonce: str) -> ProviderIdentity:
        grant = FakeGrant.model_validate_json(tokens.access_token.get_secret_value())
        if not hmac.compare_digest(grant.nonce, nonce):
            raise UnauthorizedError(code="oauth_failed")
        return grant.identity
