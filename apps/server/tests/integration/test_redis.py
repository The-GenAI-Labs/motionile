from redis.asyncio import Redis

PROBE_KEY = "motionile:integration:probe"


async def test_redis_accepts_commands_with_expiry(redis_client: Redis) -> None:
    await redis_client.set(PROBE_KEY, "ok", ex=30)

    assert await redis_client.get(PROBE_KEY) == b"ok"
    assert 0 < await redis_client.ttl(PROBE_KEY) <= 30
