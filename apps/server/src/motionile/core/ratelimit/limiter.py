import hashlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import structlog
from fastapi import Request, Response
from redis.asyncio import Redis
from redis.exceptions import RedisError

from motionile.core.errors import RateLimitedError, ServiceUnavailableError
from motionile.core.ids import new_id
from motionile.core.ratelimit.policies import RateLimitPolicy, RateLimitRule, RateLimitScope, UnknownPolicyError
from motionile.core.redis import RedisKeyBuilder
from motionile.core.security.rbac import principal_of

SCRIPT_PATH = Path(__file__).with_name("sliding_window.lua")
UNAVAILABLE_RETRY_AFTER_SECONDS = 5

logger = structlog.get_logger(__name__)

type IdentifierResolver = Callable[[Request], Awaitable[str | None]]


@dataclass(frozen=True)
class RateLimitIdentity:
    ip: str | None = None
    user_id: str | None = None
    identifier: str | None = None
    session_id: str | None = None
    api_key_id: str | None = None

    @property
    def is_anonymous(self) -> bool:
        return self.user_id is None and self.api_key_id is None

    def subject_for(self, rule: RateLimitRule) -> str | None:
        if rule.anonymous_only and not self.is_anonymous:
            return None
        combined = f"{self.ip}|{self.identifier}" if self.ip and self.identifier else None
        subjects: dict[RateLimitScope, str | None] = {
            RateLimitScope.IP: self.ip,
            RateLimitScope.USER: self.user_id,
            RateLimitScope.IDENTIFIER: self.identifier,
            RateLimitScope.IP_IDENTIFIER: combined,
            RateLimitScope.SESSION: self.session_id,
            RateLimitScope.API_KEY: self.api_key_id,
            RateLimitScope.GLOBAL: "all",
        }
        return subjects[rule.scope]


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    reset_seconds: int

    def headers(self) -> dict[str, str]:
        headers = {
            "RateLimit-Limit": str(self.limit),
            "RateLimit-Remaining": str(self.remaining),
            "RateLimit-Reset": str(self.reset_seconds),
        }
        if not self.allowed:
            headers["Retry-After"] = str(max(self.reset_seconds, 1))
        return headers


def hashed_subject(scope: RateLimitScope, subject: str) -> str:
    return hashlib.sha256(f"{scope}:{subject}".encode()).hexdigest()[:32]


def combine(rules: Sequence[RateLimitRule], allowed: bool, results: Sequence[int]) -> RateLimitDecision:
    decisions = [
        RateLimitDecision(
            allowed=allowed,
            limit=rule.limit,
            remaining=int(results[index * 2]),
            reset_seconds=max(int(results[index * 2 + 1]) // 1000 + (int(results[index * 2 + 1]) % 1000 > 0), 0),
        )
        for index, rule in enumerate(rules)
    ]
    if not allowed:
        exhausted = [decision for decision in decisions if decision.remaining == 0]
        return max(exhausted or decisions, key=lambda decision: decision.reset_seconds)
    return min(decisions, key=lambda decision: (decision.remaining, -decision.reset_seconds))


class RateLimiter:
    def __init__(
        self,
        redis: Redis,
        keys: RedisKeyBuilder,
        policies: Mapping[str, RateLimitPolicy],
        *,
        enabled: bool = True,
    ) -> None:
        self.keys = keys
        self.policies = dict(policies)
        self.enabled = enabled
        self._script = redis.register_script(SCRIPT_PATH.read_text(encoding="utf-8"))

    def policy(self, name: str) -> RateLimitPolicy:
        policy = self.policies.get(name)
        if policy is None:
            raise UnknownPolicyError(name)
        return policy

    async def hit(self, policy: RateLimitPolicy, identity: RateLimitIdentity) -> RateLimitDecision | None:
        applicable: list[tuple[int, RateLimitRule, str]] = []
        for index, rule in enumerate(policy.rules):
            subject = identity.subject_for(rule)
            if subject is not None:
                applicable.append((index, rule, subject))
        if not applicable:
            return None
        keys = [
            self.keys.key("ratelimit", policy.name, index, hashed_subject(rule.scope, subject))
            for index, rule, subject in applicable
        ]
        arguments: list[str | int] = [new_id().hex]
        for _, rule, _ in applicable:
            arguments.extend([rule.limit, rule.window_seconds * 1000])
        raw: list[int] = await self._script(keys=keys, args=arguments)
        return combine([rule for _, rule, _ in applicable], bool(raw[0]), raw[1:])

    async def check(self, policy: RateLimitPolicy, identity: RateLimitIdentity) -> RateLimitDecision | None:
        if not self.enabled:
            return None
        try:
            return await self.hit(policy, identity)
        except (RedisError, OSError, TimeoutError) as error:
            if policy.fail_closed:
                logger.warning("ratelimit.unavailable_fail_closed", policy=policy.name, error=type(error).__name__)
                raise ServiceUnavailableError(
                    "Rate limiting is temporarily unavailable. Try again shortly.",
                    code="rate_limiter_unavailable",
                    headers={"Retry-After": str(UNAVAILABLE_RETRY_AFTER_SECONDS)},
                ) from error
            logger.warning("ratelimit.unavailable_fail_open", policy=policy.name, error=type(error).__name__)
            return None


def identity_from_request(request: Request, identifier: str | None) -> RateLimitIdentity:
    principal = principal_of(request)
    client = request.client
    return RateLimitIdentity(
        ip=client.host if client is not None else None,
        user_id=str(principal.user_id) if principal is not None and principal.user_id is not None else None,
        identifier=identifier,
        session_id=str(principal.session_id) if principal is not None and principal.session_id is not None else None,
        api_key_id=str(principal.api_key_id) if principal is not None and principal.api_key_id is not None else None,
    )


def rate_limiter_of(request: Request) -> RateLimiter:
    resources: object = getattr(request.app.state, "resources", None)
    limiter: object = getattr(resources, "rate_limiter", None)
    if not isinstance(limiter, RateLimiter):
        message = "the rate limiter is not configured on the application"
        raise TypeError(message)
    return limiter


def rate_limit(policy_name: str, *, identifier: IdentifierResolver | None = None) -> Callable[..., Awaitable[None]]:
    async def enforce_rate_limit(request: Request, response: Response) -> None:
        limiter = rate_limiter_of(request)
        policy = limiter.policy(policy_name)
        subject = await identifier(request) if identifier is not None else None
        decision = await limiter.check(policy, identity_from_request(request, subject))
        if decision is None:
            return
        if not decision.allowed:
            raise RateLimitedError(f"Rate limit for {policy.name} exceeded.", headers=decision.headers())
        response.headers.update(decision.headers())

    enforce_rate_limit.__name__ = f"rate_limit_{policy_name.replace('.', '_')}"
    return enforce_rate_limit
