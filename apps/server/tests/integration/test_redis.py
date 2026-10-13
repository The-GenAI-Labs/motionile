import asyncio
from datetime import timedelta

import pytest
from redis.asyncio import Redis

from motionile.core.ratelimit.limiter import RateLimiter, RateLimitIdentity, hashed_subject
from motionile.core.ratelimit.policies import RateLimitPolicy, RateLimitRule, RateLimitScope, resolve_policies
from motionile.core.redis import MissingTTLError, RedisKeyBuilder, RedisStore

CONCURRENT_REQUESTS = 50


@pytest.fixture
def store(redis_client: Redis, redis_keys: RedisKeyBuilder) -> RedisStore:
    return RedisStore(redis_client, redis_keys)


def limiter_with(redis_client: Redis, redis_keys: RedisKeyBuilder, *policies: RateLimitPolicy) -> RateLimiter:
    return RateLimiter(redis_client, redis_keys, {policy.name: policy for policy in policies})


async def test_store_writes_always_expire(store: RedisStore, redis_client: Redis) -> None:
    key = store.keys.key("probe", "one")

    await store.set(key, "value", ttl=timedelta(seconds=30))
    assert await store.set_if_absent(key, "other", ttl=timedelta(seconds=30)) is False

    assert await store.get(key) == b"value"
    assert 0 < await redis_client.pttl(key) <= 30_000
    with pytest.raises(MissingTTLError):
        await store.set(key, "value", ttl=timedelta(0))
    await store.delete(key)
    assert await store.get(key) is None


async def test_increment_sets_ttl_once(store: RedisStore, redis_client: Redis) -> None:
    key = store.keys.key("counter", "a")

    assert await store.increment(key, ttl=timedelta(seconds=60)) == 1
    first_ttl = await redis_client.pttl(key)
    await redis_client.pexpire(key, 5_000)
    assert await store.increment(key, ttl=timedelta(seconds=60)) == 2

    assert first_ttl > 5_000
    assert await redis_client.pttl(key) <= 5_000


async def test_ping_succeeds_against_real_redis(store: RedisStore) -> None:
    await store.ping(1.0)


async def test_sliding_window_allows_exactly_the_limit_under_concurrency(
    redis_client: Redis, redis_keys: RedisKeyBuilder
) -> None:
    policy = RateLimitPolicy("tests.concurrent", (RateLimitRule(10, 60, RateLimitScope.IP),))
    limiter = limiter_with(redis_client, redis_keys, policy)
    identity = RateLimitIdentity(ip="203.0.113.10")

    decisions = await asyncio.gather(*(limiter.check(policy, identity) for _ in range(CONCURRENT_REQUESTS)))

    allowed = [decision for decision in decisions if decision is not None and decision.allowed]
    denied = [decision for decision in decisions if decision is not None and not decision.allowed]
    assert len(allowed) == 10
    assert len(denied) == CONCURRENT_REQUESTS - 10
    assert sorted(decision.remaining for decision in allowed) == list(range(10))
    assert all(0 < decision.reset_seconds <= 60 for decision in denied)


async def test_multi_rule_policies_are_atomic(redis_client: Redis, redis_keys: RedisKeyBuilder) -> None:
    policy = RateLimitPolicy(
        "tests.multi",
        (RateLimitRule(3, 60, RateLimitScope.IP_IDENTIFIER), RateLimitRule(5, 60, RateLimitScope.IP)),
    )
    limiter = limiter_with(redis_client, redis_keys, policy)

    first_account = await asyncio.gather(
        *(limiter.check(policy, RateLimitIdentity(ip="203.0.113.11", identifier="a@example.com")) for _ in range(6))
    )
    second_account = await asyncio.gather(
        *(limiter.check(policy, RateLimitIdentity(ip="203.0.113.11", identifier="b@example.com")) for _ in range(6))
    )

    assert sum(1 for decision in first_account if decision is not None and decision.allowed) == 3
    assert sum(1 for decision in second_account if decision is not None and decision.allowed) == 2


async def test_window_slides_and_frees_capacity(redis_client: Redis, redis_keys: RedisKeyBuilder) -> None:
    policy = RateLimitPolicy("tests.sliding", (RateLimitRule(2, 1, RateLimitScope.IP),))
    limiter = limiter_with(redis_client, redis_keys, policy)
    identity = RateLimitIdentity(ip="203.0.113.12")

    results = [await limiter.check(policy, identity) for _ in range(3)]
    await asyncio.sleep(1.1)
    after_window = await limiter.check(policy, identity)

    assert [decision.allowed for decision in results if decision is not None] == [True, True, False]
    assert after_window is not None
    assert after_window.allowed


async def test_rate_limit_keys_expire_and_hide_subjects(redis_client: Redis, redis_keys: RedisKeyBuilder) -> None:
    policy = resolve_policies({})["test.limited"]
    limiter = limiter_with(redis_client, redis_keys, policy)

    await limiter.check(policy, RateLimitIdentity(ip="198.51.100.20"))

    key = redis_keys.key("ratelimit", policy.name, 0, hashed_subject(RateLimitScope.IP, "198.51.100.20"))
    assert "198.51.100.20" not in key
    assert await redis_client.zcard(key) == 1
    assert 0 < await redis_client.pttl(key) <= 10_000
