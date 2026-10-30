from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

from motionile.core.errors import ValidationAppError
from motionile.modules.generation.admin_schemas import DayOutcomeView, StageDurationView

MAX_RANGE_DAYS: Final = 366
DEFAULT_RANGE_DAYS: Final = 30
MS_PER_SECOND: Final = 1_000
ROUNDING: Final = 4

type OutcomeCounts = Mapping[tuple[date, str], int]


class AnalyticsRangeError(ValidationAppError):
    default_code = "analytics_range_invalid"
    title = "Analytics range invalid"


@dataclass(frozen=True, slots=True)
class StageAverage:
    stage: str
    average_ms: float
    samples: int


@dataclass(frozen=True, slots=True)
class SceneTotals:
    scenes: int
    repaired: int
    fallbacks: int


def resolve_range(date_from: date | None, date_to: date | None, today: date) -> tuple[date, date]:
    end = date_to or today
    start = date_from or end - timedelta(days=DEFAULT_RANGE_DAYS - 1)
    if start > end:
        raise AnalyticsRangeError("dateFrom must not be after dateTo.")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise AnalyticsRangeError(f"The range may cover at most {MAX_RANGE_DAYS} days.")
    return start, end


def ratio(part: int, whole: int) -> float | None:
    return round(part / whole, ROUNDING) if whole > 0 else None


def zero_filled_days(start: date, end: date, counts: OutcomeCounts) -> list[DayOutcomeView]:
    days: list[DayOutcomeView] = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        completed = counts.get((day, "completed"), 0)
        failed = counts.get((day, "failed"), 0)
        cancelled = counts.get((day, "cancelled"), 0)
        days.append(
            DayOutcomeView(
                day=day,
                completed=completed,
                failed=failed,
                cancelled=cancelled,
                success_rate=ratio(completed, completed + failed),
            )
        )
    return days


def overall_success_rate(days: Sequence[DayOutcomeView]) -> float | None:
    completed = sum(day.completed for day in days)
    failed = sum(day.failed for day in days)
    return ratio(completed, completed + failed)


def stage_views(averages: Sequence[StageAverage]) -> list[StageDurationView]:
    return [
        StageDurationView(
            stage=average.stage,
            average_seconds=round(average.average_ms / MS_PER_SECOND, ROUNDING),
            samples=average.samples,
        )
        for average in sorted(averages, key=lambda item: item.stage)
    ]


def repair_rate(totals: SceneTotals) -> float | None:
    return ratio(totals.repaired, totals.scenes)


def fallback_rate(totals: SceneTotals) -> float | None:
    return ratio(totals.fallbacks, totals.scenes)
