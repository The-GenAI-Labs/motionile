import json
from collections.abc import Mapping, Sequence
from html import escape

from motionile.engine.ai.scenes.js_analysis import normalize_source
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.scenes.style_tokens import StyleTokens
from motionile.engine.ai.scenes.svg_assets import check_svg_asset
from motionile.engine.ai.storyboard import Storyboard
from motionile.engine.render.runtime import RUNTIME_BASE_URL

BASE_STYLESHEET_URL = f"{RUNTIME_BASE_URL}base.css"
GSAP_SCRIPT_URL = f"{RUNTIME_BASE_URL}gsap/gsap.min.js"
RUNTIME_SCRIPT_URL = f"{RUNTIME_BASE_URL}motionile.js"
TOKENS_STYLE_ID = "mo-style-tokens"
TOKENS_SELECTOR = "html[data-aspect]"
SCENE_STYLE_ATTRIBUTE = "data-mo-scene-style"
CLOSING_TAG_OPEN = "</"
ESCAPED_CLOSING_TAG_OPEN = "<\\/"
COMMENT_OPEN = "<!--"
ESCAPED_COMMENT_OPEN = "<\\!--"


class ComposeError(ValueError):
    pass


def escape_embedded(text: str) -> str:
    return (
        normalize_source(text)
        .replace(CLOSING_TAG_OPEN, ESCAPED_CLOSING_TAG_OPEN)
        .replace(COMMENT_OPEN, ESCAPED_COMMENT_OPEN)
    )


def index_modules(modules: Sequence[SceneModule], storyboard: Storyboard) -> Mapping[str, SceneModule]:
    indexed: dict[str, SceneModule] = {}
    for module in modules:
        if module.scene_id in indexed:
            raise ComposeError(f"Scene {module.scene_id} has more than one module")
        indexed[module.scene_id] = module
    expected = [scene.id for scene in storyboard.scenes]
    missing = [scene_id for scene_id in expected if scene_id not in indexed]
    extra = sorted(set(indexed) - set(expected))
    if missing:
        raise ComposeError(f"No module for scene {', '.join(missing)}")
    if extra:
        raise ComposeError(f"Modules for scenes that are not in the storyboard: {', '.join(extra)}")
    return indexed


def tokens_style(tokens: StyleTokens) -> list[str]:
    if not tokens.has_overrides:
        return []
    return [f'<style id="{TOKENS_STYLE_ID}">{TOKENS_SELECTOR}{{{tokens.css_declarations}}}</style>']


def scene_style(module: SceneModule) -> list[str]:
    css = escape_embedded(module.css).strip()
    if not css:
        return []
    return [f'<style {SCENE_STYLE_ATTRIBUTE}="{module.scene_id}">', css, "</style>"]


def asset_markup(module: SceneModule) -> list[str]:
    lines: list[str] = []
    for asset in module.assets:
        if check_svg_asset(asset):
            raise ComposeError(f"Asset {asset.id} of scene {module.scene_id} is not a safe SVG")
        lines.append(f'<div data-asset="{asset.id}">{asset.svg.strip()}</div>')
    return lines


def scene_section(module: SceneModule) -> list[str]:
    return [
        f'<section class="mo-scene {module.root_class}" data-scene="{module.scene_id}">',
        *asset_markup(module),
        "</section>",
    ]


def scene_registration(module: SceneModule) -> list[str]:
    builder = escape_embedded(module.builder).strip("\n")
    return [
        "    {",
        f"      id: {json.dumps(module.scene_id)},",
        "      build(ctx) {",
        builder,
        "      },",
        "    },",
    ]


def compose(modules: Sequence[SceneModule], storyboard: Storyboard, tokens: StyleTokens) -> str:
    indexed = index_modules(modules, storyboard)
    ordered = [indexed[scene.id] for scene in storyboard.scenes]
    lines = [
        "<!doctype html>",
        f'<html lang="{escape(storyboard.language, quote=True)}">',
        "<head>",
        '<meta charset="utf-8">',
        f"<title>{escape(storyboard.title, quote=False)}</title>",
        f'<link rel="stylesheet" href="{BASE_STYLESHEET_URL}">',
        *tokens_style(tokens),
    ]
    for module in ordered:
        lines.extend(scene_style(module))
    lines.extend(
        [
            f'<script src="{GSAP_SCRIPT_URL}"></script>',
            f'<script src="{RUNTIME_SCRIPT_URL}"></script>',
            "</head>",
            "<body>",
            '<main class="mo-stage">',
        ]
    )
    for module in ordered:
        lines.extend(scene_section(module))
    lines.extend(
        [
            "</main>",
            "<script>",
            "Motionile.composition({",
            f"  aspects: {json.dumps(list(storyboard.aspects))},",
            "  scenes: [",
        ]
    )
    for module in ordered:
        lines.extend(scene_registration(module))
    lines.extend(["  ],", "});", "</script>", "</body>", "</html>", ""])
    return "\n".join(lines)
