from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.community.minio import MinioContainer
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

from motionile.core.config import (
    PSYCOPG_SCHEME,
    AppEnv,
    AppSettings,
    DatabaseSettings,
    RateLimitSettings,
    RedisSettings,
    Settings,
    StorageSettings,
    with_driver,
)
from motionile.core.db import Database
from motionile.core.redis import RedisKeyBuilder, create_redis_client
from motionile.core.resources import Resources, build_resources

POSTGRES_IMAGE = "pgvector/pgvector:0.8.7-pg17-trixie"
REDIS_IMAGE = "redis:8.10.2-alpine"
MINIO_IMAGE = "pgsty/minio:RELEASE.2026-08-04T00-00-00Z"
MINIO_ACCESS_KEY = "motionile"
MINIO_SECRET_KEY = "motionile-integration-secret"  # noqa: S105
TEST_BUCKET = "motionile-integration"
SERVER_ROOT = Path(__file__).resolve().parents[2]
APPLICATION_NAME = "motionile-integration"
MUTABLE_TABLES = ("idempotency_records",)


async def flush_redis(client: Redis) -> None:
    await client.eval("return redis.call('FLUSHDB')", 0)


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    with PostgresContainer(POSTGRES_IMAGE, driver=None) as container:
        yield container


@pytest.fixture(scope="session")
def redis_container() -> Iterator[RedisContainer]:
    with RedisContainer(REDIS_IMAGE) as container:
        yield container


@pytest.fixture(scope="session")
def minio_container() -> Iterator[MinioContainer]:
    container = (
        MinioContainer(MINIO_IMAGE, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY)
        .with_env("MINIO_ROOT_USER", MINIO_ACCESS_KEY)
        .with_env("MINIO_ROOT_PASSWORD", MINIO_SECRET_KEY)
    )
    with container:
        yield container


@pytest.fixture(scope="session")
def database_url(postgres_container: PostgresContainer) -> str:
    return postgres_container.get_connection_url()


def alembic_config_for(url: str) -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.attributes["database_url"] = url
    return config


@pytest.fixture(scope="session")
def migrated_database_url(database_url: str) -> str:
    command.upgrade(alembic_config_for(database_url), "head")
    return database_url


@pytest.fixture(scope="session")
def scratch_database_url(database_url: str) -> str:
    engine = create_engine(with_driver(database_url, PSYCOPG_SCHEME), isolation_level="AUTOCOMMIT")
    with engine.connect() as connection:
        connection.execute(text("CREATE DATABASE migration_check"))
    engine.dispose()
    return database_url.rsplit("/", 1)[0] + "/migration_check"


@pytest.fixture(scope="session")
def redis_url(redis_container: RedisContainer) -> str:
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(redis_container.port)
    return f"redis://{host}:{port}/0"


@pytest.fixture(scope="session")
def minio_endpoint(minio_container: MinioContainer) -> str:
    host = minio_container.get_container_host_ip()
    port = minio_container.get_exposed_port(minio_container.port)
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def settings(migrated_database_url: str, redis_url: str, minio_endpoint: str) -> Settings:
    return Settings(
        app=AppSettings(env=AppEnv.CI),
        database=DatabaseSettings(url=migrated_database_url, pool_size=20, max_overflow=20),
        redis=RedisSettings(url=redis_url, key_prefix="itest"),
        storage=StorageSettings(
            endpoint_url=minio_endpoint,
            bucket=TEST_BUCKET,
            access_key_id=SecretStr(MINIO_ACCESS_KEY),
            secret_access_key=SecretStr(MINIO_SECRET_KEY),
        ),
        rate_limit=RateLimitSettings(enabled=True),
    )


@pytest.fixture
async def resources(settings: Settings) -> AsyncIterator[Resources]:
    built = build_resources(settings, application_name=APPLICATION_NAME)
    await flush_redis(built.redis)
    yield built
    async with built.database.transaction() as session:
        for table in MUTABLE_TABLES:
            await session.execute(text(f"TRUNCATE {table}"))
    await built.aclose()


@pytest.fixture
def database(resources: Resources) -> Database:
    return resources.database


@pytest.fixture
async def rolled_back_session(database: Database) -> AsyncIterator[AsyncSession]:
    async with database.engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
        yield session
        await session.close()
        await transaction.rollback()


@pytest.fixture
async def redis_client(settings: Settings) -> AsyncIterator[Redis]:
    client = create_redis_client(settings.redis)
    await flush_redis(client)
    yield client
    await client.aclose()


@pytest.fixture
def redis_keys(settings: Settings) -> RedisKeyBuilder:
    return RedisKeyBuilder(settings.redis.key_prefix)
