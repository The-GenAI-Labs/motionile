import hashlib
import hmac
import re

from pydantic import SecretStr

SIGNATURE_PATTERN = re.compile(r"[0-9a-f]{64}")
SEPARATOR = "|"


def digest_of(secret: SecretStr, message: bytes) -> str:
    key = secret.get_secret_value().encode()
    if not key:
        reason = "Razorpay signing secrets must not be empty"
        raise ValueError(reason)
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def signatures_match(expected: str, supplied: str) -> bool:
    if SIGNATURE_PATTERN.fullmatch(supplied) is None:
        return False
    return hmac.compare_digest(bytes.fromhex(expected), bytes.fromhex(supplied))


def joined_message(first: str, second: str) -> bytes | None:
    if not first or not second or SEPARATOR in first or SEPARATOR in second:
        return None
    try:
        return f"{first}{SEPARATOR}{second}".encode()
    except UnicodeEncodeError:
        return None


def verify_signature(secret: SecretStr, message: bytes | None, signature: str) -> bool:
    if message is None or not secret.get_secret_value():
        return False
    return signatures_match(digest_of(secret, message), signature)


def sign_webhook(raw_body: bytes, secret: SecretStr) -> str:
    return digest_of(secret, raw_body)


def sign_order_payment(order_id: str, payment_id: str, key_secret: SecretStr) -> str:
    message = joined_message(order_id, payment_id)
    if message is None:
        reason = "order and payment identifiers must be non-empty and free of separators"
        raise ValueError(reason)
    return digest_of(key_secret, message)


def sign_subscription_payment(payment_id: str, subscription_id: str, key_secret: SecretStr) -> str:
    message = joined_message(payment_id, subscription_id)
    if message is None:
        reason = "payment and subscription identifiers must be non-empty and free of separators"
        raise ValueError(reason)
    return digest_of(key_secret, message)


def verify_webhook_signature(raw_body: bytes, signature: str, secret: SecretStr) -> bool:
    return verify_signature(secret, raw_body, signature)


def verify_order_payment_signature(order_id: str, payment_id: str, signature: str, key_secret: SecretStr) -> bool:
    return verify_signature(key_secret, joined_message(order_id, payment_id), signature)


def verify_subscription_payment_signature(
    payment_id: str, subscription_id: str, signature: str, key_secret: SecretStr
) -> bool:
    return verify_signature(key_secret, joined_message(payment_id, subscription_id), signature)
