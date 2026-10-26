import pytest
from pydantic import JsonValue
from structlog.testing import capture_logs

from motionile.engine.ai.graphs.events import ALLOWED_PAYLOAD_KEYS
from motionile.modules.generation.event_payloads import EVENT_PAYLOAD_KEYS, MAX_STRING_CHARS, sanitize_payload


def test_the_allowlist_covers_every_event_the_graph_can_emit() -> None:
    for event, keys in ALLOWED_PAYLOAD_KEYS.items():
        assert EVENT_PAYLOAD_KEYS[event.value] == keys


def test_known_keys_are_kept() -> None:
    payload: dict[str, JsonValue] = {"stage": "plan", "durationMs": 1200}

    assert sanitize_payload("stage.completed", payload) == payload


def test_unknown_keys_are_dropped_and_logged_by_name_only() -> None:
    payload: dict[str, JsonValue] = {"stage": "plan", "prompt": "secret system text"}

    with capture_logs() as logs:
        cleaned = sanitize_payload("stage.started", payload)

    assert cleaned == {"stage": "plan"}
    dropped = [entry for entry in logs if entry["event"] == "generation.event_payload_keys_dropped"]
    assert dropped[0]["keys"] == ["prompt"]
    assert "secret system text" not in str(logs)


def test_nested_objects_are_dropped_even_under_an_allowed_key() -> None:
    cleaned = sanitize_payload("scene.fallback", {"sceneId": "intro", "reason": {"raw": "model output"}})

    assert cleaned == {"sceneId": "intro"}


def test_lists_of_scalars_are_kept_and_lists_of_objects_are_not() -> None:
    assert sanitize_payload("context.ready", {"skills": ["a", "b"]}) == {"skills": ["a", "b"]}
    assert sanitize_payload("context.ready", {"skills": [{"slug": "a"}]}) == {}


def test_long_strings_are_clipped() -> None:
    cleaned = sanitize_payload("job.failed", {"message": "x" * 2_000})

    assert cleaned == {"message": "x" * MAX_STRING_CHARS}


def test_null_values_of_allowed_keys_survive() -> None:
    assert sanitize_payload("render.progress", {"renderId": "r", "stage": None, "progress": 10}) == {
        "renderId": "r",
        "stage": None,
        "progress": 10,
    }


def test_an_unknown_event_type_carries_no_payload() -> None:
    with capture_logs() as logs:
        cleaned = sanitize_payload("mystery.event", {"anything": 1})

    assert cleaned == {}
    assert logs[0]["event_type"] == "mystery.event"


@pytest.mark.parametrize("event_type", sorted(EVENT_PAYLOAD_KEYS))
def test_payload_keys_are_camel_case_scalars_names(event_type: str) -> None:
    assert all(key.isidentifier() and key[0].islower() for key in EVENT_PAYLOAD_KEYS[event_type])
