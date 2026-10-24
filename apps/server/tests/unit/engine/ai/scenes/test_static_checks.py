from motionile.engine.ai.scenes.models import (
    MAX_ASSET_CHARS,
    MAX_ASSETS,
    MAX_BUILDER_CHARS,
    MAX_CSS_CHARS,
    MAX_MODULE_CHARS,
    SceneAsset,
    SceneModule,
    StaticFindingCode,
)
from motionile.engine.ai.scenes.static_checks import check_scene_module


def oversized(builder: str = "return 1;", css: str = "", assets: list[SceneAsset] | None = None) -> SceneModule:
    return SceneModule.model_construct(
        version=1, scene_id="x", builder=builder, css=css, assets=assets if assets is not None else []
    )


def test_a_clean_module_has_no_findings() -> None:
    module = SceneModule(
        scene_id="x",
        builder="ctx.timeline.from(ctx.root, { opacity: 0 }, 0);",
        css=".mo-s-x { display: flex; }",
        assets=[SceneAsset(id="art", svg='<svg viewBox="0 0 1 1"/>')],
    )

    assert check_scene_module(module) == []


def test_findings_from_every_part_are_combined_in_a_stable_order() -> None:
    module = SceneModule(
        scene_id="x",
        builder="fetch('x');",
        css="body { color: red; }",
        assets=[SceneAsset(id="art", svg="<svg><script/></svg>")],
    )

    codes = [finding.code for finding in check_scene_module(module)]

    assert codes == [
        StaticFindingCode.BUILDER_FORBIDDEN_SYNTAX,
        StaticFindingCode.CSS_UNSCOPED,
        StaticFindingCode.ASSET_INVALID,
    ]
    assert codes == [finding.code for finding in check_scene_module(module)]


def test_oversized_parts_are_reported_when_the_model_is_bypassed() -> None:
    module = oversized(
        builder="a" * (MAX_BUILDER_CHARS + 1),
        css="b" * (MAX_CSS_CHARS + 1),
        assets=[
            SceneAsset.model_construct(id=f"a{index}", svg="c" * (MAX_ASSET_CHARS + 1))
            for index in range(MAX_ASSETS + 1)
        ],
    )

    details = {
        finding.detail for finding in check_scene_module(module) if finding.code is StaticFindingCode.MODULE_TOO_LARGE
    }

    assert {"builder", "css", "assets", "module", "a0"} <= details


def test_the_total_size_limit_is_checked_across_parts() -> None:
    module = oversized(
        builder="return 1;" + " " * (MAX_BUILDER_CHARS - 20),
        css=" " * MAX_CSS_CHARS,
        assets=[SceneAsset.model_construct(id=f"a{index}", svg=" " * MAX_ASSET_CHARS) for index in range(3)],
    )

    details = {
        finding.detail for finding in check_scene_module(module) if finding.code is StaticFindingCode.MODULE_TOO_LARGE
    }

    assert "module" in details
    assert MAX_MODULE_CHARS < MAX_BUILDER_CHARS + MAX_CSS_CHARS + 3 * MAX_ASSET_CHARS
