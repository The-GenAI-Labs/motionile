import base64

import pytest
from pydantic import SecretStr, ValidationError
from tests.fakes.settings import ENCRYPTION_KEY, STRONG_SECRET
from tests.fakes.settings import deployed_settings as deployed

from motionile.core.config import (
    LOCAL_DATABASE_URL,
    AppEnv,
    AppRole,
    AppSettings,
    AuthSettings,
    BillingSettings,
    CatalogSettings,
    CorsSettings,
    DatabaseSettings,
    ElevenLabsSettings,
    EncryptionSettings,
    LogLevel,
    MediaDeliveryMode,
    MediaSettings,
    ProvidersMode,
    RateLimitSettings,
    RedisSettings,
    SecuritySettings,
    Settings,
    ShareSettings,
    StorageSettings,
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


@pytest.mark.parametrize("environment", [AppEnv.LOCAL, AppEnv.CI])
def test_short_access_lifetime_is_available_for_fake_browser_tests(environment: AppEnv) -> None:
    settings = Settings(app=AppSettings(env=environment), auth=AuthSettings(test_access_seconds=75))
    assert settings.auth.access_seconds == 75
    assert AuthSettings().access_seconds == 900


@pytest.mark.parametrize("environment", [AppEnv.STAGING, AppEnv.PRODUCTION])
def test_short_access_lifetime_is_rejected_when_deployed(environment: AppEnv) -> None:
    with pytest.raises(ValidationError, match="AUTH_TEST_ACCESS_SECONDS"):
        Settings(app=AppSettings(env=environment), auth=AuthSettings(test_access_seconds=75))


def test_short_access_lifetime_is_rejected_with_live_providers() -> None:
    with pytest.raises(ValidationError, match="AUTH_TEST_ACCESS_SECONDS"):
        Settings(app=AppSettings(providers_mode=ProvidersMode.LIVE), auth=AuthSettings(test_access_seconds=75))


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


def test_short_catalog_revalidation_secret_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        CatalogSettings(revalidation_secret=SecretStr("short"))


def test_short_share_internal_secret_is_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 32"):
        ShareSettings(internal_secret=SecretStr("short"))


def test_share_internal_secret_is_read_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHARE_INTERNAL_SECRET", "x" * 40)

    secret = Settings().share.internal_secret

    assert secret is not None
    assert secret.get_secret_value() == "x" * 40
    assert "x" * 40 not in repr(Settings().share)


def test_deployed_services_require_the_share_internal_secret() -> None:
    settings = deployed()
    assert settings.deployment_problems() == []

    missing = settings.model_copy(update={"share": ShareSettings()})

    assert missing.deployment_problems() == ["SHARE_INTERNAL_SECRET must be set"]


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
        "CATALOG_REVALIDATION_SECRET must be set",
        "SHARE_INTERNAL_SECRET must be set",
        "STORAGE_BUCKET must be set",
        "BILLING_RAZORPAY_KEY_ID must be set",
        "BILLING_RAZORPAY_KEY_SECRET must be set",
        "BILLING_RAZORPAY_WEBHOOK_SECRET must be set",
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
    for name in (
        "SECURITY_PAGINATION_SECRET",
        "TURNSTILE_SECRET_KEY",
        "STORAGE_ACCESS_KEY_ID",
        "STORAGE_ENDPOINT_URL",
        "CATALOG_REVALIDATION_SECRET",
        "SHARE_INTERNAL_SECRET",
        "BILLING_RAZORPAY_KEY_ID",
        "BILLING_RAZORPAY_KEY_SECRET",
        "BILLING_RAZORPAY_WEBHOOK_SECRET",
    ):
        monkeypatch.setenv(name, "  ")

    settings = Settings()

    assert settings.security.pagination_secret is None
    assert settings.turnstile.secret_key is None
    assert settings.storage.access_key_id is None
    assert settings.storage.endpoint_url is None
    assert settings.catalog.revalidation_secret is None
    assert settings.share.internal_secret is None
    assert settings.billing.razorpay_key_id is None
    assert settings.billing.razorpay_key_secret is None
    assert settings.billing.razorpay_webhook_secret is None


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


@pytest.mark.parametrize(
    "origin",
    ["https://example.com/path", "https://user:secret@example.com", "https://example.com?next=evil", "//example.com"],
)
def test_auth_origins_cannot_inject_redirect_components(origin: str) -> None:
    with pytest.raises(ValidationError):
        AuthSettings(web_origin=origin)


def test_auth_signing_key_must_be_selected() -> None:
    with pytest.raises(ValidationError, match="CURRENT_KID"):
        AuthSettings(jwt_keys={"new": ENCRYPTION_KEY}, jwt_current_kid="missing")


def test_billing_defaults_are_safe_for_local_development() -> None:
    billing = BillingSettings()

    assert billing.razorpay_key_id is None
    assert billing.razorpay_key_secret is None
    assert billing.razorpay_webhook_secret is None
    assert billing.razorpay_api_base_url == "https://api.razorpay.com"
    assert billing.order_expiry_seconds == 7_200
    assert billing.subscription_total_count == 120
    assert billing.expiry_reminder_lead_days == 7
    assert billing.reservation_ttl_seconds == 3_600
    assert billing.webhook_max_attempts == 10
    assert billing.reconciliation_pending_after_seconds == 1_800
    assert billing.report_storage_prefix == "billing/reconciliation"


def test_billing_reads_values_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BILLING_RAZORPAY_KEY_ID", "rzp_test_abc")
    monkeypatch.setenv("BILLING_RAZORPAY_KEY_SECRET", "key-secret")
    monkeypatch.setenv("BILLING_RAZORPAY_WEBHOOK_SECRET", "webhook-secret")
    monkeypatch.setenv("BILLING_RAZORPAY_API_BASE_URL", "https://api.razorpay.com/")
    monkeypatch.setenv("BILLING_ORDER_EXPIRY_SECONDS", "3600")
    monkeypatch.setenv("BILLING_REPORT_STORAGE_PREFIX", "billing/reports")

    billing = Settings().billing

    assert billing.razorpay_key_id == "rzp_test_abc"
    assert billing.razorpay_key_secret == SecretStr("key-secret")
    assert billing.razorpay_webhook_secret == SecretStr("webhook-secret")
    assert billing.razorpay_api_base_url == "https://api.razorpay.com"
    assert billing.order_expiry_seconds == 3_600
    assert billing.report_storage_prefix == "billing/reports"


def test_billing_secrets_are_not_rendered() -> None:
    billing = BillingSettings(razorpay_key_secret=SecretStr("very-secret-value"))

    assert "very-secret-value" not in repr(billing)
    assert "very-secret-value" not in str(billing.model_dump())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("order_expiry_seconds", 899),
        ("order_expiry_seconds", 86_401),
        ("subscription_total_count", 0),
        ("subscription_total_count", 1_001),
        ("expiry_reminder_lead_days", 0),
        ("expiry_reminder_lead_days", 61),
        ("reservation_ttl_seconds", 59),
        ("reservation_ttl_seconds", 86_401),
        ("webhook_max_attempts", 0),
        ("webhook_max_attempts", 51),
        ("reconciliation_pending_after_seconds", 59),
        ("reconciliation_pending_after_seconds", 86_401),
    ],
)
def test_billing_numeric_settings_are_bounded(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        BillingSettings.model_validate({field: value})


@pytest.mark.parametrize(
    "prefix", ["", "/billing", "billing/", "Billing", "billing//reports", "billing/../x", "a" * 101]
)
def test_billing_report_prefix_must_be_a_relative_key_prefix(prefix: str) -> None:
    with pytest.raises(ValidationError):
        BillingSettings(report_storage_prefix=prefix)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.razorpay.com",
        "https://user:pass@api.razorpay.com",
        "https://api.razorpay.com/v1",
        "https://api.razorpay.com?x=1",
        "api.razorpay.com",
    ],
)
def test_razorpay_base_url_must_be_a_plain_https_origin(url: str) -> None:
    with pytest.raises(ValidationError):
        BillingSettings(razorpay_api_base_url=url)


@pytest.mark.parametrize("missing", ["razorpay_key_id", "razorpay_key_secret", "razorpay_webhook_secret"])
def test_deployed_environments_require_each_razorpay_credential(missing: str) -> None:
    complete = deployed()
    settings = complete.model_copy(update={"billing": complete.billing.model_copy(update={missing: None})})

    problems = settings.billing_deployment_problems()

    assert problems == [f"BILLING_{missing.upper()} must be set"]


def test_deployed_environments_accept_complete_billing_configuration() -> None:
    assert deployed().billing_deployment_problems() == []


def render_worker_settings(**overrides: object) -> Settings:
    return Settings(
        app=AppSettings(env=AppEnv.PRODUCTION, providers_mode=ProvidersMode.LIVE, role=AppRole.RENDER_WORKER),
        elevenlabs=ElevenLabsSettings(api_key=STRONG_SECRET),
        media=MediaSettings(delivery_mode=MediaDeliveryMode.PRESIGNED),
        database=DatabaseSettings(url="postgresql://app@db.internal/motionile"),
        redis=RedisSettings(url="rediss://:secret@redis.internal:6379/0"),
        encryption=EncryptionSettings(keys={1: ENCRYPTION_KEY}),
        storage=StorageSettings(bucket="motionile-production"),
        rate_limit=RateLimitSettings(enabled=False),
    ).model_copy(update=overrides)


def test_a_render_worker_needs_no_auth_billing_turnstile_or_cdn_signing_secrets() -> None:
    settings = render_worker_settings()

    assert settings.deployment_problems() == []
    assert settings.app.role is AppRole.RENDER_WORKER


def test_a_service_process_still_requires_those_secrets() -> None:
    with pytest.raises(ValidationError) as raised:
        Settings(
            app=AppSettings(env=AppEnv.PRODUCTION, providers_mode=ProvidersMode.LIVE),
            database=DatabaseSettings(url="postgresql://app@db.internal/motionile"),
            redis=RedisSettings(url="rediss://:secret@redis.internal:6379/0"),
            encryption=EncryptionSettings(keys={1: ENCRYPTION_KEY}),
            storage=StorageSettings(bucket="motionile-production"),
            media=MediaSettings(delivery_mode=MediaDeliveryMode.PRESIGNED),
            elevenlabs=ElevenLabsSettings(api_key=STRONG_SECRET),
        )

    message = str(raised.value)
    for problem in (
        "TURNSTILE_SECRET_KEY must be set",
        "AUTH_JWT_KEYS must be set",
        "BILLING_RAZORPAY_KEY_ID must be set",
    ):
        assert problem in message


def test_a_render_worker_keeps_the_storage_encryption_and_provider_requirements() -> None:
    with pytest.raises(ValidationError) as raised:
        Settings(app=AppSettings(env=AppEnv.PRODUCTION, role=AppRole.RENDER_WORKER))

    message = str(raised.value)
    for problem in (
        "PROVIDERS_MODE must be live",
        "DATABASE_URL must be set",
        "REDIS_URL must be set",
        "ENCRYPTION_KEYS must be set",
        "STORAGE_BUCKET must be set",
        "ELEVENLABS_API_KEY must be set",
        "MEDIA_DELIVERY_MODE must be set",
    ):
        assert problem in message
    assert "TURNSTILE_SECRET_KEY" not in message
    assert "AUTH_JWT_KEYS" not in message


def test_a_render_worker_in_cloudfront_mode_does_not_need_the_signing_key_but_the_service_does() -> None:
    media = {
        "MEDIA_DELIVERY_MODE": "cloudfront",
        "CDN_DOMAIN": "cdn.motionile.com",
        "CLOUDFRONT_KEY_PAIR_ID": "K1",
        "MEDIA_COOKIE_DOMAIN": ".motionile.com",
    }
    worker = render_worker_settings(media=MediaSettings.model_validate(media))
    service = deployed().model_copy(update={"media": MediaSettings.model_validate(media)})

    assert worker.media_deployment_problems() == []
    assert service.media_deployment_problems() == ["CLOUDFRONT_PRIVATE_KEY must be set"]
