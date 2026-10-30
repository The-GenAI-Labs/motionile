import pytest
from hypothesis import given
from hypothesis import strategies as st

from motionile.modules.generation import ChargingParameters, charge_for, estimate_credits

DEFAULTS = ChargingParameters(base_credits=20, credits_per_second=2, extra_aspect_percent=40, cloned_voice_premium=10)

parameters = st.builds(
    ChargingParameters,
    base_credits=st.integers(0, 1_000),
    credits_per_second=st.integers(0, 100),
    extra_aspect_percent=st.integers(0, 300),
    cloned_voice_premium=st.integers(0, 1_000),
)
seconds = st.integers(0, 600)
aspects = st.integers(1, 3)


@pytest.mark.parametrize(
    ("duration", "aspect_count", "cloned", "expected"),
    [
        (60, 1, False, 140),
        (60, 2, False, 196),
        (60, 3, False, 252),
        (60, 1, True, 150),
        (10, 1, False, 40),
        (45, 2, True, 164),
        (91, 3, False, 364),
    ],
)
def test_the_formula_matches_hand_computed_examples(
    duration: int, aspect_count: int, cloned: bool, expected: int
) -> None:
    assert estimate_credits(DEFAULTS, duration, aspect_count, cloned) == expected


def test_the_subtotal_is_rounded_up_before_the_voice_premium() -> None:
    odd = ChargingParameters(base_credits=1, credits_per_second=1, extra_aspect_percent=33, cloned_voice_premium=5)

    assert estimate_credits(odd, 10, 2, cloned_voice=False) == 15
    assert estimate_credits(odd, 10, 2, cloned_voice=True) == 20


@pytest.mark.parametrize(("duration", "count"), [(-1, 1), (10, 0)])
def test_nonsensical_inputs_are_rejected(duration: int, count: int) -> None:
    with pytest.raises(ValueError, match=r"must not be negative|at least one"):
        estimate_credits(DEFAULTS, duration, count, cloned_voice=False)


def test_negative_parameters_are_rejected() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        ChargingParameters(base_credits=-1, credits_per_second=0, extra_aspect_percent=0, cloned_voice_premium=0)


@given(parameters, seconds, seconds, aspects, st.booleans())
def test_the_estimate_never_decreases_with_duration(
    values: ChargingParameters, first: int, second: int, count: int, cloned: bool
) -> None:
    low, high = sorted((first, second))

    assert estimate_credits(values, low, count, cloned) <= estimate_credits(values, high, count, cloned)


@given(parameters, seconds, aspects, aspects, st.booleans())
def test_the_estimate_never_decreases_with_aspects(
    values: ChargingParameters, duration: int, first: int, second: int, cloned: bool
) -> None:
    low, high = sorted((first, second))

    assert estimate_credits(values, duration, low, cloned) <= estimate_credits(values, duration, high, cloned)


@given(parameters, seconds, aspects)
def test_a_cloned_voice_adds_exactly_the_premium(values: ChargingParameters, duration: int, count: int) -> None:
    plain = estimate_credits(values, duration, count, cloned_voice=False)

    assert estimate_credits(values, duration, count, cloned_voice=True) == plain + values.cloned_voice_premium


@given(parameters, st.integers(0, 600_000), aspects, st.booleans(), st.integers(0, 100_000))
def test_the_charge_never_exceeds_the_reservation(
    values: ChargingParameters, duration_ms: int, count: int, cloned: bool, reserved: int
) -> None:
    assert 0 <= charge_for(values, duration_ms, count, cloned, reserved) <= reserved


@given(parameters, st.integers(0, 600_000), aspects, st.booleans())
def test_a_full_reservation_is_charged_exactly_the_formula(
    values: ChargingParameters, duration_ms: int, count: int, cloned: bool
) -> None:
    rounded_up = -(-duration_ms // 1000)
    formula = estimate_credits(values, rounded_up, count, cloned)

    assert charge_for(values, duration_ms, count, cloned, formula) == formula


def test_the_charge_rounds_the_final_duration_up_to_whole_seconds() -> None:
    assert charge_for(DEFAULTS, 45_001, 1, cloned_voice=False, reserved=1_000) == estimate_credits(
        DEFAULTS, 46, 1, cloned_voice=False
    )


def test_a_shorter_video_costs_less_than_the_reservation() -> None:
    reserved = estimate_credits(DEFAULTS, 60, 1, cloned_voice=False)

    assert charge_for(DEFAULTS, 30_000, 1, cloned_voice=False, reserved=reserved) == 80
    assert charge_for(DEFAULTS, 90_000, 1, cloned_voice=False, reserved=reserved) == reserved
