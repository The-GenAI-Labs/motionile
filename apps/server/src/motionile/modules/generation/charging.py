from dataclasses import dataclass

PERCENT = 100
MILLISECONDS_PER_SECOND = 1_000


@dataclass(frozen=True, slots=True)
class ChargingParameters:
    base_credits: int
    credits_per_second: int
    extra_aspect_percent: int
    cloned_voice_premium: int

    def __post_init__(self) -> None:
        if min(self.base_credits, self.credits_per_second, self.extra_aspect_percent, self.cloned_voice_premium) < 0:
            raise ValueError("charging parameters must not be negative")


def ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def estimate_credits(parameters: ChargingParameters, seconds: int, aspect_count: int, cloned_voice: bool) -> int:
    if seconds < 0:
        raise ValueError("seconds must not be negative")
    if aspect_count < 1:
        raise ValueError("a video has at least one aspect")
    subtotal = parameters.base_credits + parameters.credits_per_second * seconds
    scaled = subtotal * (PERCENT + parameters.extra_aspect_percent * (aspect_count - 1))
    total = ceil_div(scaled, PERCENT)
    return total + parameters.cloned_voice_premium if cloned_voice else total


def charge_for(
    parameters: ChargingParameters, final_duration_ms: int, aspect_count: int, cloned_voice: bool, reserved: int
) -> int:
    if final_duration_ms < 0:
        raise ValueError("the final duration must not be negative")
    seconds = ceil_div(final_duration_ms, MILLISECONDS_PER_SECOND)
    return min(estimate_credits(parameters, seconds, aspect_count, cloned_voice), reserved)
