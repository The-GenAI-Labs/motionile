from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID

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
from tests.integration.billing_support import (
    PROCESS_TASK_NAME,
    BillingApi,
    Recorded,
    client_for,
    create_product,
    purge_billing_data,
)
from tests.integration.credit_support import new_clock
from tests.integration.test_auth import signup

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
from motionile.core.db import Database, after_commit
from motionile.core.ids import new_id
from motionile.core.redis import RedisKeyBuilder, create_redis_client
from motionile.core.resources import Resources, build_resources
from motionile.entrypoints.api import create_app
from motionile.modules.auth import AuthRuntime
from motionile.modules.auth import service as auth_module
from motionile.modules.billing.dependencies import get_billing_services
from motionile.modules.billing.services.factory import ServiceHooks, build_services
from motionile.modules.credits import CreditsService
from motionile.modules.notifications import FakeDelivery, Notification

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


PRIMARY_EMAIL = "billing-primary@example.com"
OTHER_EMAIL = "billing-other@example.com"


@pytest.fixture
async def billing_api(resources: Resources, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[BillingApi]:
    resources.rate_limiter.enabled = False
    clock = new_clock()
    resources.clock = clock
    inbox = FakeDelivery(resources.redis_store)

    def enqueue(fake_resources: Resources, session: AsyncSession, message: Notification) -> None:
        del fake_resources

        async def deliver() -> None:
            await inbox.record(message)

        after_commit(session, deliver)

    monkeypatch.setattr(auth_module, "enqueue_notification", enqueue)
    recorded = Recorded()
    services = build_services(
        resources,
        ServiceHooks(
            dispatch=recorded.dispatch,
            process_task_name=PROCESS_TASK_NAME,
            receipts=recorded.receipt,
            alert=recorded.alert,
        ),
    )
    app = create_app(resources.settings, resources=resources)
    app.state.auth_runtime = AuthRuntime(resources)
    app.dependency_overrides[get_billing_services] = lambda: services
    pack_code = f"pack_{new_id().hex[:12]}"
    counter = 0

    def next_key() -> str:
        nonlocal counter
        counter += 1
        return f"billing-test-{new_id().hex}-{counter}"

    await create_product(resources.database, pack_code)
    async with client_for(app) as primary, client_for(app) as other, client_for(app) as anonymous:
        primary_id = UUID(await signup(primary, PRIMARY_EMAIL))
        other_id = UUID(await signup(other, OTHER_EMAIL))
        yield BillingApi(
            app=app,
            resources=resources,
            services=services,
            recorded=recorded,
            clock=clock,
            credits=CreditsService(clock, resources.settings.billing),
            primary=primary,
            other=other,
            anonymous=anonymous,
            primary_id=primary_id,
            other_id=other_id,
            pack_code=pack_code,
            keys=next_key,
        )
    await purge_billing_data(resources.database, [primary_id, other_id])
