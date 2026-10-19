import pytest
from pydantic import SecretStr

from motionile.modules.billing import (
    verify_order_payment_signature,
    verify_subscription_payment_signature,
    verify_webhook_signature,
)
from motionile.modules.billing.razorpay.signatures import (
    sign_order_payment,
    sign_subscription_payment,
    sign_webhook,
)

KEY_SECRET = SecretStr("EnLs21M47BllR3X8PSFtjtbd")
WEBHOOK_SECRET = SecretStr("whsec_test_secret_0123456789")
ORDER_ID = "order_IluGWxBm9U8zJ8"
PAYMENT_ID = "pay_IH4NVgf4Dreq1l"
SUBSCRIPTION_ID = "sub_IluGWxBm9U8zJ8"
WEBHOOK_BODY = b'{"entity":"event","event":"payment.captured"}'

ORDER_SIGNATURE = "c7a6b6e37e5fb8b5387cd93cff2f9cedbf5cb78112fd50292c56b4cecb49b80d"
ORDER_SIGNATURE_OTHER_KEY = "84fa50648352968a775677f80f0da1bb1348b03734632469790830f1b27cc784"
ORDER_SIGNATURE_SWAPPED = "d2b85c64ed2d1efb56b39b4badf8200147667a8af2d74b3b12e9e8a40da656a2"
SUBSCRIPTION_SIGNATURE = "fc82106f583d58749d50ea1947df744d5f9972327ff8b1c3788323746c6d7cb1"
SUBSCRIPTION_SIGNATURE_SWAPPED = "36064bfba1c15c38e20a1c601104119fc55fc90e7f198afaea240c272154706b"
WEBHOOK_SIGNATURE = "b4b9ba76461434633e9cb164a40b362923e0260ed61576a5935eec17cb8a75f0"
WEBHOOK_SIGNATURE_EMPTY_BODY = "4c97ae561714c7e1d8dd5bdf39470712f31896c71b69ad8485a949d1cf776e61"
WEBHOOK_SIGNATURE_TRAILING_SPACE = "71ca1d7489c93f5c97b1c87ede0173fb9972aa447a7cf35fc7586603b21dd77b"


def test_order_signature_matches_the_documented_construction() -> None:
    assert sign_order_payment(ORDER_ID, PAYMENT_ID, KEY_SECRET) == ORDER_SIGNATURE
    assert verify_order_payment_signature(ORDER_ID, PAYMENT_ID, ORDER_SIGNATURE, KEY_SECRET)


def test_order_signature_rejects_wrong_secret_swapped_arguments_and_other_vectors() -> None:
    assert not verify_order_payment_signature(ORDER_ID, PAYMENT_ID, ORDER_SIGNATURE_OTHER_KEY, KEY_SECRET)
    assert not verify_order_payment_signature(PAYMENT_ID, ORDER_ID, ORDER_SIGNATURE, KEY_SECRET)
    assert not verify_order_payment_signature(ORDER_ID, PAYMENT_ID, ORDER_SIGNATURE_SWAPPED, KEY_SECRET)
    assert verify_order_payment_signature(PAYMENT_ID, ORDER_ID, ORDER_SIGNATURE_SWAPPED, KEY_SECRET)
    assert not verify_order_payment_signature(ORDER_ID, PAYMENT_ID, ORDER_SIGNATURE, SecretStr("another-secret"))


def test_subscription_signature_signs_payment_then_subscription() -> None:
    assert sign_subscription_payment(PAYMENT_ID, SUBSCRIPTION_ID, KEY_SECRET) == SUBSCRIPTION_SIGNATURE
    assert verify_subscription_payment_signature(PAYMENT_ID, SUBSCRIPTION_ID, SUBSCRIPTION_SIGNATURE, KEY_SECRET)
    assert not verify_subscription_payment_signature(SUBSCRIPTION_ID, PAYMENT_ID, SUBSCRIPTION_SIGNATURE, KEY_SECRET)
    assert verify_subscription_payment_signature(
        SUBSCRIPTION_ID, PAYMENT_ID, SUBSCRIPTION_SIGNATURE_SWAPPED, KEY_SECRET
    )


def test_webhook_signature_covers_the_raw_bytes_exactly() -> None:
    assert sign_webhook(WEBHOOK_BODY, WEBHOOK_SECRET) == WEBHOOK_SIGNATURE
    assert verify_webhook_signature(WEBHOOK_BODY, WEBHOOK_SIGNATURE, WEBHOOK_SECRET)
    assert verify_webhook_signature(b"", WEBHOOK_SIGNATURE_EMPTY_BODY, WEBHOOK_SECRET)
    assert verify_webhook_signature(WEBHOOK_BODY + b" ", WEBHOOK_SIGNATURE_TRAILING_SPACE, WEBHOOK_SECRET)
    assert not verify_webhook_signature(WEBHOOK_BODY + b" ", WEBHOOK_SIGNATURE, WEBHOOK_SECRET)
    assert not verify_webhook_signature(WEBHOOK_BODY, WEBHOOK_SIGNATURE, SecretStr("whsec_other"))
    assert not verify_webhook_signature(
        b'{"entity": "event", "event": "payment.captured"}', WEBHOOK_SIGNATURE, WEBHOOK_SECRET
    )


@pytest.mark.parametrize(
    "signature",
    [
        pytest.param("", id="empty"),
        pytest.param(" ", id="blank"),
        pytest.param(WEBHOOK_SIGNATURE + " ", id="trailing-space"),
        pytest.param(" " + WEBHOOK_SIGNATURE, id="leading-space"),
        pytest.param(WEBHOOK_SIGNATURE + "\n", id="trailing-newline"),
        pytest.param(WEBHOOK_SIGNATURE.upper(), id="uppercase"),
        pytest.param(WEBHOOK_SIGNATURE[:-1], id="short"),
        pytest.param(WEBHOOK_SIGNATURE + "0", id="long"),
        pytest.param(WEBHOOK_SIGNATURE * 1_000, id="oversized"),
        pytest.param("g" * 64, id="not-hex"),
        pytest.param("é" * 64, id="non-ascii"),
        pytest.param(WEBHOOK_SIGNATURE[:-1] + "٣", id="unicode-digit"),
        pytest.param("\x00" * 64, id="nul-bytes"),
        pytest.param("sha256=" + WEBHOOK_SIGNATURE, id="prefixed"),
    ],
)
def test_malformed_signatures_are_rejected_without_raising(signature: str) -> None:
    assert not verify_webhook_signature(WEBHOOK_BODY, signature, WEBHOOK_SECRET)
    assert not verify_order_payment_signature(ORDER_ID, PAYMENT_ID, signature, KEY_SECRET)
    assert not verify_subscription_payment_signature(PAYMENT_ID, SUBSCRIPTION_ID, signature, KEY_SECRET)


@pytest.mark.parametrize(
    ("first", "second"),
    [("", PAYMENT_ID), (ORDER_ID, ""), ("order_a|pay_b", "pay_c"), (ORDER_ID, "pay_a|"), ("\ud800", PAYMENT_ID)],
)
def test_ambiguous_or_unencodable_identifiers_never_verify(first: str, second: str) -> None:
    assert not verify_order_payment_signature(first, second, ORDER_SIGNATURE, KEY_SECRET)
    assert not verify_subscription_payment_signature(first, second, SUBSCRIPTION_SIGNATURE, KEY_SECRET)
    with pytest.raises(ValueError, match="identifiers"):
        sign_order_payment(first, second, KEY_SECRET)
    with pytest.raises(ValueError, match="identifiers"):
        sign_subscription_payment(first, second, KEY_SECRET)


def test_empty_secrets_never_verify_and_cannot_sign() -> None:
    empty = SecretStr("")
    forged = sign_webhook(WEBHOOK_BODY, SecretStr("x"))

    assert not verify_webhook_signature(WEBHOOK_BODY, forged, empty)
    assert not verify_order_payment_signature(ORDER_ID, PAYMENT_ID, ORDER_SIGNATURE, empty)
    with pytest.raises(ValueError, match="must not be empty"):
        sign_webhook(WEBHOOK_BODY, empty)
