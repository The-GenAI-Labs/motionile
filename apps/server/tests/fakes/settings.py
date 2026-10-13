import base64

from pydantic import SecretStr

from motionile.core.config import (
    AppEnv,
    AppSettings,
    CorsSettings,
    DatabaseSettings,
    EncryptionSettings,
    ProvidersMode,
    RateLimitSettings,
    RedisSettings,
    SecuritySettings,
    Settings,
    StorageSettings,
    TurnstileSettings,
)

STRONG_SECRET = SecretStr("s" * 48)
ENCRYPTION_KEY = SecretStr(base64.b64encode(b"k" * 32).decode())


def make_settings(
    env: AppEnv = AppEnv.CI,
    *,
    rate_limiting: bool = False,
    providers_mode: ProvidersMode = ProvidersMode.FAKE,
) -> Settings:
    return Settings(
        app=AppSettings(env=env, providers_mode=providers_mode),
        rate_limit=RateLimitSettings(enabled=rate_limiting),
    )


def deployed_settings(env: AppEnv = AppEnv.PRODUCTION) -> Settings:
    return Settings(
        app=AppSettings(env=env, providers_mode=ProvidersMode.LIVE),
        database=DatabaseSettings(url="postgresql://app@db.internal/motionile"),
        redis=RedisSettings(url="rediss://:secret@redis.internal:6379/0"),
        cors=CorsSettings(allowed_origins=("https://motionile.com",)),
        security=SecuritySettings(pagination_secret=STRONG_SECRET),
        encryption=EncryptionSettings(keys={1: ENCRYPTION_KEY}),
        turnstile=TurnstileSettings(secret_key=SecretStr("turnstile-secret")),
        storage=StorageSettings(bucket="motionile-production"),
        rate_limit=RateLimitSettings(enabled=False),
    )
