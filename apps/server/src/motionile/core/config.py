from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Self

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LOCAL_DATABASE_URL = "postgresql://motionile:motionile@localhost:5432/motionile"
LOCAL_REDIS_URL = "redis://localhost:6379/0"
PSYCOPG_SCHEME = "postgresql+psycopg"
POSTGRES_SCHEMES = ("postgresql://", "postgres://")


class AppEnv(StrEnum):
    LOCAL = "local"
    CI = "ci"
    STAGING = "staging"
    PRODUCTION = "production"


class ProvidersMode(StrEnum):
    FAKE = "fake"
    LIVE = "live"


class LogLevel(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


DEPLOYED_ENVIRONMENTS = frozenset({AppEnv.STAGING, AppEnv.PRODUCTION})
REQUIRED_WHEN_DEPLOYED = frozenset({"database_url", "redis_url", "allowed_origins"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_env: AppEnv = AppEnv.LOCAL
    providers_mode: ProvidersMode = ProvidersMode.FAKE
    database_url: str = Field(default=LOCAL_DATABASE_URL, min_length=1)
    database_direct_url: str | None = None
    redis_url: str = Field(default=LOCAL_REDIS_URL, min_length=1)
    log_level: LogLevel = LogLevel.INFO
    allowed_origins: Annotated[tuple[str, ...], NoDecode] = ()

    @field_validator("database_direct_url", mode="before")
    @classmethod
    def treat_blank_as_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("database_url", "database_direct_url")
    @classmethod
    def require_postgres_scheme(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(POSTGRES_SCHEMES):
            message = "must be a postgresql:// connection URL"
            raise ValueError(message)
        return value

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(origin.strip().rstrip("/") for origin in value.split(",") if origin.strip())
        return value

    @model_validator(mode="after")
    def require_explicit_values_when_deployed(self) -> Self:
        if self.app_env in DEPLOYED_ENVIRONMENTS:
            missing = sorted(REQUIRED_WHEN_DEPLOYED - self.model_fields_set)
            if missing:
                message = f"{', '.join(missing)} must be set explicitly in {self.app_env}"
                raise ValueError(message)
            if self.providers_mode is not ProvidersMode.LIVE:
                message = f"providers_mode must be live in {self.app_env}"
                raise ValueError(message)
        return self

    @property
    def is_local(self) -> bool:
        return self.app_env is AppEnv.LOCAL

    @property
    def migration_database_url(self) -> str:
        return self.database_direct_url or self.database_url

    @property
    def sqlalchemy_migration_url(self) -> str:
        return with_driver(self.migration_database_url, PSYCOPG_SCHEME)


def with_driver(url: str, scheme: str) -> str:
    _, _, remainder = url.partition("://")
    return f"{scheme}://{remainder}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
