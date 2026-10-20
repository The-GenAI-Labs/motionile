import json
import re
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"
GOLDEN_NAMES = (
    "kinetic-typography",
    "flow-diagram",
    "code-walkthrough",
    "data-structure",
    "comparison-split",
    "css-animation-scene",
    "responsive-scene",
)
MALICIOUS_TECHNIQUES = (
    "exfil_fetch",
    "exfil_xhr",
    "exfil_websocket",
    "exfil_beacon",
    "external_image",
    "external_font",
    "external_css",
    "css_import",
    "iframe_embed",
    "meta_refresh",
    "window_open",
    "location_navigation",
    "service_worker",
    "webrtc",
    "file_image",
    "file_fetch",
    "metadata_image",
    "metadata_fetch",
    "infinite_loop",
    "dom_bomb",
    "memory_bomb",
    "oversized_data_uri",
)


def test_exactly_the_documented_golden_compositions_exist() -> None:
    names = {path.name for path in (FIXTURES / "compositions").iterdir() if path.is_dir()}

    assert names == set(GOLDEN_NAMES)


@pytest.mark.parametrize("name", GOLDEN_NAMES)
def test_golden_narration_matches_the_scene_elements(name: str) -> None:
    directory = FIXTURES / "compositions" / name
    narration = json.loads((directory / "narration.json").read_text(encoding="utf-8"))
    html = (directory / "composition.html").read_text(encoding="utf-8")

    scene_ids = [scene["sceneId"] for scene in narration["scenes"]]
    elements = re.findall(r'data-scene="([^"]+)"', html)

    assert narration["language"] == "en"
    assert all(scene["text"].strip() for scene in narration["scenes"])
    assert elements == scene_ids
    assert html.count("Motionile.composition(") == 1


@pytest.mark.parametrize("technique", MALICIOUS_TECHNIQUES)
def test_every_required_malicious_technique_has_a_fixture(technique: str) -> None:
    assert (FIXTURES / "malicious" / f"{technique}.html").is_file()


def test_every_malicious_fixture_defines_the_scene_the_tests_render() -> None:
    files = sorted((FIXTURES / "malicious").glob("*.html"))

    assert len(files) >= len(MALICIOUS_TECHNIQUES)
    assert all('data-scene="main"' in path.read_text(encoding="utf-8") for path in files)
