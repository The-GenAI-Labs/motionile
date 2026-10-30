import re
from importlib import resources

import pytest

from motionile.engine.ai.scenes.style_tokens import (
    BACKGROUND_TOKENS,
    BRAND_PALETTE,
    DEFAULT_STYLE_TOKENS,
    MIN_TEXT_CONTRAST,
    STYLE_TOKEN_SETS,
    STYLE_TOKEN_SOURCES,
    TEXT_TOKENS,
    TOKEN_NAMES,
    StyleTokenError,
    luminance,
    parse_style_tokens,
    style_tokens_for,
)
from motionile.engine.render.contrast import contrast_ratio

STYLE_SLUGS = ("minimal-dark", "whiteboard", "blueprint", "terminal", "editorial-light")


def base_css_palette() -> dict[str, str]:
    css = (resources.files("motionile.engine.render.runtime") / "v1" / "base.css").read_text(encoding="utf-8")
    root_block = css.split("}", 1)[0]
    return dict(
        re.findall(
            r"(--mo-(?:bg|surface|elevated|border|text-muted|text-secondary|text|accent|danger|success)):\s*(#[0-9a-f]{6});",
            root_block,
        )
    )


def test_the_brand_palette_matches_base_css() -> None:
    assert dict(BRAND_PALETTE) == base_css_palette()


def test_all_five_style_sets_ship() -> None:
    assert tuple(STYLE_TOKEN_SETS) == STYLE_SLUGS
    assert style_tokens_for("terminal") is STYLE_TOKEN_SETS["terminal"]
    assert style_tokens_for("unknown") is None


def test_minimal_dark_is_the_default_with_no_overrides() -> None:
    assert DEFAULT_STYLE_TOKENS.slug == "minimal-dark"
    assert not DEFAULT_STYLE_TOKENS.has_overrides
    assert DEFAULT_STYLE_TOKENS.css_declarations == ""
    assert DEFAULT_STYLE_TOKENS.palette == dict(BRAND_PALETTE)


@pytest.mark.parametrize("slug", STYLE_SLUGS)
def test_every_shipped_set_meets_wcag_aa_on_the_backgrounds(slug: str) -> None:
    palette = STYLE_TOKEN_SETS[slug].palette

    for background in BACKGROUND_TOKENS:
        for text in TEXT_TOKENS:
            ratio = contrast_ratio(luminance(palette[text]), luminance(palette[background]))
            assert ratio >= MIN_TEXT_CONTRAST, f"{slug}: {text} on {background} is {ratio:.2f}"


@pytest.mark.parametrize("slug", STYLE_SLUGS[1:])
def test_non_default_sets_override_every_token(slug: str) -> None:
    assert set(STYLE_TOKEN_SETS[slug].properties) == set(TOKEN_NAMES)


def test_the_whiteboard_and_editorial_sets_are_light_and_the_others_dark() -> None:
    light = {slug for slug in STYLE_SLUGS if luminance(STYLE_TOKEN_SETS[slug].palette["--mo-bg"]) > 0.5}

    assert light == {"whiteboard", "editorial-light"}


def test_each_set_round_trips_through_its_css_declarations() -> None:
    for slug, tokens in STYLE_TOKEN_SETS.items():
        assert parse_style_tokens(tokens.css_declarations, slug=slug) == tokens
        assert STYLE_TOKEN_SOURCES[slug].replace(" ", "") == tokens.css_declarations


def test_declarations_follow_the_canonical_token_order() -> None:
    tokens = parse_style_tokens("--mo-text: #ffffff; --mo-bg: #000000")

    assert tokens.css_declarations == "--mo-bg:#000000;--mo-text:#ffffff"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("--mo-border: #fff", "#ffffff"),
        ("--mo-border: #FFFFFF", "#ffffff"),
        ("--mo-border: rgb(0, 0, 0)", "#000000"),
        ("--mo-border: rgba(10, 20, 30, 1)", "#0a141e"),
        ("--mo-border: hsl(0, 0%, 0%)", "#000000"),
        ("--mo-border: hsla(240, 100%, 10%, 1)", "#000033"),
        ("  --mo-border :  #101010  ;", "#101010"),
    ],
)
def test_valid_colours_are_normalised_to_hex(source: str, expected: str) -> None:
    assert parse_style_tokens(source).properties["--mo-border"] == expected


@pytest.mark.parametrize(
    "source",
    [
        "--mo-bg: red",
        "--mo-bg: transparent",
        "--mo-bg: currentcolor",
        "--mo-bg: rgba(0, 0, 0, 0.5)",
        "--mo-bg: #0000",
        "--mo-bg: #12345",
        "--mo-bg: #zzzzzz",
        "--mo-bg: var(--mo-surface)",
        "--mo-bg: url(https://evil.example/a.png)",
        "--mo-bg: #000 #111",
        "--mo-bg: ",
        "--mo-bg: #000 !important",
        "--mo-bg: #000; --mo-bg: #111",
        "--mo-unknown: #000",
        "--mo-text-title: 90px",
        "color: #000",
        "--other: #000",
        ".a { --mo-bg: #000 }",
        "@media print { --mo-bg: #000 }",
        "--mo-bg #000",
    ],
)
def test_invalid_declarations_are_rejected(source: str) -> None:
    with pytest.raises(StyleTokenError) as caught:
        parse_style_tokens(source)

    assert caught.value.problems


def test_low_contrast_text_against_an_overridden_background_is_rejected() -> None:
    with pytest.raises(StyleTokenError) as caught:
        parse_style_tokens("--mo-bg: #ffffff")

    assert any("--mo-text " in problem or "--mo-text-muted" in problem for problem in caught.value.problems)
    assert all("WCAG AA" in problem for problem in caught.value.problems)


def test_a_dark_text_override_on_the_default_dark_background_is_rejected() -> None:
    with pytest.raises(StyleTokenError):
        parse_style_tokens("--mo-text: #222222")


def test_contrast_is_judged_against_the_surface_too() -> None:
    with pytest.raises(StyleTokenError) as caught:
        parse_style_tokens("--mo-surface: #f0f0f0")

    assert any("--mo-surface" in problem for problem in caught.value.problems)


def test_the_exact_threshold_passes() -> None:
    tokens = parse_style_tokens("--mo-text-muted: #8a8a93;--mo-bg: #0e0e10")

    assert tokens.properties["--mo-text-muted"] == "#8a8a93"


def test_tokens_are_immutable_and_hashable_by_value() -> None:
    first = parse_style_tokens("--mo-bg: #101010", slug="x")
    second = parse_style_tokens("--mo-bg:#101010", slug="x")

    assert first == second
    with pytest.raises(AttributeError):
        first.slug = "y"  # type: ignore[misc]
    with pytest.raises(TypeError):
        first.properties["--mo-bg"] = "#000000"  # type: ignore[index]
