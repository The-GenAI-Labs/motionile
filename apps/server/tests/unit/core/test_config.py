import base64

import pytest
from pydantic import SecretStr, ValidationError
from tests.fakes.settings import ENCRYPTION_KEY, STRONG_SECRET
from tests.fakes.settings import deployed_settings as deployed

from motionile.core.config import (
    LOCAL_DATABASE_URL,
    AppEnv,
    AppSettings,
    CorsSettings,
    DatabaseSettings,
    EncryptionSettings,
    LogLevel,
    ProvidersMode,
    RateLimitSettings,
    RedisSettings,
    SecuritySettings,
    Settings,
    for_asyncpg,
    get_settings,
    with_driver,
)


def test_defaults_target_local_development() -> None:
    settings = Settings()

    assert settings.app.env is AppEnv.LOCAL
    assert settings.app.providers_mode is ProvidersMode.FAKE
    assert settings.database.url == LOCAL_DATABASE_URL
    assert settings.logging.level is LogLevel.INFO
    assert settings.cors.allowed_origins == ("http://localhost:3000",)
    assert settings.is_local
    assert settings.is_fake_providers
    assert settings.test_routes_enabled


def test_reads_grouped_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "ci")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://motionile.com/, https://www.motionile.com")
    monkeypatch.setenv("DATABASE_POOL_SIZE", "4")
    monkeypatch.setenv("RATE_LIMIT_OVERRIDES", '{"jobs.create": [{"limit": 9, "window_seconds": 30}]}')
    monkeypatch.setenv("ENCRYPTION_KEYS", f'{{"2": "{ENCRYPTION_KEY.get_secret_value()}"}}')

    settings = Settings()

    assert settings.app.env is AppEnv.CI
    assert settings.logging.level is LogLevel.DEBUG
    assert settings.cors.allowed_origins == ("https://motionile.com", "https://www.motionile.com")
    assert settings.database.pool_size == 4
    assert settings.rate_limit.overrides["jobs.create"][0].limit == 9
    assert settings.encryption_keys == {2: b"k" * 32}


@pytest.mark.parametrize("origin", ["*", "https://*.motionile.com", "motionile.com"])
def test_rejects_wildcard_or_schemeless_origins(origin: str) -> None:
    with pytest.raises(ValidationError):
        CorsSettings(allowed_origins=(origin,))


def test_rejects_non_postgres_database_url() -> None:
    with pytest.raises(ValidationError, match="postgresql"):
        DatabaseSettings(url="mysql://localhost/motionile")


def test_rejects_non_redis_url() -> None:
    with pytest.raises(ValidationError, match="redis"):
        RedisSettings(url="http://localhost:6379")


def test_database_urls_use_the_right_drivers() -> None:
    database = DatabaseSettings(
        url="postgresql://pooled.example/motionile",
        direct_url="postgresql://direct.example/motionile",
    )

    assert database.async_url == "postgresql+asyncpg://pooled.example/motionile"
    assert database.direct_async_url == "postgresql+asyncpg://direct.example/motionile"
    assert database.sqlalchemy_migration_url == "postgresql+psycopg://direct.example/motionile"


def test_blank_direct_url_is_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_DIRECT_URL", "")

    assert DatabaseSettings().direct_url is None
    assert DatabaseSettings().migration_url == LOCAL_DATABASE_URL


def test_with_driver_replaces_scheme() -> None:
    assert with_driver("postgres://u:p@h/d", "postgresql+psycopg") == "postgresql+psycopg://u:p@h/d"


def test_short_pagination_secret_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        SecuritySettings(pagination_secret=SecretStr("short"))


@pytest.mark.parametrize("key", ["not-base64!", base64.b64encode(b"too-short").decode()])
def test_invalid_encryption_keys_are_rejected(key: str) -> None:
    with pytest.raises(ValidationError):
        EncryptionSettings(keys={1: SecretStr(key)})


def test_non_positive_encryption_key_version_is_rejected() -> None:
    with pytest.raises(ValidationError, match="positive"):
        EncryptionSettings(keys={0: ENCRYPTION_KEY})


def test_local_environment_falls_back_to_development_secrets() -> None:
    settings = Settings()

    assert len(settings.pagination_secret) >= 32
    assert set(settings.encryption_keys) == {1}
    assert len(settings.encryption_keys[1]) == 32


@pytest.mark.parametrize("env", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_deployed_environments_accept_complete_configuration(env: AppEnv) -> None:
    settings = deployed(env)

    assert settings.deployment_problems() == []
    assert not settings.test_routes_enabled
    assert settings.pagination_secret == STRONG_SECRET.get_secret_value().encode()


@pytest.mark.parametrize("env", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_deployed_environments_reject_unsafe_defaults(env: AppEnv) -> None:
    with pytest.raises(ValidationError) as raised:
        Settings(app=AppSettings(env=env))

    message = str(raised.value)
    for problem in (
        "PROVIDERS_MODE must be live",
        "DATABASE_URL must be set",
        "REDIS_URL must be set",
        "CORS_ALLOWED_ORIGINS must be set",
        "SECURITY_PAGINATION_SECRET must be set",
        "ENCRYPTION_KEYS must be set",
        "TURNSTILE_SECRET_KEY must be set",
        "STORAGE_BUCKET must be set",
    ):
        assert problem in message


def test_production_rejects_plain_http_origins() -> None:
    complete = deployed()

    with pytest.raises(ValidationError, match="must use https"):
        Settings.model_validate(
            {**complete.model_dump(), "cors": CorsSettings(allowed_origins=("http://motionile.com",))}
        )


def test_secrets_are_not_rendered() -> None:
    settings = deployed()

    assert "s" * 48 not in repr(settings)
    assert "turnstile-secret" not in str(settings.model_dump())


def test_rate_limit_overrides_accept_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_OVERRIDES", " ")

    assert RateLimitSettings().overrides == {}


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()


def test_blank_secrets_from_env_files_are_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("SECURITY_PAGINATION_SECRET", "TURNSTILE_SECRET_KEY", "STORAGE_ACCESS_KEY_ID", "STORAGE_ENDPOINT_URL"):
        monkeypatch.setenv(name, "  ")

    settings = Settings()

    assert settings.security.pagination_secret is None
    assert settings.turnstile.secret_key is None
    assert settings.storage.access_key_id is None
    assert settings.storage.endpoint_url is None


def test_asyncpg_urls_translate_libpq_parameters() -> None:
    neon = "postgresql://app:secret@ep-x-pooler.ap-southeast-1.aws.neon.tech/motionile?sslmode=require&channel_binding=require"

    assert for_asyncpg(neon) == (
        "postgresql+asyncpg://app:secret@ep-x-pooler.ap-southeast-1.aws.neon.tech/motionile?ssl=require"
    )
    assert for_asyncpg("postgresql://u@h/d") == "postgresql+asyncpg://u@h/d"


def test_database_settings_accept_neon_connection_strings_unchanged() -> None:
    database = DatabaseSettings(
        url="postgresql://app:pw@ep-x-pooler.example.neon.tech/motionile?sslmode=require&channel_binding=require",
        direct_url="postgresql://app:pw@ep-x.example.neon.tech/motionile?sslmode=require&channel_binding=require",
    )

    assert database.async_url.endswith("/motionile?ssl=require")
    assert database.direct_async_url == "postgresql+asyncpg://app:pw@ep-x.example.neon.tech/motionile?ssl=require"
    assert database.sqlalchemy_migration_url.endswith("?sslmode=require&channel_binding=require")
