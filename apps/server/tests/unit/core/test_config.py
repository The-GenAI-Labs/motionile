import pytest
from pydantic import ValidationError

from motionile.core.config import (
    LOCAL_DATABASE_URL,
    PSYCOPG_SCHEME,
    AppEnv,
    LogLevel,
    ProvidersMode,
    Settings,
    get_settings,
    with_driver,
)

DEPLOYED_DATABASE_URL = "postgresql://app:secret@db.internal:5432/motionile"
DEPLOYED_REDIS_URL = "redis://:secret@redis.internal:6379/0"


def test_defaults_target_local_development() -> None:
    settings = Settings()

    assert settings.app_env is AppEnv.LOCAL
    assert settings.providers_mode is ProvidersMode.FAKE
    assert settings.database_url == LOCAL_DATABASE_URL
    assert settings.log_level is LogLevel.INFO
    assert settings.allowed_origins == ()
    assert settings.is_local


def test_reads_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "ci")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://motionile.com/, https://www.motionile.com")

    settings = Settings()

    assert settings.app_env is AppEnv.CI
    assert settings.log_level is LogLevel.DEBUG
    assert settings.allowed_origins == ("https://motionile.com", "https://www.motionile.com")
    assert not settings.is_local


def test_rejects_non_postgres_database_url() -> None:
    with pytest.raises(ValidationError, match="postgresql"):
        Settings(database_url="mysql://localhost/motionile")


def test_migration_url_prefers_direct_connection() -> None:
    settings = Settings(
        database_url="postgresql://pooled.example/motionile",
        database_direct_url="postgresql://direct.example/motionile",
    )

    assert settings.migration_database_url == "postgresql://direct.example/motionile"
    assert settings.sqlalchemy_migration_url == "postgresql+psycopg://direct.example/motionile"


def test_migration_url_falls_back_to_database_url() -> None:
    settings = Settings(database_url="postgres://pooled.example/motionile")

    assert settings.sqlalchemy_migration_url == "postgresql+psycopg://pooled.example/motionile"


def test_replaces_url_scheme_with_driver() -> None:
    assert with_driver("postgresql://u:p@h:5432/d", PSYCOPG_SCHEME) == "postgresql+psycopg://u:p@h:5432/d"


@pytest.mark.parametrize("app_env", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_deployed_environments_require_explicit_connections(app_env: AppEnv) -> None:
    with pytest.raises(ValidationError, match="must be set explicitly"):
        Settings(app_env=app_env, providers_mode=ProvidersMode.LIVE)


@pytest.mark.parametrize("app_env", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_deployed_environments_require_live_providers(app_env: AppEnv) -> None:
    with pytest.raises(ValidationError, match="providers_mode must be live"):
        Settings(
            app_env=app_env,
            database_url=DEPLOYED_DATABASE_URL,
            redis_url=DEPLOYED_REDIS_URL,
            allowed_origins=("https://motionile.com",),
        )


def test_deployed_environment_accepts_complete_configuration() -> None:
    settings = Settings(
        app_env=AppEnv.PRODUCTION,
        providers_mode=ProvidersMode.LIVE,
        database_url=DEPLOYED_DATABASE_URL,
        redis_url=DEPLOYED_REDIS_URL,
        allowed_origins=("https://motionile.com",),
    )

    assert settings.app_env is AppEnv.PRODUCTION


def test_settings_are_immutable() -> None:
    settings = Settings()
    field_name = "app_env"

    with pytest.raises(ValidationError):
        setattr(settings, field_name, AppEnv.CI)


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
