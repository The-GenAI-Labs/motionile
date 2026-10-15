import base64
import hashlib
import hmac
import secrets


def random_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


def sign_value(secret: bytes, *values: str) -> str:
    payload = "\x00".join(values).encode()
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
