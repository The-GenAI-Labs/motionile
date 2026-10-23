from datetime import timedelta

import pytest
from pydantic import SecretStr
from tests.fakes.settings import make_settings
from tests.fakes.storage import InMemoryStorage
from tests.unit.modules.media.support import KEY_FILE, NOW, USER_A, USER_B

from motionile.core.clock import FrozenClock
from motionile.core.config import AppSettings, MediaDeliveryMode, MediaSettings, ProvidersMode, Settings
from motionile.modules.media import (
    CloudFrontDelivery,
    MediaDeliveryMisconfiguredError,
    MediaKeyNotSignableError,
    PresignedDelivery,
    build_delivery,
)
from motionile.modules.media.delivery import require_media_key

USER = USER_A
OTHER = USER_B
KEY = f"media/u/{USER}/renders/01939a5e-0000-7000-8000-0000000000aa/16x9.mp4"


def cloudfront_settings(**overrides: object) -> Settings:
    media = MediaSettings.model_validate(
        {
            "MEDIA_DELIVERY_MODE": "cloudfront",
            "CDN_DOMAIN": "cdn.motionile.test",
            "CLOUDFRONT_KEY_PAIR_ID": "KTESTPAIR0001",
            "CLOUDFRONT_PRIVATE_KEY": SecretStr(KEY_FILE.read_text()),
            "MEDIA_COOKIE_DOMAIN": ".motionile.test",
            **overrides,
        }
    )
    return Settings(app=AppSettings(providers_mode=ProvidersMode.FAKE), media=media)


async def test_presigned_delivery_returns_a_per_asset_url_and_no_cookies() -> None:
    delivery = PresignedDelivery(InMemoryStorage(), timedelta(seconds=900))

    grant = delivery.session(USER)

    assert grant.mode is MediaDeliveryMode.PRESIGNED
    assert grant.expires_at is None
    assert grant.cookies == ()
    assert await delivery.url_for(KEY) == f"memory://{KEY}?expires=900"
    assert await delivery.signed_url(KEY, timedelta(seconds=60)) == f"memory://{KEY}?expires=60"


@pytest.mark.parametrize(
    "key", ["work/renders/a/composition.html", "voice/u/a/v/sample.wav", "tts/ab/x.mp3", "music/a.m4a"]
)
async def test_presigned_delivery_refuses_keys_outside_media(key: str) -> None:
    delivery = PresignedDelivery(InMemoryStorage(), timedelta(seconds=900))

    with pytest.raises(MediaKeyNotSignableError):
        await delivery.url_for(key)
    with pytest.raises(MediaKeyNotSignableError):
        await delivery.signed_url(key, timedelta(seconds=60))


def test_the_factory_builds_presigned_delivery_by_default() -> None:
    delivery = build_delivery(make_settings(), InMemoryStorage(), FrozenClock(NOW))

    assert isinstance(delivery, PresignedDelivery)


def test_the_factory_builds_cloudfront_delivery_from_settings() -> None:
    delivery = build_delivery(cloudfront_settings(), InMemoryStorage(), FrozenClock(NOW))

    assert isinstance(delivery, CloudFrontDelivery)
    grant = delivery.session(USER)
    assert grant.mode is MediaDeliveryMode.CLOUDFRONT
    assert {cookie.domain for cookie in grant.cookies} == {".motionile.test"}


def test_the_cookie_lifetime_comes_from_settings() -> None:
    delivery = build_delivery(cloudfront_settings(MEDIA_COOKIE_TTL_SECONDS=120), InMemoryStorage(), FrozenClock(NOW))

    assert delivery.session(USER).expires_at == NOW + timedelta(seconds=120)


@pytest.mark.parametrize("missing", ["CDN_DOMAIN", "CLOUDFRONT_KEY_PAIR_ID", "CLOUDFRONT_PRIVATE_KEY"])
def test_the_factory_rejects_incomplete_cloudfront_configuration(missing: str) -> None:
    settings = cloudfront_settings(**{missing: None})

    with pytest.raises(MediaDeliveryMisconfiguredError):
        build_delivery(settings, InMemoryStorage(), FrozenClock(NOW))


def test_the_cookie_domain_falls_back_to_the_auth_cookie_domain() -> None:
    settings = cloudfront_settings(MEDIA_COOKIE_DOMAIN=None)
    settings = settings.model_copy(update={"auth": settings.auth.model_copy(update={"cookie_domain": ".auth.test"})})

    delivery = build_delivery(settings, InMemoryStorage(), FrozenClock(NOW))

    assert {cookie.domain for cookie in delivery.session(USER).cookies} == {".auth.test"}


def test_the_owner_prefix_restricts_signing_to_that_users_media() -> None:
    assert require_media_key(KEY, owner_user_id=USER) == KEY
    with pytest.raises(MediaKeyNotSignableError):
        require_media_key(KEY, owner_user_id=OTHER)
    with pytest.raises(MediaKeyNotSignableError):
        require_media_key(f"media/u/{USER}x/a.mp4", owner_user_id=USER)


async def test_presigned_delivery_pins_urls_to_the_owner_when_given() -> None:
    delivery = PresignedDelivery(InMemoryStorage(), timedelta(seconds=900))

    assert await delivery.url_for(KEY, owner_user_id=USER) == f"memory://{KEY}?expires=900"
    assert await delivery.signed_url(KEY, timedelta(seconds=60), owner_user_id=USER) == f"memory://{KEY}?expires=60"
    with pytest.raises(MediaKeyNotSignableError):
        await delivery.url_for(KEY, owner_user_id=OTHER)
    with pytest.raises(MediaKeyNotSignableError):
        await delivery.signed_url(KEY, timedelta(seconds=60), owner_user_id=OTHER)


async def test_cloudfront_delivery_pins_urls_to_the_owner_when_given() -> None:
    delivery = build_delivery(cloudfront_settings(), InMemoryStorage(), FrozenClock(NOW))

    assert (await delivery.url_for(KEY, owner_user_id=USER)).startswith("https://cdn.motionile.test/media/u/")
    assert "Signature=" in await delivery.signed_url(KEY, timedelta(seconds=60), owner_user_id=USER)
    with pytest.raises(MediaKeyNotSignableError):
        await delivery.url_for(KEY, owner_user_id=OTHER)
    with pytest.raises(MediaKeyNotSignableError):
        await delivery.signed_url(KEY, timedelta(seconds=60), owner_user_id=OTHER)
