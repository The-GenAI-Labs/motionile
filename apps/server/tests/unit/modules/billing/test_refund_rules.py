import pytest
from hypothesis import given
from hypothesis import strategies as st

from motionile.modules.billing.exceptions import RefundExceedsRefundableError
from motionile.modules.billing.services.refund_rules import (
    clawback_amount,
    proportional_credits,
    refund_payment_status,
    refundable_paise,
    resolve_refund_amount,
)
from motionile.modules.billing.states import PaymentRecordStatus


def test_the_refundable_amount_excludes_processed_and_pending_refunds() -> None:
    assert refundable_paise(amount_paise=10_000, refunded_paise=2_500, pending_paise=1_500) == 6_000
    assert refundable_paise(amount_paise=10_000, refunded_paise=0, pending_paise=0) == 10_000


def test_an_omitted_amount_refunds_everything_that_is_left() -> None:
    assert resolve_refund_amount(None, 6_000) == 6_000


@pytest.mark.parametrize(("requested", "refundable"), [(1, 1), (6_000, 6_000), (1, 6_000)])
def test_amounts_within_the_refundable_amount_are_accepted(requested: int, refundable: int) -> None:
    assert resolve_refund_amount(requested, refundable) == requested


@pytest.mark.parametrize(
    ("requested", "refundable"), [(0, 100), (-5, 100), (101, 100), (1, 0), (None, 0), (None, -3), (1, -3)]
)
def test_amounts_outside_the_refundable_amount_are_rejected_with_the_remaining_amount(
    requested: int | None, refundable: int
) -> None:
    with pytest.raises(RefundExceedsRefundableError) as raised:
        resolve_refund_amount(requested, refundable)

    assert raised.value.code == "refund_exceeds_refundable"
    assert raised.value.extensions == {"refundablePaise": max(refundable, 0)}


def test_the_payment_status_follows_the_refunded_total() -> None:
    assert refund_payment_status(amount_paise=100, refunded_paise=1) is PaymentRecordStatus.PARTIALLY_REFUNDED
    assert refund_payment_status(amount_paise=100, refunded_paise=99) is PaymentRecordStatus.PARTIALLY_REFUNDED
    assert refund_payment_status(amount_paise=100, refunded_paise=100) is PaymentRecordStatus.REFUNDED


@pytest.mark.parametrize(
    ("granted", "paid", "refunded", "expected"),
    [
        (100, 49_900, 49_900, 100),
        (100, 49_900, 24_950, 50),
        (100, 49_900, 1, 1),
        (10, 100, 33, 4),
        (10, 100, 34, 4),
        (0, 100, 50, 0),
        (100, 100, 0, 0),
    ],
)
def test_credits_are_rounded_up_with_integer_arithmetic(granted: int, paid: int, refunded: int, expected: int) -> None:
    assert (
        proportional_credits(credits_granted=granted, payment_amount_paise=paid, refund_amount_paise=refunded)
        == expected
    )


def test_a_clawback_never_takes_more_than_the_lot_still_holds() -> None:
    assert (
        clawback_amount(
            credits_granted=100,
            payment_amount_paise=1_000,
            refund_amount_paise=1_000,
            already_clawed_back=0,
            lot_remaining=30,
        )
        == 30
    )


def test_a_spent_lot_claws_back_nothing() -> None:
    assert (
        clawback_amount(
            credits_granted=100,
            payment_amount_paise=1_000,
            refund_amount_paise=500,
            already_clawed_back=0,
            lot_remaining=0,
        )
        == 0
    )


def test_rounding_across_several_refunds_never_exceeds_the_credits_granted() -> None:
    taken = 0
    for refunded in (33, 33, 34):
        taken += clawback_amount(
            credits_granted=10,
            payment_amount_paise=100,
            refund_amount_paise=refunded,
            already_clawed_back=taken,
            lot_remaining=10 - taken,
        )

    assert taken == 10


positive = st.integers(min_value=1, max_value=10**9)


@given(
    credits_granted=st.integers(min_value=0, max_value=10**6),
    payment=positive,
    share=st.integers(min_value=0, max_value=10**9),
    already=st.integers(min_value=0, max_value=10**6),
    remaining=st.integers(min_value=0, max_value=10**6),
)
def test_a_clawback_is_bounded_by_what_was_granted_and_what_remains(
    credits_granted: int, payment: int, share: int, already: int, remaining: int
) -> None:
    refund = min(share, payment)
    already_taken = min(already, credits_granted)

    amount = clawback_amount(
        credits_granted=credits_granted,
        payment_amount_paise=payment,
        refund_amount_paise=refund,
        already_clawed_back=already_taken,
        lot_remaining=remaining,
    )

    assert 0 <= amount <= remaining
    assert already_taken + amount <= credits_granted


@given(
    credits_granted=st.integers(min_value=1, max_value=10**6),
    payment=positive,
    refunds=st.tuples(st.integers(min_value=0, max_value=10**9), st.integers(min_value=0, max_value=10**9)),
    already=st.integers(min_value=0, max_value=10**6),
    remaining=st.integers(min_value=0, max_value=10**6),
)
def test_a_larger_refund_never_claws_back_less(
    credits_granted: int, payment: int, refunds: tuple[int, int], already: int, remaining: int
) -> None:
    low, high = sorted(min(refund, payment) for refund in refunds)
    already_taken = min(already, credits_granted)

    def amount_for(refund: int) -> int:
        return clawback_amount(
            credits_granted=credits_granted,
            payment_amount_paise=payment,
            refund_amount_paise=refund,
            already_clawed_back=already_taken,
            lot_remaining=remaining,
        )

    assert amount_for(low) <= amount_for(high)


@given(
    credits_granted=st.integers(min_value=1, max_value=1_000),
    payment=st.integers(min_value=1, max_value=10_000),
    cuts=st.lists(st.integers(min_value=1, max_value=10_000), min_size=1, max_size=8),
)
def test_any_sequence_of_refunds_up_to_the_payment_recovers_at_most_the_credits_granted(
    credits_granted: int, payment: int, cuts: list[int]
) -> None:
    remaining_paise = payment
    taken = 0
    lot_remaining = credits_granted
    for cut in cuts:
        refund = min(cut, remaining_paise)
        if refund == 0:
            break
        remaining_paise -= refund
        amount = clawback_amount(
            credits_granted=credits_granted,
            payment_amount_paise=payment,
            refund_amount_paise=refund,
            already_clawed_back=taken,
            lot_remaining=lot_remaining,
        )
        taken += amount
        lot_remaining -= amount

    assert taken <= credits_granted
    assert lot_remaining >= 0


@given(
    credits_granted=st.integers(min_value=1, max_value=10**6),
    payment=positive,
    refund=st.integers(min_value=1, max_value=10**9),
)
def test_the_proportional_share_is_an_exact_integer_ceiling(credits_granted: int, payment: int, refund: int) -> None:
    refunded = min(refund, payment)

    share = proportional_credits(
        credits_granted=credits_granted, payment_amount_paise=payment, refund_amount_paise=refunded
    )

    assert share * payment >= credits_granted * refunded
    assert (share - 1) * payment < credits_granted * refunded
