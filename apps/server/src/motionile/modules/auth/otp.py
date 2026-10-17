import hmac
import secrets
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel
from redis.exceptions import WatchError

from motionile.core.clock import Clock
from motionile.core.errors import RateLimitedError, UnauthorizedError
from motionile.core.redis import RedisStore
from motionile.core.security.identifiers import Identifier
from motionile.core.security.tokens import random_token, sign_value, token_hash

MAX_TOKEN_LENGTH = 128

OtpPurpose = Literal["verify_contact", "login", "password_reset", "set_password", "add_contact", "delete_account"]
OTP_TTL = timedelta(minutes=5)
TICKET_TTL = timedelta(minutes=10)
RESEND_TTL = timedelta(seconds=60)
MAX_ATTEMPTS = 5


class Challenge(BaseModel):
    id: str
    purpose: OtpPurpose
    user_id: UUID | None
    kind: Literal["email", "phone"]
    destination: str
    digest: str
    attempts: int = 0
    expires_at: datetime

    @property
    def identifier(self) -> Identifier:
        return Identifier(self.kind, self.destination)


class Ticket(BaseModel):
    challenge_id: str
    purpose: OtpPurpose
    user_id: UUID | None
    kind: Literal["email", "phone"]
    destination: str

    @property
    def identifier(self) -> Identifier:
        return Identifier(self.kind, self.destination)


class OtpService:
    def __init__(self, store: RedisStore, clock: Clock, pepper: bytes) -> None:
        self.store = store
        self.clock = clock
        self.pepper = pepper

    def digest(self, purpose: OtpPurpose, destination: str, code: str) -> str:
        return sign_value(self.pepper, purpose, destination, code)

    def challenge_key(self, challenge_id: str) -> str:
        return self.store.keys.key("otp", challenge_id)

    def ticket_key(self, ticket: str) -> str:
        return self.store.keys.key("auth.ticket", token_hash(ticket).hex())

    async def issue(
        self, purpose: OtpPurpose, identifier: Identifier, user_id: UUID | None
    ) -> tuple[str, Challenge, str]:
        cooldown_key = self.store.keys.key("otp.cooldown", token_hash(identifier.value).hex())
        available = await self.store.set_if_absent(cooldown_key, "1", ttl=RESEND_TTL)
        if not available:
            raise RateLimitedError(code="otp_cooldown", headers={"Retry-After": "60"})
        code = f"{secrets.randbelow(1_000_000):06d}"
        challenge = Challenge(
            id=random_token(),
            purpose=purpose,
            user_id=user_id,
            kind=identifier.kind,
            destination=identifier.value,
            digest=self.digest(purpose, identifier.value, code),
            expires_at=self.clock.now() + OTP_TTL,
        )
        ticket = random_token()
        await self.store.set(self.challenge_key(challenge.id), challenge.model_dump_json(), ttl=OTP_TTL)
        await self.store.set(
            self.ticket_key(ticket),
            Ticket(
                challenge_id=challenge.id,
                purpose=purpose,
                user_id=user_id,
                kind=identifier.kind,
                destination=identifier.value,
            ).model_dump_json(),
            ttl=TICKET_TTL,
        )
        return ticket, challenge, code

    async def ticket(self, value: str | None, purpose: OtpPurpose | None = None) -> Ticket:
        if not value or len(value) > MAX_TOKEN_LENGTH:
            raise UnauthorizedError(code="invalid_challenge")
        raw = await self.store.get(self.ticket_key(value))
        if raw is None:
            raise UnauthorizedError(code="invalid_challenge")
        ticket = Ticket.model_validate_json(raw)
        if purpose is not None and ticket.purpose != purpose:
            raise UnauthorizedError(code="invalid_challenge")
        return ticket

    async def verify(self, value: str | None, purpose: OtpPurpose, code: str) -> Challenge:
        ticket = await self.ticket(value, purpose)
        key = self.challenge_key(ticket.challenge_id)
        while True:
            async with self.store.client.pipeline(transaction=True) as pipeline:
                try:
                    await pipeline.watch(key)
                    raw = await pipeline.get(key)
                    if raw is None:
                        raise UnauthorizedError(code="invalid_challenge")
                    challenge = Challenge.model_validate_json(raw)
                    matches = hmac.compare_digest(challenge.digest, self.digest(purpose, challenge.destination, code))
                    valid = matches and challenge.purpose == purpose and challenge.expires_at > self.clock.now()
                    challenge.attempts += 1
                    pipeline.multi()
                    if valid or challenge.attempts >= MAX_ATTEMPTS:
                        pipeline.delete(key)
                    else:
                        pipeline.set(key, challenge.model_dump_json(), keepttl=True)
                    await pipeline.execute()
                    break
                except WatchError:
                    continue
        if not valid or challenge.user_id is None:
            raise UnauthorizedError(code="invalid_challenge")
        if value is not None:
            await self.store.delete(self.ticket_key(value))
        return challenge
