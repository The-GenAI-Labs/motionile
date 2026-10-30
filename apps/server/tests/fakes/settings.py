import base64

from pydantic import SecretStr

from motionile.core.config import (
    AiSettings,
    AppEnv,
    AppSettings,
    AuthSettings,
    BillingSettings,
    CatalogSettings,
    CorsSettings,
    DatabaseSettings,
    ElevenLabsSettings,
    EncryptionSettings,
    MediaDeliveryMode,
    MediaSettings,
    NotificationSettings,
    OpenAISettings,
    ProvidersMode,
    RateLimitSettings,
    RedisSettings,
    SecuritySettings,
    Settings,
    ShareSettings,
    StorageSettings,
    TurnstileSettings,
)

STRONG_SECRET = SecretStr("s" * 48)
SHARE_INTERNAL_SECRET = "integration-share-internal-secret-0123456789"  # noqa: S105
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
        auth=AuthSettings(
            jwt_keys={"current": ENCRYPTION_KEY},
            jwt_current_kid="current",
            jwt_issuer="https://api.motionile.com",
            web_origin="https://motionile.com",
            api_origin="https://api.motionile.com",
            cookie_domain=".motionile.com",
            otp_pepper=STRONG_SECRET,
            csrf_secret=STRONG_SECRET,
            google_client_id="google",
            google_client_secret=STRONG_SECRET,
            github_client_id="github",
            github_client_secret=STRONG_SECRET,
            microsoft_client_id="microsoft",
            microsoft_client_secret=STRONG_SECRET,
        ),
        catalog=CatalogSettings(revalidation_secret=STRONG_SECRET),
        share=ShareSettings(internal_secret=STRONG_SECRET),
        billing=BillingSettings(
            razorpay_key_id="rzp_live_key",
            razorpay_key_secret=STRONG_SECRET,
            razorpay_webhook_secret=STRONG_SECRET,
        ),
        notifications=NotificationSettings(
            email_backend="ses",
            sender="hello@motionile.com",
            whatsapp_token=STRONG_SECRET,
            whatsapp_phone_number_id="1234",
        ),
        elevenlabs=ElevenLabsSettings(api_key=STRONG_SECRET),
        openai=OpenAISettings(api_key=STRONG_SECRET),
        ai=AiSettings(
            anthropic_api_key=STRONG_SECRET,
            langfuse_public_key=SecretStr("pk-lf-test"),
            langfuse_secret_key=SecretStr("sk-lf-test"),
        ),
        media=MediaSettings(delivery_mode=MediaDeliveryMode.PRESIGNED),
        database=DatabaseSettings(url="postgresql://app@db.internal/motionile"),
        redis=RedisSettings(url="rediss://:secret@redis.internal:6379/0"),
        cors=CorsSettings(allowed_origins=("https://motionile.com",)),
        security=SecuritySettings(pagination_secret=STRONG_SECRET),
        encryption=EncryptionSettings(keys={1: ENCRYPTION_KEY}),
        turnstile=TurnstileSettings(secret_key=SecretStr("turnstile-secret")),
        storage=StorageSettings(bucket="motionile-production"),
        rate_limit=RateLimitSettings(enabled=False),
    )
