from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import cast
from urllib.parse import urlsplit

from redis.asyncio import Redis

from motionile.core.bot.turnstile import CloudflareTurnstileVerifier, FakeTurnstileVerifier, TurnstileVerifier
from motionile.core.clock import Clock, SystemClock
from motionile.core.config import Settings
from motionile.core.db import Database, create_engine
from motionile.core.events import EventBus, event_bus
from motionile.core.http.safe_client import SafeHttpClient
from motionile.core.idempotency import IdempotencyService
from motionile.core.pagination import CursorCodec
from motionile.core.ratelimit.limiter import RateLimiter
from motionile.core.ratelimit.policies import resolve_policies
from motionile.core.redis import RedisKeyBuilder, RedisStore, create_redis_client
from motionile.core.security.encryption import KeyRing
from motionile.core.storage.base import Storage
from motionile.core.storage.s3 import S3Storage

TURNSTILE_HOSTS = ("challenges.cloudflare.com",)
RAZORPAY_HOSTS = ("api.razorpay.com",)


@dataclass
class Resources:
    settings: Settings
    clock: Clock
    database: Database
    redis: Redis
    redis_store: RedisStore
    rate_limiter: RateLimiter
    idempotency: IdempotencyService
    cursor_codec: CursorCodec
    key_ring: KeyRing
    storage: Storage
    http_client: SafeHttpClient
    turnstile: TurnstileVerifier
    events: EventBus
    provider_clients: dict[str, SafeHttpClient] = field(default_factory=dict[str, SafeHttpClient])
    shared: dict[str, object] = field(default_factory=dict[str, object])

    def shared_instance[InstanceT](self, name: str, build: Callable[[], InstanceT]) -> InstanceT:
        if name not in self.shared:
            self.shared[name] = build()
        return cast("InstanceT", self.shared[name])

    async def aclose(self) -> None:
        for client in self.provider_clients.values():
            await client.aclose()
        await self.http_client.aclose()
        await self.redis.aclose()
        await self.database.dispose()


def build_turnstile(settings: Settings, http_client: SafeHttpClient) -> TurnstileVerifier:
    secret = settings.turnstile.secret_key
    if settings.is_fake_providers or secret is None:
        return FakeTurnstileVerifier()
    return CloudflareTurnstileVerifier(
        http_client,
        secret_key=secret.get_secret_value(),
        verify_url=settings.turnstile.verify_url,
        expected_hostnames=settings.turnstile.expected_hostnames,
    )


def build_resources(settings: Settings, *, application_name: str, clock: Clock | None = None) -> Resources:
    resolved_clock = clock or SystemClock()
    database = Database(create_engine(settings.database, application_name=application_name))
    redis = create_redis_client(settings.redis)
    keys = RedisKeyBuilder(settings.redis.key_prefix)
    http_client = SafeHttpClient(settings.outbound_http)
    turnstile_client = SafeHttpClient(settings.outbound_http, allowed_hosts=TURNSTILE_HOSTS)
    web_origin = settings.auth.web_origin.rstrip("/")
    web_host = urlsplit(web_origin).hostname
    if web_host is None:
        raise ValueError("AUTH_WEB_ORIGIN requires a host")
    web_test_origins = (web_origin,) if settings.is_local or settings.test_routes_enabled else ()
    return Resources(
        settings=settings,
        clock=resolved_clock,
        database=database,
        redis=redis,
        redis_store=RedisStore(redis, keys),
        rate_limiter=RateLimiter(
            redis,
            keys,
            resolve_policies(settings.rate_limit.overrides),
            enabled=settings.rate_limit.enabled,
        ),
        idempotency=IdempotencyService(
            database=database,
            clock=resolved_clock,
            ttl=timedelta(seconds=settings.security.idempotency_ttl_seconds),
            lock_duration=timedelta(seconds=settings.security.idempotency_lock_seconds),
        ),
        cursor_codec=CursorCodec(settings.pagination_secret),
        key_ring=KeyRing(settings.encryption_keys),
        storage=S3Storage.from_settings(settings.storage),
        http_client=http_client,
        turnstile=build_turnstile(settings, turnstile_client),
        events=event_bus,
        provider_clients={
            "turnstile": turnstile_client,
            "hibp": SafeHttpClient(settings.outbound_http, allowed_hosts=("api.pwnedpasswords.com",)),
            "whatsapp": SafeHttpClient(settings.outbound_http, allowed_hosts=("graph.facebook.com",)),
            "google": SafeHttpClient(
                settings.outbound_http, allowed_hosts=("oauth2.googleapis.com", "www.googleapis.com")
            ),
            "github": SafeHttpClient(settings.outbound_http, allowed_hosts=("github.com", "api.github.com")),
            "microsoft": SafeHttpClient(settings.outbound_http, allowed_hosts=("login.microsoftonline.com",)),
            "razorpay": SafeHttpClient(settings.outbound_http, allowed_hosts=RAZORPAY_HOSTS),
            "catalog_revalidation": SafeHttpClient(
                settings.outbound_http,
                allowed_hosts=(web_host,),
                insecure_test_origins=web_test_origins,
            ),
        },
    )
