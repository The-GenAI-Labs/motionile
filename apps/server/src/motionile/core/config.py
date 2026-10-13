import base64
import binascii
import json
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Self

from pydantic import BaseModel, BeforeValidator, Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LOCAL_DATABASE_URL = "postgresql://motionile:motionile@localhost:5432/motionile"
LOCAL_REDIS_URL = "redis://localhost:6379/0"
ASYNCPG_SCHEME = "postgresql+asyncpg"
PSYCOPG_SCHEME = "postgresql+psycopg"
POSTGRES_SCHEMES = ("postgresql://", "postgres://")
DEVELOPMENT_CURSOR_SIGNING_SEED = "motionile-development-pagination-secret-not-for-production"
DEVELOPMENT_ENCRYPTION_KEY = base64.b64encode(b"motionile-dev-encryption-key-32b").decode()
AES_256_KEY_BYTES = 32
MINIMUM_SECRET_LENGTH = 32


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
TEST_ROUTE_ENVIRONMENTS = frozenset({AppEnv.LOCAL, AppEnv.CI})


def with_driver(url: str, scheme: str) -> str:
    _, _, remainder = url.partition("://")
    return f"{scheme}://{remainder}"


def split_csv(value: object) -> object:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return value


def blank_as_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


type OptionalSecret = Annotated[SecretStr | None, BeforeValidator(blank_as_none)]
type OptionalText = Annotated[str | None, BeforeValidator(blank_as_none)]


class GroupSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        validate_by_name=True,
        validate_by_alias=True,
    )


class AppSettings(GroupSettings):
    env: AppEnv = Field(default=AppEnv.LOCAL, validation_alias="APP_ENV")
    providers_mode: ProvidersMode = Field(default=ProvidersMode.FAKE, validation_alias="PROVIDERS_MODE")


class DatabaseSettings(GroupSettings):
    model_config = SettingsConfigDict(env_prefix="DATABASE_")

    url: str = Field(default=LOCAL_DATABASE_URL, min_length=1)
    direct_url: OptionalText = None
    pool_size: int = Field(default=10, ge=1, le=100)
    max_overflow: int = Field(default=10, ge=0, le=100)
    pool_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    pool_recycle_seconds: int = Field(default=1800, ge=60)
    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    statement_cache_size: int = Field(default=100, ge=0)
    health_timeout_seconds: float = Field(default=2.0, gt=0, le=10)

    @field_validator("url", "direct_url")
    @classmethod
    def require_postgres_scheme(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith(POSTGRES_SCHEMES):
            message = "must be a postgresql:// connection URL"
            raise ValueError(message)
        return value

    @property
    def migration_url(self) -> str:
        return self.direct_url or self.url

    @property
    def async_url(self) -> str:
        return with_driver(self.url, ASYNCPG_SCHEME)

    @property
    def direct_async_url(self) -> str:
        return with_driver(self.migration_url, ASYNCPG_SCHEME)

    @property
    def sqlalchemy_migration_url(self) -> str:
        return with_driver(self.migration_url, PSYCOPG_SCHEME)


class RedisSettings(GroupSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_")

    url: str = Field(default=LOCAL_REDIS_URL, min_length=1)
    key_prefix: str = Field(default="mo", pattern=r"^[a-z][a-z0-9_]{0,15}$")
    socket_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    health_timeout_seconds: float = Field(default=1.0, gt=0, le=10)

    @field_validator("url")
    @classmethod
    def require_redis_scheme(cls, value: str) -> str:
        if not value.startswith(("redis://", "rediss://")):
            message = "must be a redis:// or rediss:// URL"
            raise ValueError(message)
        return value


class SecuritySettings(GroupSettings):
    model_config = SettingsConfigDict(env_prefix="SECURITY_")

    pagination_secret: OptionalSecret = None
    hsts_max_age_seconds: int = Field(default=63_072_000, ge=0)
    idempotency_ttl_seconds: int = Field(default=86_400, ge=60)
    idempotency_lock_seconds: int = Field(default=30, ge=1, le=600)
    require_origin_on_unsafe_methods: bool = False

    @field_validator("pagination_secret")
    @classmethod
    def require_long_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value()) < MINIMUM_SECRET_LENGTH:
            message = f"must be at least {MINIMUM_SECRET_LENGTH} characters"
            raise ValueError(message)
        return value


class CorsSettings(GroupSettings):
    model_config = SettingsConfigDict(env_prefix="CORS_")

    allowed_origins: Annotated[tuple[str, ...], NoDecode] = ("http://localhost:3000",)
    max_age_seconds: int = Field(default=600, ge=0, le=86_400)
    origin_guard_exempt_prefixes: Annotated[tuple[str, ...], NoDecode] = ("/v1/webhooks",)

    @field_validator("allowed_origins", "origin_guard_exempt_prefixes", mode="before")
    @classmethod
    def parse_lists(cls, value: object) -> object:
        return split_csv(value)

    @field_validator("allowed_origins")
    @classmethod
    def normalize_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(origin.rstrip("/") for origin in value)
        for origin in normalized:
            if origin == "*" or "*" in origin:
                message = "wildcard origins are not allowed"
                raise ValueError(message)
            if not origin.startswith(("https://", "http://")):
                message = f"origin {origin!r} must start with http:// or https://"
                raise ValueError(message)
        return normalized


class RateLimitRuleOverride(BaseModel):
    limit: int = Field(ge=1)
    window_seconds: int = Field(ge=1)


class RateLimitSettings(GroupSettings):
    model_config = SettingsConfigDict(env_prefix="RATE_LIMIT_")

    enabled: bool = True
    overrides: Annotated[dict[str, list[RateLimitRuleOverride]], NoDecode] = Field(
        default_factory=dict[str, list[RateLimitRuleOverride]]
    )

    @field_validator("overrides", mode="before")
    @classmethod
    def parse_json(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value) if value.strip() else {}
        return value


class StorageSettings(GroupSettings):
    model_config = SettingsConfigDict(env_prefix="STORAGE_")

    endpoint_url: OptionalText = "http://localhost:9000"
    region: str = "ap-south-1"
    bucket: str = Field(default="motionile-local", min_length=3, max_length=63)
    access_key_id: OptionalSecret = None
    secret_access_key: OptionalSecret = None
    force_path_style: bool = True
    presign_ttl_seconds: int = Field(default=900, ge=60, le=604_800)


class TurnstileSettings(GroupSettings):
    model_config = SettingsConfigDict(env_prefix="TURNSTILE_")

    secret_key: OptionalSecret = None
    expected_hostnames: Annotated[tuple[str, ...], NoDecode] = ("localhost",)
    verify_url: str = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    timeout_seconds: float = Field(default=5.0, gt=0, le=30)

    @field_validator("expected_hostnames", mode="before")
    @classmethod
    def parse_list(cls, value: object) -> object:
        return split_csv(value)


class EncryptionSettings(GroupSettings):
    model_config = SettingsConfigDict(env_prefix="ENCRYPTION_")

    keys: Annotated[dict[int, SecretStr], NoDecode] = Field(default_factory=dict[int, SecretStr])

    @field_validator("keys", mode="before")
    @classmethod
    def parse_json(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value) if value.strip() else {}
        return value

    @field_validator("keys")
    @classmethod
    def validate_keys(cls, value: dict[int, SecretStr], info: ValidationInfo) -> dict[int, SecretStr]:
        for version, key in value.items():
            if version < 1:
                message = f"{info.field_name} versions must be positive integers"
                raise ValueError(message)
            try:
                decoded = base64.b64decode(key.get_secret_value(), validate=True)
            except binascii.Error as error:
                message = f"key version {version} is not valid base64"
                raise ValueError(message) from error
            if len(decoded) != AES_256_KEY_BYTES:
                message = f"key version {version} must decode to {AES_256_KEY_BYTES} bytes"
                raise ValueError(message)
        return value


class LoggingSettings(GroupSettings):
    model_config = SettingsConfigDict(env_prefix="LOG_")

    level: LogLevel = LogLevel.INFO
    access_log: bool = True


class OutboundHttpSettings(GroupSettings):
    model_config = SettingsConfigDict(env_prefix="OUTBOUND_HTTP_")

    connect_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    read_timeout_seconds: float = Field(default=15.0, gt=0, le=300)
    max_response_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    max_redirects: int = Field(default=5, ge=0, le=10)


class Settings(BaseModel):
    model_config = {"frozen": True}

    app: AppSettings = Field(default_factory=AppSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    cors: CorsSettings = Field(default_factory=CorsSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    turnstile: TurnstileSettings = Field(default_factory=TurnstileSettings)
    encryption: EncryptionSettings = Field(default_factory=EncryptionSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    outbound_http: OutboundHttpSettings = Field(default_factory=OutboundHttpSettings)

    @model_validator(mode="after")
    def require_safe_values_when_deployed(self) -> Self:
        if self.app.env not in DEPLOYED_ENVIRONMENTS:
            return self
        problems = list(self.deployment_problems())
        if problems:
            message = f"unsafe configuration for {self.app.env}: " + "; ".join(problems)
            raise ValueError(message)
        return self

    def deployment_problems(self) -> list[str]:
        problems: list[str] = []
        if self.app.providers_mode is not ProvidersMode.LIVE:
            problems.append("PROVIDERS_MODE must be live")
        if "url" not in self.database.model_fields_set:
            problems.append("DATABASE_URL must be set")
        if "url" not in self.redis.model_fields_set:
            problems.append("REDIS_URL must be set")
        if "allowed_origins" not in self.cors.model_fields_set or not self.cors.allowed_origins:
            problems.append("CORS_ALLOWED_ORIGINS must be set")
        if any(origin.startswith("http://") for origin in self.cors.allowed_origins):
            problems.append("CORS_ALLOWED_ORIGINS must use https")
        if self.security.pagination_secret is None:
            problems.append("SECURITY_PAGINATION_SECRET must be set")
        if not self.encryption.keys:
            problems.append("ENCRYPTION_KEYS must be set")
        if self.turnstile.secret_key is None:
            problems.append("TURNSTILE_SECRET_KEY must be set")
        if "bucket" not in self.storage.model_fields_set:
            problems.append("STORAGE_BUCKET must be set")
        return problems

    @property
    def is_local(self) -> bool:
        return self.app.env is AppEnv.LOCAL

    @property
    def is_fake_providers(self) -> bool:
        return self.app.providers_mode is ProvidersMode.FAKE

    @property
    def test_routes_enabled(self) -> bool:
        return self.app.env in TEST_ROUTE_ENVIRONMENTS

    @property
    def pagination_secret(self) -> bytes:
        secret = self.security.pagination_secret
        value = secret.get_secret_value() if secret is not None else DEVELOPMENT_CURSOR_SIGNING_SEED
        return value.encode()

    @property
    def encryption_keys(self) -> dict[int, bytes]:
        if not self.encryption.keys:
            return {1: base64.b64decode(DEVELOPMENT_ENCRYPTION_KEY)}
        return {version: base64.b64decode(key.get_secret_value()) for version, key in self.encryption.keys.items()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
