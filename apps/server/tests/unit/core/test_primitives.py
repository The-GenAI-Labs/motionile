from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from motionile.core.clock import FrozenClock, SystemClock
from motionile.core.ids import is_uuid7, new_id
from motionile.core.schemas import CursorPage, PageQuery, ResponseModel, StrictModel


class CreateThing(StrictModel):
    display_name: str
    item_count: int = 1


class ThingView(ResponseModel):
    display_name: str


def test_new_id_returns_time_ordered_uuid7() -> None:
    first, second = new_id(), new_id()

    assert is_uuid7(first)
    assert first < second


def test_system_clock_returns_aware_utc_time() -> None:
    now = SystemClock().now()

    assert now.tzinfo is UTC


def test_frozen_clock_advances_only_when_told() -> None:
    clock = FrozenClock(datetime(2026, 1, 1, tzinfo=UTC))

    clock.advance(timedelta(minutes=5))

    assert clock.now() == datetime(2026, 1, 1, 0, 5, tzinfo=UTC)
    clock.set(datetime(2027, 1, 1, tzinfo=UTC))
    assert clock.now().year == 2027


def test_frozen_clock_requires_timezone() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        FrozenClock(datetime(2026, 1, 1))


def test_strict_model_accepts_camel_case_and_strips_whitespace() -> None:
    thing = CreateThing.model_validate({"displayName": "  Motionile  ", "itemCount": 2})

    assert thing.display_name == "Motionile"
    assert thing.model_dump(by_alias=True) == {"displayName": "Motionile", "itemCount": 2}


def test_strict_model_accepts_field_names() -> None:
    assert CreateThing.model_validate({"display_name": "x"}).display_name == "x"


def test_strict_model_forbids_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="extra"):
        CreateThing.model_validate({"displayName": "x", "role": "admin"})


def test_cursor_page_serializes_in_camel_case() -> None:
    page = CursorPage[ThingView](items=[ThingView(display_name="a")], next_cursor="abc")

    assert page.model_dump(mode="json") == {"items": [{"displayName": "a"}], "nextCursor": "abc"}


@pytest.mark.parametrize("limit", [0, 101])
def test_page_query_bounds_limit(limit: int) -> None:
    with pytest.raises(ValidationError):
        PageQuery(limit=limit)
