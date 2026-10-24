import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

import tinycss2
from tinycss2 import color3
from tinycss2.ast import Declaration, FunctionBlock, HashToken, Node, ParseError

from motionile.engine.render.validate import contrast_ratio, relative_luminance

TOKEN_NAMES = (
    "--mo-bg",
    "--mo-surface",
    "--mo-elevated",
    "--mo-border",
    "--mo-text-muted",
    "--mo-text-secondary",
    "--mo-text",
    "--mo-accent",
    "--mo-danger",
    "--mo-success",
)
BACKGROUND_TOKENS = ("--mo-bg", "--mo-surface")
TEXT_TOKENS = (
    "--mo-text-muted",
    "--mo-text-secondary",
    "--mo-text",
    "--mo-accent",
    "--mo-danger",
    "--mo-success",
)
MIN_TEXT_CONTRAST = 4.5
COLOR_FUNCTIONS = frozenset({"rgb", "rgba", "hsl", "hsla"})
HEX_DIGITS = re.compile(r"^(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
CHANNEL_MAX = 255
BRAND_PALETTE: Mapping[str, str] = MappingProxyType(
    {
        "--mo-bg": "#0e0e10",
        "--mo-surface": "#16161a",
        "--mo-elevated": "#1e1e23",
        "--mo-border": "#2a2a30",
        "--mo-text-muted": "#8a8a93",
        "--mo-text-secondary": "#b4b4bc",
        "--mo-text": "#f2f2f3",
        "--mo-accent": "#fafafa",
        "--mo-danger": "#e5484d",
        "--mo-success": "#3dd68c",
    }
)


class StyleTokenError(ValueError):
    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True, slots=True)
class StyleTokens:
    slug: str
    properties: Mapping[str, str] = field(default_factory=lambda: MappingProxyType(dict[str, str]()))

    @property
    def has_overrides(self) -> bool:
        return bool(self.properties)

    @property
    def palette(self) -> dict[str, str]:
        return {**BRAND_PALETTE, **self.properties}

    @property
    def css_declarations(self) -> str:
        return ";".join(f"{name}:{self.properties[name]}" for name in TOKEN_NAMES if name in self.properties)


def to_hex(red: float, green: float, blue: float) -> str:
    channels = (round(max(0.0, min(1.0, value)) * CHANNEL_MAX) for value in (red, green, blue))
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def parse_color_token(token: Node) -> str | None:
    if isinstance(token, HashToken):
        if not HEX_DIGITS.match(token.value):
            return None
    elif not isinstance(token, FunctionBlock) or token.lower_name not in COLOR_FUNCTIONS:
        return None
    parsed = color3.parse_color(token.serialize())
    if not isinstance(parsed, color3.RGBA):
        return None
    red, green, blue, alpha = cast("tuple[float, float, float, float]", tuple(parsed))
    if alpha != 1.0:
        return None
    return to_hex(red, green, blue)


def parse_declaration(declaration: Declaration) -> tuple[str, str] | str:
    name = declaration.name
    if name not in TOKEN_NAMES:
        return f"{name} is not a style token; the known tokens are {', '.join(TOKEN_NAMES)}"
    if declaration.important:
        return f"{name} must not be !important"
    values = [token for token in declaration.value if token.type not in {"whitespace", "comment"}]
    color = parse_color_token(values[0]) if len(values) == 1 else None
    if color is None:
        return f"{name} must be an opaque hex, rgb(), rgba(), hsl() or hsla() colour"
    return name, color


def luminance(color: str) -> float:
    return relative_luminance(int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))


def contrast_problems(properties: Mapping[str, str]) -> list[str]:
    palette = {**BRAND_PALETTE, **properties}
    problems: list[str] = []
    for background in BACKGROUND_TOKENS:
        for text in TEXT_TOKENS:
            ratio = contrast_ratio(luminance(palette[text]), luminance(palette[background]))
            if ratio < MIN_TEXT_CONTRAST:
                problems.append(
                    f"{text} {palette[text]} has contrast {ratio:.2f}:1 against {background} {palette[background]}; "
                    f"WCAG AA needs {MIN_TEXT_CONTRAST}:1"
                )
    return problems


def parse_style_tokens(css_declarations: str, *, slug: str = "custom") -> StyleTokens:
    problems: list[str] = []
    properties: dict[str, str] = {}
    for item in tinycss2.parse_blocks_contents(css_declarations, skip_comments=True, skip_whitespace=True):
        if isinstance(item, Declaration):
            parsed = parse_declaration(item)
            if isinstance(parsed, str):
                problems.append(parsed)
            elif parsed[0] in properties:
                problems.append(f"{parsed[0]} is set twice")
            else:
                properties[parsed[0]] = parsed[1]
        elif isinstance(item, ParseError):
            problems.append(item.message)
        else:
            problems.append("Only custom property declarations are allowed")
    if not problems and properties:
        problems.extend(contrast_problems(properties))
    if problems:
        raise StyleTokenError(tuple(problems))
    return StyleTokens(slug=slug, properties=MappingProxyType(properties))


DEFAULT_STYLE_TOKENS = parse_style_tokens("", slug="minimal-dark")

STYLE_TOKEN_SOURCES: Mapping[str, str] = MappingProxyType(
    {
        "minimal-dark": "",
        "whiteboard": (
            "--mo-bg:#fbfaf6;--mo-surface:#f1efe7;--mo-elevated:#e8e5da;--mo-border:#c9c3b0;"
            "--mo-text-muted:#5b5a55;--mo-text-secondary:#3a3935;--mo-text:#16150f;"
            "--mo-accent:#1d4ed8;--mo-danger:#b42318;--mo-success:#166534"
        ),
        "blueprint": (
            "--mo-bg:#0b2447;--mo-surface:#123166;--mo-elevated:#19408a;--mo-border:#3b6ab0;"
            "--mo-text-muted:#a9c3e6;--mo-text-secondary:#d4e5ff;--mo-text:#ffffff;"
            "--mo-accent:#5ee6ff;--mo-danger:#ff9b94;--mo-success:#7dffb2"
        ),
        "terminal": (
            "--mo-bg:#070a07;--mo-surface:#0e140e;--mo-elevated:#162016;--mo-border:#2a4a2a;"
            "--mo-text-muted:#6ea872;--mo-text-secondary:#ffc233;--mo-text:#5dff8f;"
            "--mo-accent:#ffb000;--mo-danger:#ff6b6b;--mo-success:#5dff8f"
        ),
        "editorial-light": (
            "--mo-bg:#faf7f2;--mo-surface:#f1ece3;--mo-elevated:#e8e1d4;--mo-border:#cfc4ad;"
            "--mo-text-muted:#645d52;--mo-text-secondary:#3d3832;--mo-text:#1a1816;"
            "--mo-accent:#c0262d;--mo-danger:#b42318;--mo-success:#1e6b3a"
        ),
    }
)
STYLE_TOKEN_SETS: Mapping[str, StyleTokens] = MappingProxyType(
    {slug: parse_style_tokens(source, slug=slug) for slug, source in STYLE_TOKEN_SOURCES.items()}
)


def style_tokens_for(slug: str) -> StyleTokens | None:
    return STYLE_TOKEN_SETS.get(slug)
