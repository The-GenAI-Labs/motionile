import pytest
from hypothesis import given
from hypothesis import strategies as st

from motionile.engine.audio.models import WordTiming
from motionile.engine.audio.narration import NarrationError, SceneAudio, assemble_narration
from motionile.engine.audio.timing import is_monotonic


def scene(
    scene_id: str, duration_ms: int, words: list[tuple[str, int, int]] | None = None, text: str = "text"
) -> SceneAudio:
    return SceneAudio(
        id=scene_id,
        text=text,
        duration_ms=duration_ms,
        words=tuple(WordTiming(*word) for word in (words or [])),
    )


def test_assembly_matches_the_documented_example_shape() -> None:
    document = assemble_narration(
        [
            scene("intro", 3000, [("Every", 0, 310), ("video", 310, 640)], "Every video"),
            scene("middle", 3000, [("Next", 100, 400)], "Next"),
        ],
        padding_ms=610,
    )

    payload = document.window_payload()

    assert payload["version"] == 1
    assert payload["totalDurationMs"] == 3610 + 3000
    first, second = payload["scenes"]
    assert (first["id"], first["index"], first["startMs"], first["durationMs"]) == ("intro", 0, 0, 3610)
    assert first["words"][1] == {
        "index": 1,
        "text": "video",
        "startMs": 310,
        "endMs": 640,
        "sceneStartMs": 310,
        "sceneEndMs": 640,
    }
    assert (second["startMs"], second["durationMs"]) == (3610, 3000)
    assert second["words"][0]["startMs"] == 3710
    assert second["words"][0]["sceneStartMs"] == 100


def test_last_scene_has_no_padding_and_starts_are_cumulative() -> None:
    document = assemble_narration([scene("a", 1000), scene("b", 2000), scene("c", 500)], padding_ms=250)

    assert [item.duration_ms for item in document.scenes] == [1250, 2250, 500]
    assert [item.start_ms for item in document.scenes] == [0, 1250, 3500]
    assert document.total_duration_ms == 4000
    assert document.scenes[-1].end_ms == document.total_duration_ms


def test_single_scene_has_no_padding() -> None:
    document = assemble_narration([scene("only", 1500)], padding_ms=700)

    assert document.total_duration_ms == 1500


def test_zero_padding() -> None:
    document = assemble_narration([scene("a", 1000), scene("b", 1000)], padding_ms=0)

    assert [item.start_ms for item in document.scenes] == [0, 1000]


def test_scene_without_words_is_kept() -> None:
    document = assemble_narration([scene("a", 1000), scene("b", 1000, [("x", 0, 10)])], padding_ms=100)

    assert document.scenes[0].words == ()
    assert len(document.scenes[1].words) == 1


def test_words_are_clamped_to_the_audio_and_made_monotonic() -> None:
    document = assemble_narration(
        [scene("a", 1000, [("one", 0, 600), ("two", 500, 1400), ("three", 1200, 1500)]), scene("b", 1000)],
        padding_ms=300,
    )

    words = document.scenes[0].words
    assert [(word.scene_start_ms, word.scene_end_ms) for word in words] == [(0, 600), (600, 1000), (1000, 1000)]
    assert max(word.scene_end_ms for word in words) <= 1000


def test_blank_words_are_dropped_and_indexes_stay_dense() -> None:
    document = assemble_narration([scene("a", 1000, [("x", 0, 100), (" ", 100, 200), ("y", 200, 300)])], padding_ms=0)

    assert [(word.index, word.text) for word in document.scenes[0].words] == [(0, "x"), (1, "y")]


def test_word_indexes_restart_in_every_scene() -> None:
    document = assemble_narration(
        [scene("a", 1000, [("a", 0, 10), ("b", 10, 20)]), scene("b", 1000, [("c", 0, 10)])], padding_ms=0
    )

    assert [word.index for word in document.scenes[1].words] == [0]


@pytest.mark.parametrize(
    ("scenes", "padding"),
    [
        ([], 0),
        ([scene("a", 100), scene("a", 100)], 0),
        ([scene("a", 0)], 0),
        ([scene("a", 100)], -1),
        ([scene("a", 100)], 10_001),
    ],
)
def test_invalid_input_is_refused(scenes: list[SceneAudio], padding: int) -> None:
    with pytest.raises(NarrationError):
        assemble_narration(scenes, padding)


@st.composite
def scene_lists(draw: st.DrawFn) -> list[SceneAudio]:
    count = draw(st.integers(1, 8))
    scenes: list[SceneAudio] = []
    for index in range(count):
        duration = draw(st.integers(1, 20_000))
        words: list[WordTiming] = []
        cursor = 0
        for word_index in range(draw(st.integers(0, 12))):
            start = cursor + draw(st.integers(0, 400))
            end = start + draw(st.integers(0, 900))
            words.append(WordTiming(f"w{word_index}", start, end))
            cursor = end
        scenes.append(SceneAudio(f"s{index}", "text", duration, tuple(words)))
    return scenes


@given(scene_lists(), st.integers(0, 3000))
def test_timing_invariants(scenes: list[SceneAudio], padding: int) -> None:
    document = assemble_narration(scenes, padding)

    cursor = 0
    for position, assembled in enumerate(document.scenes):
        source = scenes[position]
        expected = source.duration_ms + (padding if position < len(scenes) - 1 else 0)
        assert assembled.start_ms == cursor
        assert assembled.duration_ms == expected
        cursor += expected
        for word in assembled.words:
            assert word.start_ms == assembled.start_ms + word.scene_start_ms
            assert word.end_ms == assembled.start_ms + word.scene_end_ms
            assert 0 <= word.scene_start_ms <= word.scene_end_ms <= source.duration_ms
        assert [word.index for word in assembled.words] == list(range(len(assembled.words)))
        assert is_monotonic([WordTiming(word.text, word.start_ms, word.end_ms) for word in assembled.words])
    assert document.total_duration_ms == cursor
