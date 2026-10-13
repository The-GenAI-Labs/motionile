from collections.abc import Awaitable, Callable
from uuid import UUID

import pytest
from fastapi import Depends, FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError

from motionile.core.errors import ServiceUnavailableError, register_exception_handlers
from motionile.core.ratelimit.limiter import (
    RateLimitDecision,
    RateLimiter,
    RateLimitIdentity,
    combine,
    hashed_subject,
    rate_limit,
)
from motionile.core.ratelimit.policies import RateLimitPolicy, RateLimitRule, RateLimitScope, UnknownPolicyError
from motionile.core.redis import RedisKeyBuilder
from motionile.core.security.rbac import Principal, PrincipalKind

LOGIN = RateLimitPolicy(
    "auth.login",
    (RateLimitRule(5, 60, RateLimitScope.IP_IDENTIFIER), RateLimitRule(30, 3600, RateLimitScope.IP)),
    fail_closed=True,
)
DEFAULT = RateLimitPolicy(
    "api.default",
    (RateLimitRule(120, 60, RateLimitScope.USER), RateLimitRule(60, 60, RateLimitScope.IP, anonymous_only=True)),
)


class ScriptedRedis:
    def __init__(self, responses: list[list[int]] | None = None, error: Exception | None = None) -> None:
        self.responses = responses or []
        self.error = error
        self.calls: list[tuple[list[str], list[str | int]]] = []

    def register_script(self, _source: str) -> "ScriptedRedis":
        return self

    async def __call__(self, *, keys: list[str], args: list[str | int]) -> list[int]:
        self.calls.append((keys, args))
        if self.error is not None:
            raise self.error
        return self.responses.pop(0)


def limiter(redis: ScriptedRedis, *, enabled: bool = True) -> RateLimiter:
    policies = {policy.name: policy for policy in (LOGIN, DEFAULT)}
    return RateLimiter(redis, RedisKeyBuilder("mo"), policies, enabled=enabled)  # type: ignore[arg-type]


def test_identity_subjects_per_scope() -> None:
    identity = RateLimitIdentity(ip="203.0.113.9", identifier="a@b.co", session_id="s", api_key_id="k")

    assert identity.subject_for(RateLimitRule(1, 1, RateLimitScope.IP)) == "203.0.113.9"
    assert identity.subject_for(RateLimitRule(1, 1, RateLimitScope.IP_IDENTIFIER)) == "203.0.113.9|a@b.co"
    assert identity.subject_for(RateLimitRule(1, 1, RateLimitScope.USER)) is None
    assert identity.subject_for(RateLimitRule(1, 1, RateLimitScope.SESSION)) == "s"
    assert identity.subject_for(RateLimitRule(1, 1, RateLimitScope.API_KEY)) == "k"
    assert identity.subject_for(RateLimitRule(1, 1, RateLimitScope.GLOBAL)) == "all"
    assert identity.subject_for(RateLimitRule(1, 1, RateLimitScope.IP, anonymous_only=True)) is None


def test_hashed_subject_hides_personal_data() -> None:
    hashed = hashed_subject(RateLimitScope.IDENTIFIER, "person@example.com")

    assert "person" not in hashed
    assert len(hashed) == 32


def test_combine_reports_most_restrictive_rule() -> None:
    rules = [RateLimitRule(5, 60, RateLimitScope.IP), RateLimitRule(30, 3600, RateLimitScope.IP)]

    allowed = combine(rules, True, [4, 60000, 2, 1200500])
    denied = combine(rules, False, [0, 30000, 3, 500])

    assert allowed == RateLimitDecision(allowed=True, limit=30, remaining=2, reset_seconds=1201)
    assert denied == RateLimitDecision(allowed=False, limit=5, remaining=0, reset_seconds=30)


def test_decision_headers() -> None:
    assert RateLimitDecision(False, 5, 0, 12).headers() == {
        "RateLimit-Limit": "5",
        "RateLimit-Remaining": "0",
        "RateLimit-Reset": "12",
        "Retry-After": "12",
    }
    assert "Retry-After" not in RateLimitDecision(True, 5, 4, 12).headers()


async def test_sends_only_applicable_rules_to_redis() -> None:
    redis = ScriptedRedis([[1, 119, 60000]])

    decision = await limiter(redis).check(DEFAULT, RateLimitIdentity(ip="1.2.3.4", user_id="u-1"))

    keys, args = redis.calls[0]
    assert len(keys) == 1
    assert keys[0].startswith("mo:ratelimit:api.default:0:")
    assert args[1:] == [120, 60000]
    assert decision == RateLimitDecision(True, 120, 119, 60)


async def test_no_applicable_rule_means_no_decision() -> None:
    redis = ScriptedRedis()

    assert await limiter(redis).check(LOGIN, RateLimitIdentity()) is None
    assert redis.calls == []


async def test_disabled_limiter_never_calls_redis() -> None:
    redis = ScriptedRedis()

    assert await limiter(redis, enabled=False).check(LOGIN, RateLimitIdentity(ip="1.1.1.1")) is None
    assert redis.calls == []


async def test_redis_failure_fails_closed_for_auth_policies() -> None:
    redis = ScriptedRedis(error=RedisConnectionError("down"))

    with pytest.raises(ServiceUnavailableError) as raised:
        await limiter(redis).check(LOGIN, RateLimitIdentity(ip="1.1.1.1", identifier="x"))
    assert raised.value.code == "rate_limiter_unavailable"
    assert raised.value.headers["Retry-After"] == "5"


async def test_redis_failure_fails_open_for_other_policies() -> None:
    redis = ScriptedRedis(error=TimeoutError())

    assert await limiter(redis).check(DEFAULT, RateLimitIdentity(ip="1.1.1.1")) is None


def test_unknown_policy_lookup_fails() -> None:
    with pytest.raises(UnknownPolicyError):
        limiter(ScriptedRedis()).policy("nope")


class AppState:
    def __init__(self, rate_limiter: RateLimiter) -> None:
        self.rate_limiter = rate_limiter


def build_app(redis: ScriptedRedis, principal: Principal | None = None) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.state.resources = AppState(limiter(redis))

    async def identifier(_: object) -> str:
        return "person@example.com"

    @app.middleware("http")
    async def attach_principal(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if principal is not None:
            request.state.principal = principal
        return await call_next(request)

    @app.post("/login", dependencies=[Depends(rate_limit("auth.login", identifier=identifier))])
    async def login() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/things", dependencies=[Depends(rate_limit("api.default"))])
    async def things() -> dict[str, str]:
        return {"status": "ok"}

    return app


@pytest.fixture
def principal() -> Principal:
    return Principal(kind=PrincipalKind.USER, user_id=UUID(int=7), roles=frozenset({"user"}))


async def test_dependency_sets_rate_limit_headers() -> None:
    app = build_app(ScriptedRedis([[1, 4, 60000, 29, 3600000]]))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post("/login")

    assert response.status_code == 200
    assert response.headers["ratelimit-limit"] == "5"
    assert response.headers["ratelimit-remaining"] == "4"


async def test_dependency_rejects_with_problem_and_retry_after() -> None:
    app = build_app(ScriptedRedis([[0, 0, 42000, 10, 3000000]]))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        response = await http.post("/login")

    assert response.status_code == 429
    assert response.json()["code"] == "rate_limited"
    assert response.headers["retry-after"] == "42"


async def test_dependency_uses_the_principal_for_user_rules(principal: Principal) -> None:
    redis = ScriptedRedis([[1, 119, 60000]])
    app = build_app(redis, principal)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        await http.get("/things")

    keys, _ = redis.calls[0]
    assert keys == [f"mo:ratelimit:api.default:0:{hashed_subject(RateLimitScope.USER, str(UUID(int=7)))}"]


async def test_missing_limiter_is_a_configuration_error() -> None:
    app = FastAPI()

    @app.get("/x", dependencies=[Depends(rate_limit("api.default"))])
    async def handler() -> None:
        return None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        with pytest.raises(TypeError, match="rate limiter is not configured"):
            await http.get("/x")
