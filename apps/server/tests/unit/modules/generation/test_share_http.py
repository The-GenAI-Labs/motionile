import hmac
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient, Response
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.settings import make_settings
from tests.unit.modules.generation.test_share import Fixture

from motionile.core.config import Settings, ShareSettings
from motionile.core.db import Database
from motionile.core.dependencies import get_database, get_settings_dependency
from motionile.core.errors import register_exception_handlers
from motionile.core.ratelimit.limiter import RateLimiter
from motionile.core.ratelimit.policies import RateLimitPolicy, RateLimitRule, RateLimitScope, resolve_policies
from motionile.core.redis import RedisKeyBuilder
from motionile.modules.generation.dependencies import INTERNAL_HEADER, get_share_service, is_internal_share_caller
from motionile.modules.generation.share_router import public_share_router
from motionile.modules.generation.slugs import new_slug

SECRET = "internal-share-secret-" + "x" * 16
LIMIT = 3
PUBLIC_IP = ("198.51.100.7", 4000)
OTHER_IP = ("198.51.100.8", 4000)


class CountingRedis:
    def __init__(self) -> None:
        self.hits: dict[str, int] = {}

    def register_script(self, _source: str) -> "CountingRedis":
        return self

    async def __call__(self, *, keys: list[str], args: list[str | int]) -> list[int]:
        key = keys[0]
        self.hits[key] = self.hits.get(key, 0) + 1
        limit = int(args[1])
        allowed = self.hits[key] <= limit
        return [int(allowed), max(limit - self.hits[key], 0), 60_000]

    def hits_for(self, policy: str) -> int:
        return sum(count for key, count in self.hits.items() if f":ratelimit:{policy}:" in key)


class FakeDatabase:
    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        yield AsyncSession()


class LimiterState:
    def __init__(self, rate_limiter: RateLimiter) -> None:
        self.rate_limiter = rate_limiter


class Harness:
    def __init__(self, secret: str | None = SECRET) -> None:
        self.fixture = Fixture()
        self.redis = CountingRedis()
        self.settings: Settings = make_settings().model_copy(
            update={"share": ShareSettings(internal_secret=SecretStr(secret) if secret is not None else None)}
        )
        policies = {
            **resolve_policies({}),
            "share.view": RateLimitPolicy("share.view", (RateLimitRule(LIMIT, 60, RateLimitScope.IP),)),
            "share.count": RateLimitPolicy("share.count", (RateLimitRule(LIMIT, 60, RateLimitScope.IP),)),
        }
        limiter = RateLimiter(cast("Redis", self.redis), RedisKeyBuilder("mo"), policies)
        self.application = FastAPI()
        register_exception_handlers(self.application)
        self.application.include_router(public_share_router, prefix="/v1")
        self.application.state.resources = LimiterState(limiter)
        self.application.dependency_overrides[get_settings_dependency] = lambda: self.settings
        self.application.dependency_overrides[get_database] = lambda: cast("Database", FakeDatabase())
        self.application.dependency_overrides[get_share_service] = lambda: self.fixture.service

    def client(self, address: tuple[str, int] = PUBLIC_IP) -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=self.application, client=address), base_url="http://test")

    async def link(self) -> str:
        view = await self.fixture.service.create(
            self.fixture.session, self.fixture.owner, self.fixture.job.id, self.fixture.request()
        )
        return view.slug

    @property
    def views(self) -> int:
        return self.fixture.store.links[0].view_count


@pytest.fixture
def harness() -> Harness:
    return Harness()


def internal(secret: str = SECRET) -> dict[str, str]:
    return {INTERNAL_HEADER: secret}


def problem_of(response: Response) -> tuple[int, str, str | None]:
    body = response.json()
    return response.status_code, body["code"], body.get("detail")


async def test_a_read_with_the_secret_skips_the_limiter_and_counts_no_view(harness: Harness) -> None:
    slug = await harness.link()

    async with harness.client() as client:
        statuses = [(await client.get(f"/v1/share/{slug}", headers=internal())).status_code for _ in range(LIMIT * 3)]

    assert statuses == [200] * (LIMIT * 3)
    assert harness.redis.hits == {}
    assert harness.views == 0
    assert harness.fixture.views.seen == set()


async def test_a_read_without_the_secret_is_limited_per_address_and_counts_a_view_once(harness: Harness) -> None:
    slug = await harness.link()

    async with harness.client() as client, harness.client(OTHER_IP) as other:
        statuses = [(await client.get(f"/v1/share/{slug}")).status_code for _ in range(LIMIT + 2)]
        limited = await client.get(f"/v1/share/{slug}")
        untouched = await other.get(f"/v1/share/{slug}")

    assert statuses == [200] * LIMIT + [429] * 2
    assert limited.status_code == 429
    assert limited.json()["code"] == "rate_limited"
    assert int(limited.headers["retry-after"]) >= 1
    assert untouched.status_code == 200
    assert harness.views == 2


@pytest.mark.parametrize("secret", ["wrong-secret-" + "y" * 20, "", SECRET[:-1], SECRET + "x"])
async def test_a_wrong_secret_gets_no_exemption(harness: Harness, secret: str) -> None:
    slug = await harness.link()

    async with harness.client() as client:
        statuses = [
            (await client.get(f"/v1/share/{slug}", headers=internal(secret))).status_code for _ in range(LIMIT + 1)
        ]

    assert statuses == [200] * LIMIT + [429]
    assert harness.redis.hits_for("share.view") == LIMIT + 1
    assert harness.views == 1


async def test_a_secret_is_ignored_when_none_is_configured() -> None:
    harness = Harness(secret=None)
    slug = await harness.link()

    async with harness.client() as client:
        statuses = [(await client.get(f"/v1/share/{slug}", headers=internal(""))).status_code for _ in range(LIMIT + 1)]

    assert statuses == [200] * LIMIT + [429]
    assert harness.views == 1


async def test_the_secret_does_not_bypass_the_view_counter_limit(harness: Harness) -> None:
    slug = await harness.link()

    async with harness.client() as client:
        statuses = [
            (await client.post(f"/v1/share/{slug}/views", headers=internal())).status_code for _ in range(LIMIT + 1)
        ]

    assert statuses == [204] * LIMIT + [429]
    assert harness.redis.hits_for("share.count") == LIMIT + 1


async def test_only_the_post_records_a_view_and_a_visitor_counts_once_per_window(harness: Harness) -> None:
    slug = await harness.link()

    async with harness.client() as client, harness.client(OTHER_IP) as other:
        first = await client.post(f"/v1/share/{slug}/views")
        repeated = await client.post(f"/v1/share/{slug}/views")
        second_visitor = await other.post(f"/v1/share/{slug}/views")

    assert [first.status_code, repeated.status_code, second_visitor.status_code] == [204, 204, 204]
    assert first.content == b""
    assert first.headers["cache-control"] == "no-store"
    assert harness.views == 2


async def test_the_server_render_then_the_browser_post_counts_one_view(harness: Harness) -> None:
    slug = await harness.link()

    async with harness.client() as client:
        page = await client.get(f"/v1/share/{slug}", headers=internal())
        recorded = await client.post(f"/v1/share/{slug}/views")

    assert (page.status_code, recorded.status_code) == (200, 204)
    assert harness.views == 1


async def test_a_dead_link_is_the_same_404_for_the_read_and_for_the_view_count(harness: Harness) -> None:
    slug = await harness.link()
    await harness.fixture.service.revoke(harness.fixture.session, harness.fixture.owner, harness.fixture.job.id)
    unknown = new_slug()

    async with harness.client() as client:
        reads = [await client.get(f"/v1/share/{name}") for name in (slug, unknown, "short")]
        counts = [await client.post(f"/v1/share/{name}/views") for name in (slug, unknown, "short")]

    problems = {problem_of(response) for response in [*reads, *counts]}
    assert len(problems) == 1
    assert next(iter(problems))[:2] == (404, "share_not_found")
    assert all(response.headers["content-type"] == "application/problem+json" for response in [*reads, *counts])
    assert harness.views == 0


async def test_the_view_count_route_has_its_own_limit(harness: Harness) -> None:
    slug = await harness.link()

    async with harness.client() as client:
        statuses = [(await client.post(f"/v1/share/{slug}/views")).status_code for _ in range(LIMIT + 2)]
        read = await client.get(f"/v1/share/{slug}")

    assert statuses == [204] * LIMIT + [429] * 2
    assert read.status_code == 200
    assert harness.redis.hits_for("share.count") == LIMIT + 2
    assert harness.redis.hits_for("share.view") == 1


def request_with(headers: dict[str, str]) -> Request:
    return Request(
        {"type": "http", "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()]}
    )


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        (internal(), True),
        ({"x-motionile-internal": SECRET}, True),
        (internal("nope"), False),
        (internal(""), False),
        (internal(SECRET.upper()), False),
        ({}, False),
    ],
)
def test_the_internal_caller_is_recognised_only_by_the_exact_secret(headers: dict[str, str], expected: bool) -> None:
    settings = Harness().settings

    assert is_internal_share_caller(request_with(headers), settings) is expected


def test_nobody_is_internal_when_no_secret_is_configured() -> None:
    settings = Harness(secret=None).settings

    assert is_internal_share_caller(request_with(internal()), settings) is False


def test_the_secret_is_compared_in_constant_time_on_fixed_length_digests(monkeypatch: pytest.MonkeyPatch) -> None:
    compared: list[tuple[bytes, bytes]] = []
    original = hmac.compare_digest

    def spy(left: bytes, right: bytes) -> bool:
        compared.append((left, right))
        return original(left, right)

    monkeypatch.setattr(hmac, "compare_digest", spy)
    settings = Harness().settings

    for supplied in ("a", SECRET, SECRET + "-and-a-much-longer-value" * 4):
        is_internal_share_caller(request_with(internal(supplied)), settings)

    assert len(compared) == 3
    assert {len(left) for left, _ in compared} == {32}
    assert {len(right) for _, right in compared} == {32}
    assert SECRET.encode() not in {value for pair in compared for value in pair}
