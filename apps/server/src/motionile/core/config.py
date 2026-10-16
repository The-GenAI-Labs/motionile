import base64
import binascii
import json
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Self
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, BeforeValidator, Field, SecretStr, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

LOCAL_DATABASE_URL = "postgresql://motionile:motionile@localhost:5432/motionile"
LOCAL_REDIS_URL = "redis://localhost:6379/0"
ASYNCPG_SCHEME = "postgresql+asyncpg"
PSYCOPG_SCHEME = "postgresql+psycopg"
LIBPQ_ONLY_PARAMETERS = frozenset({"channel_binding", "options", "target_session_attrs", "gssencmode"})
POSTGRES_SCHEMES = ("postgresql://", "postgres://")
DEVELOPMENT_CURSOR_SIGNING_SEED = "motionile-development-pagination-secret-not-for-production"
DEVELOPMENT_ENCRYPTION_KEY = base64.b64encode(b"motionile-dev-encryption-key-32b").decode()
AES_256_KEY_BYTES = 32
MINIMUM_SECRET_LENGTH = 32
MAX_KEY_ID_LENGTH = 64


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


def for_asyncpg(url: str) -> str:
    parts = urlsplit(with_driver(url, ASYNCPG_SCHEME))
    query: list[tuple[str, str]] = []
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        if name in LIBPQ_ONLY_PARAMETERS:
            continue
        query.append(("ssl" if name == "sslmode" else name, value))
    return urlunsplit(parts._replace(query=urlencode(query)))


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
        return for_asyncpg(self.url)

    @property
    def direct_async_url(self) -> str:
        return for_asyncpg(self.migration_url)

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


class AuthSettings(GroupSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_")

    jwt_keys: Annotated[dict[str, SecretStr], NoDecode] = Field(default_factory=dict[str, SecretStr])
    jwt_current_kid: str = Field(default="local", min_length=1, max_length=64)
    jwt_issuer: str = "https://api.motionile.local"
    jwt_audience: str = "motionile"
    test_access_seconds: int | None = Field(default=None, ge=10, le=900)
    cookie_domain: OptionalText = None
    web_origin: str = "http://localhost:3000"
    api_origin: str = "https://localhost:8000"
    otp_pepper: OptionalSecret = None
    csrf_secret: OptionalSecret = None
    hibp_enabled: bool = True
    google_client_id: OptionalText = None
    google_client_secret: OptionalSecret = None
    github_client_id: OptionalText = None
    github_client_secret: OptionalSecret = None
    microsoft_client_id: OptionalText = None
    microsoft_client_secret: OptionalSecret = None

    @field_validator("jwt_keys", mode="before")
    @classmethod
    def parse_keys(cls, value: object) -> object:
        return json.loads(value) if isinstance(value, str) and value.strip() else value

    @field_validator("jwt_keys")
    @classmethod
    def validate_signing_keys(cls, value: dict[str, SecretStr]) -> dict[str, SecretStr]:
        for kid, key in value.items():
            if not kid or len(kid) > MAX_KEY_ID_LENGTH:
                raise ValueError("JWT key IDs must contain 1 to 64 characters")
            try:
                raw = base64.b64decode(key.get_secret_value(), validate=True)
            except binascii.Error as error:
                raise ValueError("JWT keys must be base64 Ed25519 seeds") from error
            if len(raw) != AES_256_KEY_BYTES:
                raise ValueError("JWT keys must decode to 32-byte Ed25519 seeds")
        return value

    @model_validator(mode="after")
    def require_selected_key(self) -> Self:
        if self.jwt_keys and self.jwt_current_kid not in self.jwt_keys:
            raise ValueError("AUTH_JWT_CURRENT_KID must select a configured key")
        return self

    @field_validator("web_origin", "api_origin", "jwt_issuer")
    @classmethod
    def require_origin(cls, value: str) -> str:
        parts = urlsplit(value)
        if (
            parts.scheme not in {"http", "https"}
            or not parts.netloc
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or parts.path not in {"", "/"}
        ):
            raise ValueError("must be an HTTP(S) origin without credentials, path, query or fragment")
        return value.rstrip("/")

    @field_validator("otp_pepper", "csrf_secret")
    @classmethod
    def validate_secret(cls, value: SecretStr | None) -> SecretStr | None:
        return SecuritySettings.require_long_secret(value)

    def secret(self, purpose: str) -> bytes:
        selected = self.otp_pepper if purpose == "otp" else self.csrf_secret
        if selected is not None:
            return selected.get_secret_value().encode()
        return f"motionile-local-{purpose}-not-for-deployment".encode()

    @property
    def access_seconds(self) -> int:
        return self.test_access_seconds or 900


class NotificationSettings(GroupSettings):
    model_config = SettingsConfigDict(env_prefix="NOTIFICATIONS_")

    email_backend: str = Field(default="smtp", pattern="^(ses|smtp)$")
    sender: str = "Motionile <hello@motionile.local>"
    ses_region: str = "ap-south-1"
    smtp_host: str = "localhost"
    smtp_port: int = Field(default=1025, ge=1, le=65535)
    smtp_username: OptionalText = None
    smtp_password: OptionalSecret = None
    smtp_starttls: bool = False
    whatsapp_token: OptionalSecret = None
    whatsapp_phone_number_id: OptionalText = None
    whatsapp_template: str = "motionile_authentication"
    whatsapp_notice_template: str = "motionile_security_notice"
    ses_configuration_set: OptionalText = Field(default=None, validation_alias="SES_CONFIGURATION_SET")
    whatsapp_language: str = "en_US"
    whatsapp_api_version: str = "v23.0"


class Settings(BaseModel):
    model_config = {"frozen": True}

    auth: AuthSettings = Field(default_factory=AuthSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
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
        if self.auth.test_access_seconds is not None and (
            self.app.env not in TEST_ROUTE_ENVIRONMENTS or self.app.providers_mode is not ProvidersMode.FAKE
        ):
            raise ValueError("AUTH_TEST_ACCESS_SECONDS requires local or CI with fake providers")
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
        problems.extend(self.auth_deployment_problems())
        return problems

    def auth_deployment_problems(self) -> list[str]:
        required = {
            "AUTH_JWT_KEYS": self.auth.jwt_keys,
            "AUTH_OTP_PEPPER": self.auth.otp_pepper,
            "AUTH_CSRF_SECRET": self.auth.csrf_secret,
            "AUTH_COOKIE_DOMAIN": self.auth.cookie_domain,
            "AUTH_GOOGLE_CLIENT_ID": self.auth.google_client_id,
            "AUTH_GOOGLE_CLIENT_SECRET": self.auth.google_client_secret,
            "AUTH_GITHUB_CLIENT_ID": self.auth.github_client_id,
            "AUTH_GITHUB_CLIENT_SECRET": self.auth.github_client_secret,
            "AUTH_MICROSOFT_CLIENT_ID": self.auth.microsoft_client_id,
            "AUTH_MICROSOFT_CLIENT_SECRET": self.auth.microsoft_client_secret,
            "NOTIFICATIONS_WHATSAPP_TOKEN": self.notifications.whatsapp_token,
            "NOTIFICATIONS_WHATSAPP_PHONE_NUMBER_ID": self.notifications.whatsapp_phone_number_id,
        }
        problems = [f"{name} must be set" for name, value in required.items() if not value]
        if self.auth.jwt_current_kid not in self.auth.jwt_keys:
            problems.append("AUTH_JWT_CURRENT_KID must select a configured key")
        for name in ("web_origin", "api_origin", "jwt_issuer"):
            value: str = getattr(self.auth, name)
            if name not in self.auth.model_fields_set or not value.startswith("https://"):
                problems.append(f"AUTH_{name.upper()} must be explicitly set to https")
        if self.auth.web_origin not in self.cors.allowed_origins:
            problems.append("AUTH_WEB_ORIGIN must appear in CORS_ALLOWED_ORIGINS")
        if self.notifications.email_backend != "ses" or "sender" not in self.notifications.model_fields_set:
            problems.append("deployed email requires SES and an explicit NOTIFICATIONS_SENDER")
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
