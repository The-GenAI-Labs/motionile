from http.cookies import SimpleCookie

from starlette.responses import Response
from tests.fakes.settings import make_settings
from tests.fakes.storage import InMemoryStorage
from tests.unit.modules.media.support import NOW, USER_A
from tests.unit.modules.media.test_delivery_modes import cloudfront_settings

from motionile.core.clock import FrozenClock
from motionile.core.security.cookies import MEDIA_COOKIES, CookieManager
from motionile.modules.media import build_delivery
from motionile.modules.media.router import apply_cookies


def parse(response: Response) -> SimpleCookie:
    parsed: SimpleCookie = SimpleCookie()
    for value in response.headers.getlist("set-cookie"):
        parsed.load(value)
    return parsed


def test_clearing_a_session_expires_the_cloudfront_cookies_with_the_attributes_they_were_set_with() -> None:
    settings = cloudfront_settings()
    granted = Response()
    apply_cookies(granted, build_delivery(settings, InMemoryStorage(), FrozenClock(NOW)).session(USER_A))
    cleared = Response()

    CookieManager.for_settings(settings).clear(cleared)

    set_cookies = parse(granted)
    cleared_cookies = parse(cleared)
    for name in MEDIA_COOKIES:
        assert cleared_cookies[name]["max-age"] == "0"
        assert cleared_cookies[name]["domain"] == set_cookies[name]["domain"] == ".motionile.test"
        assert cleared_cookies[name]["path"] == set_cookies[name]["path"]
        assert cleared_cookies[name]["secure"]
        assert cleared_cookies[name]["httponly"]
        assert cleared_cookies[name]["samesite"] == set_cookies[name]["samesite"]


def test_no_cloudfront_cookie_is_cleared_when_media_is_delivered_with_presigned_urls() -> None:
    cleared = Response()

    CookieManager.for_settings(make_settings()).clear(cleared)

    assert not set(MEDIA_COOKIES) & set(parse(cleared))


def test_the_media_cookie_domain_falls_back_to_the_auth_cookie_domain() -> None:
    manager = CookieManager.for_settings(cloudfront_settings(MEDIA_COOKIE_DOMAIN=None))

    assert manager.clears_media
    assert manager.media_domain is None
