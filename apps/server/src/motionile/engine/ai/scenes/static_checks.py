from motionile.engine.ai.scenes.builder_checks import check_builder
from motionile.engine.ai.scenes.css_scope import check_css
from motionile.engine.ai.scenes.js_analysis import parse_builder
from motionile.engine.ai.scenes.models import (
    MAX_ASSET_CHARS,
    MAX_ASSETS,
    MAX_BUILDER_CHARS,
    MAX_CSS_CHARS,
    MAX_MODULE_CHARS,
    SceneModule,
    StaticFinding,
    StaticFindingCode,
)
from motionile.engine.ai.scenes.svg_assets import check_svg_asset


def too_large(message: str, detail: str) -> StaticFinding:
    return StaticFinding(code=StaticFindingCode.MODULE_TOO_LARGE, message=message, detail=detail)


def size_findings(module: SceneModule) -> list[StaticFinding]:
    findings: list[StaticFinding] = []
    if len(module.builder) > MAX_BUILDER_CHARS:
        findings.append(
            too_large(f"The builder has {len(module.builder)} characters; the limit is {MAX_BUILDER_CHARS}", "builder")
        )
    if len(module.css) > MAX_CSS_CHARS:
        findings.append(too_large(f"The CSS has {len(module.css)} characters; the limit is {MAX_CSS_CHARS}", "css"))
    if len(module.assets) > MAX_ASSETS:
        findings.append(too_large(f"The module has {len(module.assets)} assets; the limit is {MAX_ASSETS}", "assets"))
    findings.extend(
        too_large(f"Asset `{asset.id}` has {len(asset.svg)} characters; the limit is {MAX_ASSET_CHARS}", asset.id)
        for asset in module.assets
        if len(asset.svg) > MAX_ASSET_CHARS
    )
    total = len(module.builder) + len(module.css) + sum(len(asset.svg) for asset in module.assets)
    if total > MAX_MODULE_CHARS:
        findings.append(too_large(f"The module has {total} characters; the limit is {MAX_MODULE_CHARS}", "module"))
    return findings


def check_scene_module(module: SceneModule) -> list[StaticFinding]:
    findings = size_findings(module)
    findings.extend(check_builder(parse_builder(module.builder)))
    findings.extend(check_css(module.css, module.scene_id))
    for asset in module.assets:
        findings.extend(check_svg_asset(asset))
    return findings
