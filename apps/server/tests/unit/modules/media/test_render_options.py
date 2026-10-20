from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from tests.unit.modules.media.render_support import SCENES, VOICE, request_options

from motionile.modules.media.render_options import (
    MAX_SCENES,
    RenderOptionsRequest,
    ResolvedVoice,
    SynthesizeNarration,
    stored_options,
)

VOICE_ID = "018f0000-0000-7000-8000-000000000001"


def synth(**overrides: Any) -> dict[str, Any]:
    narration: dict[str, Any] = {"mode": "synthesize", "voiceId": VOICE_ID, "scenes": SCENES, **overrides}
    return {"aspects": ["16:9"], "narration": narration}


def rejects(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RenderOptionsRequest.model_validate(payload)


def test_a_minimal_request_is_valid_and_defaults_apply() -> None:
    options = RenderOptionsRequest.model_validate(synth())

    assert options.fps is None
    assert options.subtitles is True
    assert options.burn_in_subtitles is False
    assert options.music_track_id is None


def test_the_stored_options_carry_the_resolved_voice_and_the_default_fps() -> None:
    stored = stored_options(RenderOptionsRequest.model_validate(synth()), VOICE, 30)

    assert stored.fps == 30
    assert isinstance(stored.narration, SynthesizeNarration)
    assert stored.narration.voice == VOICE
    dumped = stored.model_dump(mode="json", by_alias=True)
    assert dumped["musicTrackId"] is None
    assert dumped["narration"]["voice"]["providerVoiceId"] == "fake-voice-aria"
    assert dumped["aspects"] == ["16:9"]
    assert stored.scene_ids == ["intro", "outro"]


def test_a_synthesized_narration_needs_a_resolved_voice() -> None:
    with pytest.raises(ValueError, match="resolved voice"):
        stored_options(RenderOptionsRequest.model_validate(synth()), None, 30)


@pytest.mark.parametrize("aspects", [[], ["16:9", "16:9"], ["16:9", "9:16", "1:1", "16:9"], ["4:3"]])
def test_aspects_are_one_to_three_unique_known_values(aspects: list[str]) -> None:
    rejects({**synth(), "aspects": aspects})


@pytest.mark.parametrize("fps", [23, 61, 0, -1])
def test_fps_stays_between_24_and_60(fps: int) -> None:
    rejects({**synth(), "fps": fps})


def test_burn_in_requires_subtitles() -> None:
    rejects({**synth(), "subtitles": False, "burnInSubtitles": True})


def test_unknown_fields_are_rejected() -> None:
    rejects({**synth(), "bitrate": 1})
    rejects(synth(extra=1))


def test_scene_ids_must_match_the_pattern_and_be_unique() -> None:
    rejects(synth(scenes=[{"sceneId": "bad id", "text": "x"}]))
    rejects(synth(scenes=[{"sceneId": "-lead", "text": "x"}]))
    rejects(synth(scenes=[{"sceneId": "a", "text": "x"}, {"sceneId": "a", "text": "y"}]))


def test_scene_counts_and_text_are_bounded() -> None:
    rejects(synth(scenes=[]))
    rejects(synth(scenes=[{"sceneId": f"s{index}", "text": "x"} for index in range(MAX_SCENES + 1)]))
    rejects(synth(scenes=[{"sceneId": "a", "text": "x" * 2001}]))
    rejects(synth(scenes=[{"sceneId": "a", "text": "   "}]))
    total = [{"sceneId": f"s{index}", "text": "x" * 2000} for index in range(11)]
    rejects(synth(scenes=total))
    accepted = [{"sceneId": f"s{index}", "text": "x" * 2000} for index in range(10)]
    assert RenderOptionsRequest.model_validate(synth(scenes=accepted)).narration.scenes[0].scene_id == "s0"


def test_text_is_stripped() -> None:
    options = RenderOptionsRequest.model_validate(synth(scenes=[{"sceneId": " a ", "text": "  hello  "}]))

    assert options.narration.scenes[0].text == "hello"


def test_an_uploaded_narration_names_unique_audio_parts() -> None:
    payload = {
        "aspects": ["1:1"],
        "narration": {
            "mode": "upload",
            "scenes": [
                {"sceneId": "a", "audioPart": "audio-a"},
                {"sceneId": "b", "audioPart": "audio-b", "text": "hello"},
            ],
        },
    }
    assert len(RenderOptionsRequest.model_validate(payload).narration.scenes) == 2
    payload["narration"]["scenes"][1]["audioPart"] = "audio-a"  # type: ignore[index]
    rejects(payload)


def test_an_upload_scene_cannot_carry_a_voice() -> None:
    rejects({"aspects": ["1:1"], "narration": {"mode": "upload", "voiceId": VOICE_ID, "scenes": []}})


def test_the_voice_id_is_required_for_synthesis() -> None:
    narration = {"mode": "synthesize", "scenes": SCENES}
    rejects({"aspects": ["1:1"], "narration": narration})


def test_a_resolved_voice_is_bounded() -> None:
    with pytest.raises(ValidationError):
        ResolvedVoice(voice_id=UUID(int=1), provider="Bad Name", provider_voice_id="x", language="en")


def test_request_helper_builds_valid_options() -> None:
    assert request_options().aspects
