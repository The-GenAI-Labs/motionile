import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from motionile.core.config import PSYCOPG_SCHEME, get_settings, with_driver
from motionile.models import metadata

DATABASE_URL_ATTRIBUTE = "database_url"

config = context.config
target_metadata = metadata

if config.config_file_name is not None and DATABASE_URL_ATTRIBUTE not in config.attributes:
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def resolve_database_url() -> str:
    override: str | None = config.attributes.get(DATABASE_URL_ATTRIBUTE)
    if override is not None:
        return with_driver(override, PSYCOPG_SCHEME)
    return get_settings().database.sqlalchemy_migration_url


def run_migrations_offline() -> None:
    context.configure(
        url=resolve_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def apply_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(resolve_database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(apply_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
