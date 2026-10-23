import io
from dataclasses import replace
from typing import Any

import pytest
from PIL import Image

from motionile.engine.audio.narration_models import NarrationScene
from motionile.engine.render.models import Aspect, IssueCode, ValidationIssue
from motionile.engine.render.sandbox import CompositionInfo, SceneInfo
from motionile.engine.render.synthetic import SyntheticScene, build_synthetic_narration
from motionile.engine.render.validate import (
    ImportantItem,
    Probe,
    Rect,
    Rgba,
    SampleContext,
    TextItem,
    analyze_contrast,
    animating_keys,
    contract_issues,
    contrast_ratio,
    deduplicate,
    is_blank,
    layout_issues,
    parse_probe,
    pixel_contrast,
    relative_luminance,
    required_contrast,
    sample_times,
)

NARRATION = build_synthetic_narration([SyntheticScene("a", "one two three"), SyntheticScene("b", "four five six")])
WHITE = Rgba(255, 255, 255, 1.0)


def png(color: tuple[int, int, int], size: tuple[int, int] = (200, 100)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


DEFAULT_RECT = Rect(200, 200, 300, 50)
BASE_ITEM = TextItem(
    index=0,
    selector="#a",
    scene="a",
    rect=DEFAULT_RECT,
    line_rects=(DEFAULT_RECT,),
    element_rect=DEFAULT_RECT,
    font_size_px=40,
    font_weight=400,
    fill=WHITE,
    clip_text=False,
    opacity=1.0,
    visible=True,
    overflow_x=0,
    overflow_y=0,
    important=False,
    text="text",
)


def item(index: int = 0, **changes: Any) -> TextItem:
    values: dict[str, Any] = {"index": index}
    for key, value in changes.items():
        if key == "rect":
            values.update(rect=value, line_rects=(value,), element_rect=value)
        elif key == "font_size":
            values["font_size_px"] = value
        elif key == "weight":
            values["font_weight"] = value
        elif key == "overflow":
            values.update(overflow_x=value[0], overflow_y=value[1])
        else:
            values[key] = value
    return replace(BASE_ITEM, **values)


def issues_for(
    *items: TextItem, aspect: Aspect = Aspect.LANDSCAPE, contrast: dict[int, float] | None = None
) -> list[ValidationIssue]:
    context = SampleContext(aspect, "a", 100)
    return layout_issues(Probe(items, ()), frozenset(), context, aspect.spec, contrast or {})


def codes(issues: list[ValidationIssue]) -> list[str]:
    return [issue.code for issue in issues]


def info(**overrides: Any) -> CompositionInfo:
    scenes = tuple(SceneInfo(s.id, s.start_ms, s.end_ms, s.end_ms) for s in NARRATION.scenes)
    base: dict[str, Any] = {
        "duration_ms": NARRATION.total_duration_ms,
        "timeline_duration_ms": NARRATION.total_duration_ms,
        "aspects": ("16:9", "9:16", "1:1"),
        "scenes": scenes,
        "scene_elements": ("a", "b"),
    }
    return CompositionInfo(**{**base, **overrides})


def test_sample_times_are_fifty_ms_inside_the_scene_edges() -> None:
    scene = NARRATION.scenes[1]

    start, middle, end = sample_times(scene)

    assert start == scene.start_ms + 50
    assert end == scene.end_ms - 50
    assert middle == scene.start_ms + scene.duration_ms // 2


def test_sample_times_for_a_very_short_scene_stay_ordered() -> None:
    short = NarrationScene(id="a", index=0, start_ms=0, duration_ms=40, text="x", words=())

    start, middle, end = sample_times(short)

    assert start <= middle <= end


def test_luminance_and_contrast_match_wcag_reference_values() -> None:
    assert relative_luminance(255, 255, 255) == pytest.approx(1.0)
    assert relative_luminance(0, 0, 0) == pytest.approx(0.0)
    assert contrast_ratio(1.0, 0.0) == pytest.approx(21.0)
    assert contrast_ratio(0.0, 1.0) == pytest.approx(21.0)


def test_pixel_contrast_blends_the_text_alpha_with_the_background() -> None:
    opaque = pixel_contrast(WHITE, 1.0, (14, 14, 16))
    faded = pixel_contrast(WHITE, 0.3, (14, 14, 16))

    assert opaque > 15
    assert faded < opaque
    assert pixel_contrast(Rgba(0, 0, 0, 0.0), 1.0, (14, 14, 16)) == pytest.approx(1.0)


def test_required_contrast_is_three_for_large_text_and_four_and_a_half_otherwise() -> None:
    assert required_contrast(item(font_size=30)) == 3.0
    assert required_contrast(item(font_size=20, weight=700)) == 3.0
    assert required_contrast(item(font_size=20, weight=400)) == 4.5


def test_analyze_contrast_samples_the_pixels_behind_each_text_box() -> None:
    dark = analyze_contrast(png((14, 14, 16)), [item(rect=Rect(10, 10, 80, 30), fill=WHITE)])
    low = analyze_contrast(png((230, 230, 230)), [item(rect=Rect(10, 10, 80, 30), fill=WHITE)])

    assert dark[0] > 10
    assert low[0] < 1.5


def test_analyze_contrast_skips_boxes_outside_the_image() -> None:
    assert analyze_contrast(png((0, 0, 0)), [item(rect=Rect(5000, 5000, 10, 10))]) == {}


def test_blank_detection() -> None:
    buffer = io.BytesIO()
    image = Image.new("RGB", (50, 50), (14, 14, 16))
    image.putpixel((3, 3), (240, 240, 240))
    image.save(buffer, format="PNG")

    assert is_blank(png((14, 14, 16))) is True
    assert is_blank(buffer.getvalue()) is False


def test_clean_text_has_no_issues() -> None:
    assert issues_for(item(rect=Rect(200, 200, 300, 50)), contrast={0: 15.0}) == []


def test_font_too_small_uses_the_aspect_minimum() -> None:
    landscape = issues_for(item(font_size=27), aspect=Aspect.LANDSCAPE)
    portrait = issues_for(item(font_size=33, rect=Rect(200, 400, 300, 50)), aspect=Aspect.PORTRAIT)
    fine = issues_for(item(font_size=34, rect=Rect(200, 400, 300, 50)), aspect=Aspect.PORTRAIT)

    assert codes(landscape) == ["font_too_small"]
    assert codes(portrait) == ["font_too_small"]
    assert portrait[0].detail == {"fontSizePx": 33.0, "minimumPx": 34}
    assert fine == []


def test_text_overflow_over_two_pixels_is_reported() -> None:
    assert codes(issues_for(item(overflow=(0, 3)))) == ["text_overflow"]
    assert issues_for(item(overflow=(2, 2))) == []


def test_safe_area_violation_per_aspect() -> None:
    inside = Rect(96, 64, 1728, 856)
    left = Rect(90, 200, 100, 40)
    bottom = Rect(200, 1000, 100, 40)

    assert issues_for(item(rect=inside)) == []
    assert codes(issues_for(item(rect=left))) == ["safe_area_violation"]
    assert codes(issues_for(item(rect=bottom))) == ["safe_area_violation"]
    assert issues_for(item(rect=Rect(200, 1000, 100, 40)), aspect=Aspect.SQUARE)[0].code == "safe_area_violation"


def test_offscreen_text_is_reported_in_addition_to_the_safe_area() -> None:
    result = issues_for(item(rect=Rect(1800, 200, 400, 50)))

    assert set(codes(result)) == {"safe_area_violation", "element_offscreen"}


def test_overlapping_text_boxes_are_reported_but_nested_ones_are_not() -> None:
    first = item(0, rect=Rect(200, 200, 300, 50), selector="#a")
    second = item(1, rect=Rect(250, 210, 300, 50), selector="#b")
    nested = item(2, rect=Rect(250, 210, 300, 50), selector="#a > span")
    touching = item(3, rect=Rect(500, 200, 100, 50), selector="#c")

    assert codes(issues_for(first, second)) == ["text_overlap"]
    assert issues_for(first, nested) == []
    assert issues_for(first, touching) == []


def test_small_overlaps_below_sixteen_square_pixels_are_ignored() -> None:
    first = item(0, rect=Rect(200, 200, 100, 50), selector="#a")
    second = item(1, rect=Rect(297, 247, 100, 50), selector="#b")

    assert issues_for(first, second) == []


def test_low_contrast_is_reported_against_the_required_ratio() -> None:
    low = issues_for(item(font_size=40), contrast={0: 2.0})
    small_text_low = issues_for(item(font_size=20), contrast={0: 3.5})

    assert codes(low) == ["contrast_low"]
    assert low[0].detail == {"ratio": 2.0, "required": 3.0}
    assert "contrast_low" in codes(small_text_low)


def test_invisible_and_animating_text_is_not_checked() -> None:
    hidden = item(font_size=10, opacity=0.01)
    moving = item(1, font_size=10, selector="#moving")
    context = SampleContext(Aspect.LANDSCAPE, "a", 100)

    result = layout_issues(Probe((hidden, moving), ()), frozenset({"#moving"}), context, Aspect.LANDSCAPE.spec, {})

    assert result == []


def test_animating_keys_detects_movement_opacity_and_structure_changes() -> None:
    still = item(0, selector="#still")
    mover = item(1, selector="#mover", rect=Rect(300, 300, 100, 40))
    faded = item(2, selector="#fader", opacity=0.5)
    before = Probe((still, mover, faded), ())
    after = Probe(
        (still, item(1, selector="#mover", rect=Rect(300, 320, 100, 40)), item(2, selector="#fader", opacity=0.8)),
        (),
    )

    assert animating_keys(before, after) == {"#mover", "#fader"}
    assert animating_keys(before, Probe((still,), ())) == {"#still", "#mover", "#fader"}


def test_parse_probe_reads_the_browser_payload() -> None:
    rect = {"x": 1, "y": 2, "width": 3, "height": 4}
    payload = {
        "texts": [
            {
                "index": 0,
                "selector": "#a",
                "scene": None,
                "rect": rect,
                "lineRects": [rect],
                "elementRect": rect,
                "fontSizePx": 40,
                "fontWeight": 700,
                "fill": {"r": 1, "g": 2, "b": 3, "a": 0.5},
                "clipText": False,
                "opacity": 1,
                "visible": True,
                "overflowX": 0,
                "overflowY": 0,
                "important": False,
                "text": "hi",
            }
        ],
        "important": [{"index": 0, "selector": "#i", "rect": rect, "opacity": 1, "visible": True}],
    }

    probe = parse_probe(payload)

    assert probe.texts[0].fill == Rgba(1, 2, 3, 0.5)
    assert probe.texts[0].scene is None
    assert probe.important[0].rect == Rect(1, 2, 3, 4)


def test_important_elements_outside_the_viewport_are_reported() -> None:
    outside = ImportantItem(0, "#logo", Rect(1900, 100, 200, 100), 1.0, True)
    inside = ImportantItem(1, "#ok", Rect(100, 100, 200, 100), 1.0, True)
    context = SampleContext(Aspect.LANDSCAPE, "a", 100)

    result = layout_issues(Probe((), (outside, inside)), frozenset(), context, Aspect.LANDSCAPE.spec, {})

    assert [(issue.code, issue.selector) for issue in result] == [("element_offscreen", "#logo")]


def test_a_matching_composition_has_no_contract_issues() -> None:
    assert contract_issues(info(), NARRATION, Aspect.LANDSCAPE) == []


def test_missing_composition_is_reported() -> None:
    assert codes(contract_issues(None, NARRATION, Aspect.LANDSCAPE)) == ["composition_missing"]


def test_scene_mismatch_and_missing_elements() -> None:
    wrong_scenes = (SceneInfo("a", 0, 100, 100), SceneInfo("x", 100, 200, 200))

    result = contract_issues(info(scenes=wrong_scenes, scene_elements=("a",)), NARRATION, Aspect.LANDSCAPE)

    assert {"scene_mismatch", "scene_element_missing"} <= set(codes(result))


def test_unsupported_aspect() -> None:
    result = contract_issues(info(aspects=("16:9",)), NARRATION, Aspect.PORTRAIT)

    assert codes(result) == ["aspect_unsupported"]


def test_duration_mismatch_beyond_fifty_milliseconds() -> None:
    total = NARRATION.total_duration_ms

    assert contract_issues(info(timeline_duration_ms=total + 50), NARRATION, Aspect.LANDSCAPE) == []
    assert codes(contract_issues(info(timeline_duration_ms=total + 51), NARRATION, Aspect.LANDSCAPE)) == [
        "duration_mismatch"
    ]


def test_scene_boundary_mismatch_and_overflow() -> None:
    first, second = NARRATION.scenes
    shifted = (
        SceneInfo("a", first.start_ms, first.end_ms + 120, first.end_ms + 120),
        SceneInfo("b", second.start_ms, second.end_ms, second.end_ms + 200),
    )

    result = contract_issues(info(scenes=shifted), NARRATION, Aspect.LANDSCAPE)

    assert {"scene_boundary_mismatch", "scene_overflow"} <= set(codes(result))


def test_content_ending_within_tolerance_is_not_an_overflow() -> None:
    first, second = NARRATION.scenes
    scenes = (
        SceneInfo("a", first.start_ms, first.end_ms, first.end_ms + 50),
        SceneInfo("b", second.start_ms, second.end_ms, second.end_ms),
    )

    assert contract_issues(info(scenes=scenes), NARRATION, Aspect.LANDSCAPE) == []


def test_deduplicate_keeps_the_first_occurrence_per_element() -> None:
    context_a = SampleContext(Aspect.LANDSCAPE, "a", 100)
    context_b = SampleContext(Aspect.LANDSCAPE, "a", 900)
    first = issues_for(item(overflow=(0, 9)))
    again = layout_issues(Probe((item(overflow=(0, 9)),), ()), frozenset(), context_b, Aspect.LANDSCAPE.spec, {})

    merged = deduplicate([*first, *again])

    assert len(merged) == 1
    assert merged[0].time_ms == context_a.time_ms
    assert merged[0].code == IssueCode.TEXT_OVERFLOW
