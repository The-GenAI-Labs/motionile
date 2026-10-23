import base64
import json
from datetime import datetime, timedelta
from urllib.parse import quote
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from motionile.core.clock import Clock
from motionile.core.config import MediaDeliveryMode
from motionile.core.security.cookies import MEDIA_COOKIES
from motionile.modules.media.delivery.base import DeliveryCookie, MediaSessionGrant, require_media_key
from motionile.modules.media.exceptions import MediaKeyNotSignableError
from motionile.modules.media.keys import segment, user_media_prefix

POLICY_COOKIE, SIGNATURE_COOKIE, KEY_PAIR_COOKIE = MEDIA_COOKIES
SHARE_ROOT = "share"
BASE64_ALPHABET_MAP = str.maketrans({"+": "-", "=": "_", "/": "~"})


def cloudfront_base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii").translate(BASE64_ALPHABET_MAP)


def policy_document(resource: str, expires_at: int) -> bytes:
    document = {"Statement": [{"Resource": resource, "Condition": {"DateLessThan": {"AWS:EpochTime": expires_at}}}]}
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


class CloudFrontSigner:
    def __init__(self, private_key: RSAPrivateKey, key_pair_id: str) -> None:
        self._private_key = private_key
        self.key_pair_id = key_pair_id

    def __repr__(self) -> str:
        return f"CloudFrontSigner(key_pair_id={self.key_pair_id!r})"

    def sign(self, data: bytes) -> str:
        signature = self._private_key.sign(data, padding.PKCS1v15(), hashes.SHA1())  # noqa: S303
        return cloudfront_base64(signature)

    def cookies(self, resource: str, expires_at: int, max_age: int, domain: str | None) -> tuple[DeliveryCookie, ...]:
        policy = policy_document(resource, expires_at)
        return (
            DeliveryCookie(POLICY_COOKIE, cloudfront_base64(policy), max_age, domain),
            DeliveryCookie(SIGNATURE_COOKIE, self.sign(policy), max_age, domain),
            DeliveryCookie(KEY_PAIR_COOKIE, self.key_pair_id, max_age, domain),
        )

    def canned_url(self, url: str, expires_at: int) -> str:
        signature = self.sign(policy_document(url, expires_at))
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}Expires={expires_at}&Signature={signature}&Key-Pair-Id={self.key_pair_id}"

    def custom_url(self, url: str, expires_at: int, resource: str | None = None) -> str:
        policy = policy_document(resource or url, expires_at)
        separator = "&" if "?" in url else "?"
        return (
            f"{url}{separator}Policy={cloudfront_base64(policy)}"
            f"&Signature={self.sign(policy)}&Key-Pair-Id={self.key_pair_id}"
        )


class CloudFrontDelivery:
    mode = MediaDeliveryMode.CLOUDFRONT

    def __init__(
        self,
        signer: CloudFrontSigner,
        domain: str,
        clock: Clock,
        *,
        cookie_domain: str | None,
        cookie_ttl: timedelta,
    ) -> None:
        self._signer = signer
        self._domain = domain
        self._clock = clock
        self._cookie_domain = cookie_domain
        self._cookie_ttl = cookie_ttl

    def user_resource(self, user_id: UUID) -> str:
        return f"https://{self._domain}/{user_media_prefix(user_id)}*"

    def session(self, user_id: UUID) -> MediaSessionGrant:
        expires_at = self._clock.now() + self._cookie_ttl
        cookies = self._signer.cookies(
            self.user_resource(user_id),
            epoch(expires_at),
            int(self._cookie_ttl.total_seconds()),
            self._cookie_domain,
        )
        return MediaSessionGrant(self.mode, expires_at, cookies)

    async def url_for(self, key: str, *, owner_user_id: UUID | None = None) -> str:
        return self._url(require_media_key(key, owner_user_id=owner_user_id))

    async def signed_url(self, key: str, ttl: timedelta, *, owner_user_id: UUID | None = None) -> str:
        return self._signer.canned_url(
            self._url(require_media_key(key, owner_user_id=owner_user_id)), self._expiry(ttl)
        )

    def share_url(self, name: str, ttl: timedelta) -> str:
        try:
            checked = segment(name)
        except ValueError:
            raise MediaKeyNotSignableError from None
        return self._signer.canned_url(
            f"https://{self._domain}/{SHARE_ROOT}/{quote(checked, safe='')}", self._expiry(ttl)
        )

    def _url(self, key: str) -> str:
        return f"https://{self._domain}/{quote(key, safe='/')}"

    def _expiry(self, ttl: timedelta) -> int:
        return epoch(self._clock.now() + ttl)


def epoch(moment: datetime) -> int:
    return int(moment.timestamp())
