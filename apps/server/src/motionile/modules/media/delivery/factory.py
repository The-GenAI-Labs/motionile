from datetime import timedelta

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from motionile.core.clock import Clock
from motionile.core.config import MediaDeliveryMode, Settings
from motionile.core.storage.base import Storage
from motionile.modules.media.delivery.base import MediaDelivery
from motionile.modules.media.delivery.cloudfront import CloudFrontDelivery, CloudFrontSigner
from motionile.modules.media.delivery.presigned import PresignedDelivery
from motionile.modules.media.exceptions import MediaDeliveryMisconfiguredError


def load_signing_key(pem: bytes) -> RSAPrivateKey:
    key = load_pem_private_key(pem, password=None)
    if not isinstance(key, RSAPrivateKey):
        raise MediaDeliveryMisconfiguredError
    return key


def build_delivery(settings: Settings, storage: Storage, clock: Clock) -> MediaDelivery:
    media = settings.media
    if media.delivery_mode is MediaDeliveryMode.PRESIGNED:
        return PresignedDelivery(storage, timedelta(seconds=media.signed_url_ttl_seconds))
    pem = media.private_key_pem
    if media.cdn_domain is None or media.cloudfront_key_pair_id is None or pem is None:
        raise MediaDeliveryMisconfiguredError
    return CloudFrontDelivery(
        CloudFrontSigner(load_signing_key(pem), media.cloudfront_key_pair_id),
        media.cdn_domain,
        clock,
        cookie_domain=settings.media_cookie_domain,
        cookie_ttl=timedelta(seconds=media.cookie_ttl_seconds),
    )
