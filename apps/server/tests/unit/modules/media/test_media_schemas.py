from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from motionile.modules.media.schemas import (
    AttributionText,
    Bpm,
    HttpsUrl,
    LicenseName,
    Mood,
    MusicListQuery,
    MusicUpdateRequest,
    Title,
)

FIELD_TYPES: dict[str, Any] = {
    "title": Title,
    "mood": Mood,
    "bpm": Bpm,
    "license_name": LicenseName,
    "license_url": HttpsUrl,
    "attribution_text": AttributionText,
}


def validated(name: str, value: object) -> Any:
    return TypeAdapter(FIELD_TYPES[name]).validate_python(value)


def test_field_types_strip_whitespace() -> None:
    assert validated("title", "  Slow dawn  ") == "Slow dawn"
    assert validated("license_name", "  CC BY  ") == "CC BY"
    assert validated("attribution_text", "  By someone ") == "By someone"
    assert validated("license_url", "  https://example.com/license  ") == "https://example.com/license"
    assert validated("mood", " calm ") == "calm"


def test_field_types_accept_in_range_values() -> None:
    assert validated("bpm", "90") == 90
    assert validated("bpm", 30) == 30
    assert validated("bpm", 300) == 300
    assert validated("mood", "lo-fi2") == "lo-fi2"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("title", ""),
        ("title", "   "),
        ("title", "x" * 121),
        ("mood", "Calm"),
        ("mood", "x"),
        ("mood", "1calm"),
        ("mood", "a" * 41),
        ("bpm", 29),
        ("bpm", 301),
        ("license_name", ""),
        ("license_name", "x" * 121),
        ("license_url", "http://example.com/license"),
        ("license_url", "https://example.com/with space"),
        ("license_url", "ftp://example.com/x"),
        ("license_url", "https://" + "a" * 2000),
        ("attribution_text", ""),
        ("attribution_text", "x" * 501),
    ],
)
def test_field_types_reject_out_of_bounds_values(name: str, value: object) -> None:
    with pytest.raises(ValidationError):
        validated(name, value)


def test_an_update_needs_at_least_one_field() -> None:
    with pytest.raises(ValidationError):
        MusicUpdateRequest.model_validate({})


def test_an_update_tracks_which_fields_were_sent() -> None:
    parsed = MusicUpdateRequest.model_validate({"bpm": None, "title": " New "})

    assert parsed.model_fields_set == {"bpm", "title"}
    assert parsed.title == "New"
    assert parsed.bpm is None


@pytest.mark.parametrize("field", ["title", "mood", "licenseName", "licenseUrl"])
def test_required_columns_cannot_be_cleared(field: str) -> None:
    with pytest.raises(ValidationError):
        MusicUpdateRequest.model_validate({field: None})


def test_an_update_may_clear_the_optional_columns() -> None:
    parsed = MusicUpdateRequest.model_validate({"bpm": None, "attributionText": None})

    assert parsed.model_fields_set == {"bpm", "attribution_text"}


def test_an_update_rejects_unknown_and_invalid_fields() -> None:
    with pytest.raises(ValidationError):
        MusicUpdateRequest.model_validate({"title": "ok", "isActive": True})
    with pytest.raises(ValidationError):
        MusicUpdateRequest.model_validate({"licenseUrl": "http://insecure.example"})


def test_the_list_query_filters_by_mood_and_state() -> None:
    parsed = MusicListQuery.model_validate({"mood": "calm", "active": "false", "limit": "5"})

    assert (parsed.mood, parsed.active, parsed.limit) == ("calm", False, 5)
    with pytest.raises(ValidationError):
        MusicListQuery.model_validate({"mood": "NOT VALID"})
    with pytest.raises(ValidationError):
        MusicListQuery.model_validate({"unexpected": "1"})
