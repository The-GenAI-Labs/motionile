import base64
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from botocore.signers import CloudFrontSigner as BotocoreCloudFrontSigner
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from tests.unit.modules.media.support import KEY_PAIR_ID, NOW, RENDER, USER_A, USER_B, load_key

from motionile.core.clock import FrozenClock
from motionile.modules.media import (
    CloudFrontDelivery,
    CloudFrontSigner,
    MediaKeyNotSignableError,
    render_media_prefix,
    user_media_prefix,
)
from motionile.modules.media.delivery import (
    KEY_PAIR_COOKIE,
    POLICY_COOKIE,
    SIGNATURE_COOKIE,
    cloudfront_base64,
    policy_document,
)

DOMAIN = "cdn.motionile.test"
COOKIE_DOMAIN = ".motionile.test"
COOKIE_TTL = timedelta(seconds=3600)
URL_TTL = timedelta(seconds=900)
EXPECTED_POLICY = (
    "eyJTdGF0ZW1lbnQiOlt7IlJlc291cmNlIjoiaHR0cHM6Ly9jZG4ubW90aW9uaWxlLnRlc3QvbWVkaWEvdS8wMTkz"
    "OWE1ZS0wMDAwLTcwMDAtODAwMC0wMDAwMDAwMDAwMDEvKiIsIkNvbmRpdGlvbiI6eyJEYXRlTGVzc1RoYW4iOnsi"
    "QVdTOkVwb2NoVGltZSI6MTc5MjQxNDgwMH19fV19"
)
EXPECTED_COOKIE_SIGNATURE = (
    "Hs4lYTsJZtqj3Yi1XXMjFtZEYpC5QXV~~K0hScN5B-OIL1DG8IDHgVfHfeb7sHcPyz3hmv5WFQ3HUasOGRkOOpDz"
    "EY~WsKdfKgMC3ifQeJqhDuvW1Rr4VMhLnjsfSJbtPu9BbNKaLHo9Q5Rw47xDl8b4DfZ99ZVmyoMwzliFY-Kv~Xwg"
    "3H049ttnUqYa35Q29bwFa25DRKJhSa5AqKJdT~6OVPpP74dpHC797FvrqPTmVdRpamIMROiEvQnMMwhrJ32JVR9f"
    "56g1ILiYTWr4ZWFaHEieqWKBC8iR-5rV7LP1pQDA1IR2OAWCIFm8DfiGWVFm-vtyUgHkHjbwOUCKaw__"
)
EXPECTED_URL_SIGNATURE = (
    "a7ySg~2g8J2SU--aqaTl0X6DW-VdS3R85d-cf0Rw5cqmGITt08K9ktpVYZB0rOcruc6RnUFj5bkLZYColnJPXuE3"
    "i90DZ~T7dPcTjtk0kPSrGqaucrsCXzNg7Djzdx8VRJNaVwJXq0sGmIgaz5Qat~8bvLlrTt60dPoraB4CME1~xx~n"
    "zuC-wTa~VCyrB-9ZUYxORoTjGrEhFfMNCfwHTxfXt4SoiN21-eRe7Dk6RYcz9sI0B8kluySs2W~c23zn3An012nI"
    "zRzq9AGzDwH0IAO5iZntQ3~vq6YjEkkjcndMGlNYW5La~dANPFHVfUjeBn1nRqRALadEsrFsPw0d5g__"
)
COOKIE_EXPIRY = 1792414800
URL_EXPIRY = 1792412100


def public_key() -> RSAPublicKey:
    return load_key().public_key()


def standard_decode(value: str) -> bytes:
    return base64.b64decode(value.replace("-", "+").replace("_", "=").replace("~", "/"))


def verifies(signature: str, document: bytes) -> bool:
    try:
        public_key().verify(standard_decode(signature), document, padding.PKCS1v15(), hashes.SHA1())  # noqa: S303
    except InvalidSignature:
        return False
    return True


def delivery() -> CloudFrontDelivery:
    return CloudFrontDelivery(
        CloudFrontSigner(load_key(), KEY_PAIR_ID),
        DOMAIN,
        FrozenClock(NOW),
        cookie_domain=COOKIE_DOMAIN,
        cookie_ttl=COOKIE_TTL,
    )


def user_key(user_id: UUID, name: str = "16x9.mp4") -> str:
    return f"{render_media_prefix(user_id, RENDER)}{name}"


def test_the_policy_and_signature_match_the_recorded_vector() -> None:
    grant = delivery().session(USER_A)
    cookies = {cookie.name: cookie.value for cookie in grant.cookies}

    assert cookies[POLICY_COOKIE] == EXPECTED_POLICY
    assert cookies[SIGNATURE_COOKIE] == EXPECTED_COOKIE_SIGNATURE
    assert cookies[KEY_PAIR_COOKIE] == KEY_PAIR_ID


def test_the_recorded_signature_verifies_with_the_public_key() -> None:
    policy = standard_decode(EXPECTED_POLICY)

    assert verifies(EXPECTED_COOKIE_SIGNATURE, policy)
    assert not verifies(EXPECTED_COOKIE_SIGNATURE, policy.replace(b"000000000001", b"000000000002"))


def test_the_policy_document_is_the_compact_custom_policy() -> None:
    document = json.loads(standard_decode(EXPECTED_POLICY))

    assert document == {
        "Statement": [
            {
                "Resource": f"https://{DOMAIN}/media/u/{USER_A}/*",
                "Condition": {"DateLessThan": {"AWS:EpochTime": COOKIE_EXPIRY}},
            }
        ]
    }
    assert b" " not in standard_decode(EXPECTED_POLICY)


def test_the_session_grant_expires_after_the_cookie_lifetime() -> None:
    grant = delivery().session(USER_A)

    assert grant.expires_at == NOW + COOKIE_TTL
    assert int(NOW.timestamp() + COOKIE_TTL.total_seconds()) == COOKIE_EXPIRY


def test_the_cookies_are_secure_http_only_lax_and_scoped_to_the_media_domain() -> None:
    cookies = delivery().session(USER_A).cookies

    assert [cookie.name for cookie in cookies] == [POLICY_COOKIE, SIGNATURE_COOKIE, KEY_PAIR_COOKIE]
    for cookie in cookies:
        assert cookie.secure
        assert cookie.http_only
        assert cookie.same_site == "lax"
        assert cookie.path == "/"
        assert cookie.domain == COOKIE_DOMAIN
        assert cookie.max_age == int(COOKIE_TTL.total_seconds())


def test_a_policy_for_one_user_never_covers_another_users_path() -> None:
    resource = delivery().user_resource(USER_A)
    prefix = resource.removesuffix("*")

    assert resource == f"https://{DOMAIN}/{user_media_prefix(USER_A)}*"
    assert f"https://{DOMAIN}/{user_key(USER_A)}".startswith(prefix)
    assert not f"https://{DOMAIN}/{user_key(USER_B)}".startswith(prefix)
    assert not f"https://{DOMAIN}/media/u/{USER_A}".startswith(prefix)
    assert not f"https://{DOMAIN}/media/u/{USER_A}evil/x.mp4".startswith(prefix)
    assert not f"https://{DOMAIN}/work/renders/{RENDER}/x".startswith(prefix)


def test_different_users_get_different_policies_and_signatures() -> None:
    first = {cookie.name: cookie.value for cookie in delivery().session(USER_A).cookies}
    second = {cookie.name: cookie.value for cookie in delivery().session(USER_B).cookies}

    assert first[POLICY_COOKIE] != second[POLICY_COOKIE]
    assert first[SIGNATURE_COOKIE] != second[SIGNATURE_COOKIE]
    assert str(USER_B) in json.loads(standard_decode(second[POLICY_COOKIE]))["Statement"][0]["Resource"]
    assert str(USER_A) not in json.loads(standard_decode(second[POLICY_COOKIE]))["Statement"][0]["Resource"]


async def test_a_signed_url_uses_a_canned_policy_that_matches_the_recorded_vector() -> None:
    url = await delivery().signed_url(user_key(USER_A), URL_TTL)
    parts = urlsplit(url)
    query = parse_qs(parts.query)

    assert parts.netloc == DOMAIN
    assert parts.path == f"/{user_key(USER_A)}"
    assert query["Expires"] == [str(URL_EXPIRY)]
    assert query["Signature"] == [EXPECTED_URL_SIGNATURE]
    assert query["Key-Pair-Id"] == [KEY_PAIR_ID]
    assert verifies(EXPECTED_URL_SIGNATURE, policy_document(f"https://{DOMAIN}/{user_key(USER_A)}", URL_EXPIRY))


async def test_signed_urls_match_the_aws_sdk_reference_signer() -> None:
    key = load_key()

    def sign(message: bytes) -> bytes:
        return key.sign(message, padding.PKCS1v15(), hashes.SHA1())  # noqa: S303

    reference = BotocoreCloudFrontSigner(KEY_PAIR_ID, sign)
    url = f"https://{DOMAIN}/{user_key(USER_A)}"
    expires = NOW + URL_TTL

    canned = reference.generate_presigned_url(url, date_less_than=expires)
    policy = reference.build_policy(url, expires)
    custom = reference.generate_presigned_url(url, policy=policy)
    signer = CloudFrontSigner(key, KEY_PAIR_ID)

    assert signer.canned_url(url, URL_EXPIRY) == canned
    assert signer.custom_url(url, URL_EXPIRY) == custom


def test_a_custom_policy_url_can_cover_a_wildcard_resource() -> None:
    signer = CloudFrontSigner(load_key(), KEY_PAIR_ID)
    url = f"https://{DOMAIN}/{user_key(USER_A)}"
    resource = f"https://{DOMAIN}/{user_media_prefix(USER_A)}*"

    signed = signer.custom_url(url, URL_EXPIRY, resource)
    query = parse_qs(urlsplit(signed).query)
    policy = standard_decode(query["Policy"][0])

    assert json.loads(policy)["Statement"][0]["Resource"] == resource
    assert verifies(query["Signature"][0], policy)
    assert "Expires" not in query


async def test_share_links_are_signed_under_the_share_path_only() -> None:
    url = delivery().share_url("abc123", URL_TTL)
    parts = urlsplit(url)
    query = parse_qs(parts.query)

    assert parts.path == "/share/abc123"
    assert verifies(query["Signature"][0], policy_document(f"https://{DOMAIN}/share/abc123", URL_EXPIRY))
    for name in ("../media/u/x", "a/b", "", "a b", "*"):
        with pytest.raises(MediaKeyNotSignableError):
            delivery().share_url(name, URL_TTL)


@pytest.mark.parametrize(
    "key",
    [
        "work/renders/01939a5e-0000-7000-8000-0000000000aa/composition.html",
        "voice/u/01939a5e-0000-7000-8000-000000000001/v/sample-0.wav",
        "tts/ab/abcdef.mp3",
        "music/track.m4a",
        "voice-preview/voice.mp3",
        "media",
        "mediax/u/a/b.mp4",
        "../media/u/a/b.mp4",
        "media/../work/x",
        "media/u/*/x.mp4",
        "media//u/x",
        "",
    ],
)
async def test_keys_outside_media_cannot_be_signed(key: str) -> None:
    with pytest.raises(MediaKeyNotSignableError):
        await delivery().signed_url(key, URL_TTL)
    with pytest.raises(MediaKeyNotSignableError):
        await delivery().url_for(key)


async def test_plain_urls_point_at_the_cdn_without_a_signature() -> None:
    url = await delivery().url_for(user_key(USER_A, "poster-16x9.webp"))

    assert url == f"https://{DOMAIN}/{user_key(USER_A, 'poster-16x9.webp')}"


def test_base64_uses_the_cloudfront_alphabet() -> None:
    assert cloudfront_base64(b"\xfb\xff\xfe") == "-~~-"
    assert cloudfront_base64(b"a") == "YQ__"
    assert cloudfront_base64(b"ab") == "YWI_"
    assert "+" not in cloudfront_base64(bytes(range(256)))
    assert "/" not in cloudfront_base64(bytes(range(256)))
    assert "=" not in cloudfront_base64(bytes(range(256)))
