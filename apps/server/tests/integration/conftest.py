from collections.abc import AsyncIterator, Iterator

import pytest
from redis.asyncio import Redis
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

POSTGRES_IMAGE = "pgvector/pgvector:0.8.7-pg17-trixie"
REDIS_IMAGE = "redis:8.10.2-alpine"


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as container:
        yield container


@pytest.fixture(scope="session")
def redis_container() -> Iterator[RedisContainer]:
    with RedisContainer(REDIS_IMAGE) as container:
        yield container


@pytest.fixture(scope="session")
def database_url(postgres_container: PostgresContainer) -> str:
    return postgres_container.get_connection_url()


@pytest.fixture
async def redis_client(redis_container: RedisContainer) -> AsyncIterator[Redis]:
    client = Redis(
        host=redis_container.get_container_host_ip(),
        port=int(redis_container.get_exposed_port(redis_container.port)),
    )
    yield client
    await client.aclose()
