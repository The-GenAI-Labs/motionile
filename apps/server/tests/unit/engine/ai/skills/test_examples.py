import re

import pytest
import tinycss2
from tests.skill_support import compose_example
from tests.unit.engine.ai.skills.support import all_examples, documents_in, example_id
from tinycss2.ast import AtRule, QualifiedRule

from motionile.engine.ai.ports import SkillLayer
from motionile.engine.ai.scenes.js_analysis import parse_builder, walk
from motionile.engine.ai.scenes.models import SceneModule
from motionile.engine.ai.scenes.static_checks import check_scene_module
from motionile.engine.ai.skills.examples import (
    EXAMPLE_SCENE_ID,
    SkillExample,
    example_sections,
    extract_examples,
)
from motionile.engine.ai.skills.loader import SkillDocument, SkillLibraryError

EXAMPLES = all_examples()
EXAMPLE_IDS = [example_id(example) for example in EXAMPLES]
NARRATION_WORDS = range(8, 26)


def document_with(body: str) -> SkillDocument:
    return SkillDocument(
        slug="sample",
        name="Sample",
        description="A sample skill.",
        layer=SkillLayer.VISUAL,
        tokens="",
        body=body,
        checksum=bytes(32),
        token_count=1,
        frontmatter={},
        characters=len(body),
    )


def test_the_library_ships_twenty_examples_two_for_every_visual_skill() -> None:
    by_skill = {
        skill: [example for example in EXAMPLES if example.skill == skill] for skill in {e.skill for e in EXAMPLES}
    }

    assert len(EXAMPLES) == 20
    assert set(by_skill) == {document.slug for document in documents_in(SkillLayer.VISUAL)}
    assert {len(examples) for examples in by_skill.values()} == {2}
    assert len(set(EXAMPLE_IDS)) == len(EXAMPLE_IDS)


@pytest.mark.parametrize("example", EXAMPLES, ids=EXAMPLE_IDS)
def test_an_example_has_a_realistic_narration_line(example: SkillExample) -> None:
    assert len(example.narration.split()) in NARRATION_WORDS
    assert '"' not in example.narration


@pytest.mark.parametrize("example", EXAMPLES, ids=EXAMPLE_IDS)
def test_an_example_has_no_comments_in_its_code(example: SkillExample) -> None:
    parsed = parse_builder(example.builder)

    assert parsed.is_valid
    assert [node for node in walk(parsed.tree.root_node) if node.type == "comment"] == []
    assert "/*" not in example.css
    assert "*/" not in example.css
    assert "//" not in re.sub(r"https?://[^\s\"'`]+", "", example.builder)


@pytest.mark.parametrize("example", EXAMPLES, ids=EXAMPLE_IDS)
def test_an_example_becomes_a_valid_scene_module_for_the_demo_scene(example: SkillExample) -> None:
    module = example.scene_module()

    assert isinstance(module, SceneModule)
    assert module.scene_id == EXAMPLE_SCENE_ID == "demo"
    assert SceneModule.model_validate_json(module.model_dump_json(by_alias=True)) == module


@pytest.mark.parametrize("example", EXAMPLES, ids=EXAMPLE_IDS)
def test_an_example_passes_the_static_checks(example: SkillExample) -> None:
    assert check_scene_module(example.scene_module()) == []


def selectors_of(css: str) -> list[str]:
    selectors: list[str] = []
    pending = list(tinycss2.parse_stylesheet(css, skip_comments=True, skip_whitespace=True))
    while pending:
        rule = pending.pop(0)
        if isinstance(rule, QualifiedRule):
            selectors.extend(part.strip() for part in tinycss2.serialize(rule.prelude).split(","))
        elif isinstance(rule, AtRule) and rule.lower_at_keyword != "keyframes" and rule.content is not None:
            pending.extend(tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True))
    return selectors


@pytest.mark.parametrize("example", EXAMPLES, ids=EXAMPLE_IDS)
def test_every_css_selector_of_an_example_is_scoped_to_the_demo_scene(example: SkillExample) -> None:
    selectors = selectors_of(example.css)

    assert selectors
    assert all(re.match(r"\.mo-s-demo(?![a-z0-9-])", selector) for selector in selectors), selectors


@pytest.mark.parametrize("example", EXAMPLES, ids=EXAMPLE_IDS)
def test_an_example_composes_into_a_document_with_its_builder_and_assets(example: SkillExample) -> None:
    composed = compose_example(example)

    assert 'class="mo-scene mo-s-demo" data-scene="demo"' in composed.html
    assert composed.html.count("Motionile.composition(") == 1
    for asset in example.assets:
        assert f'<div data-asset="{asset.id}">' in composed.html
    assert compose_example(example).html == composed.html
    assert [scene.id for scene in composed.narration.scenes] == list(composed.scene_ids)


def test_only_visual_skills_carry_examples() -> None:
    for layer in (SkillLayer.STYLE, SkillLayer.DOMAIN):
        for document in documents_in(layer):
            assert extract_examples(document) == ()


def test_an_example_is_extracted_from_the_markdown_of_a_skill() -> None:
    body = "\n".join(
        [
            "# Sample",
            "",
            "## Examples",
            "",
            "#### Example: First",
            "",
            'Narration: "One two three."',
            "",
            "```js",
            "const a = 1;",
            "ctx.timeline.to(ctx.root, { opacity: 1 }, a);",
            "```",
            "",
            "```css",
            ".mo-s-demo { color: red; }",
            "```",
            "",
            "```svg id=badge",
            '<svg viewBox="0 0 1 1"><rect width="1" height="1"/></svg>',
            "```",
            "",
            "#### Example: Second",
            'Narration: "Four five."',
            "```js",
            "ctx.timeline.to(ctx.root, { opacity: 1 }, 0);",
            "```",
        ]
    )

    first, second = extract_examples(document_with(body))

    assert (first.title, first.narration) == ("First", "One two three.")
    assert first.builder == "const a = 1;\nctx.timeline.to(ctx.root, { opacity: 1 }, a);"
    assert first.css == ".mo-s-demo { color: red; }"
    assert [(asset.id, asset.svg.startswith("<svg")) for asset in first.assets] == [("badge", True)]
    assert (second.title, second.css, second.assets) == ("Second", "", ())


def test_code_blocks_outside_examples_are_not_extracted() -> None:
    body = "# Sample\n\n## Patterns\n\n```js\nconst a = 1;\n```\n\n#### Example: Only\n" + (
        'Narration: "Hi there."\n```js\nctx.timeline.to(ctx.root, { opacity: 1 }, 0);\n```\n\n## Next\n```js\nx;\n```\n'
    )

    (only,) = extract_examples(document_with(body))

    assert only.builder == "ctx.timeline.to(ctx.root, { opacity: 1 }, 0);"


def test_a_heading_inside_a_code_fence_does_not_end_an_example() -> None:
    body = (
        '#### Example: Fenced\nNarration: "Hi there."\n'
        '```js\nconst title = "# not a heading";\n#### Example: nope\n```\n'
    )

    sections = example_sections(body)

    assert [title for title, _ in sections] == ["Fenced"]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("#### Example: A\n```js\nx;\n```\n", "exactly one Narration line"),
        ('#### Example: A\nNarration: "a b"\nNarration: "c d"\n```js\nx;\n```\n', "exactly one Narration line"),
        ('#### Example: A\nNarration: "a b"\n```css\n.a{}\n```\n', "exactly one js block"),
        ('#### Example: A\nNarration: "a b"\n```js\nx;\n```\n```js\ny;\n```\n', "exactly one js block"),
        ('#### Example: A\nNarration: "a b"\n```js\nx;\n```\n```css\na{}\n```\n```css\nb{}\n```\n', "at most one css"),
        ('#### Example: A\nNarration: "a b"\n```js\nx;\n```\n```svg\n<svg/>\n```\n', "every svg block needs an id"),
        ('#### Example: A\nNarration: "a b"\n```js\nx;\n```\n```html\n<p/>\n```\n', "unsupported code blocks: html"),
        ('#### Example: A\nNarration: "a b"\n```js\nx;\n', "never closed"),
    ],
)
def test_a_malformed_example_is_rejected_with_a_clear_message(body: str, expected: str) -> None:
    with pytest.raises(SkillLibraryError, match=expected):
        extract_examples(document_with(body))
