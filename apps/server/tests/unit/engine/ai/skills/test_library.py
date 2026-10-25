import hashlib
import itertools
import re
import shutil
from pathlib import Path

import pytest
from tests.unit.engine.ai.skills.support import documents_in, library, skill_text

from motionile.engine.ai.job_options import SLUG_PATTERN
from motionile.engine.ai.ports import SkillLayer
from motionile.engine.ai.scenes.style_tokens import STYLE_TOKEN_SETS, parse_style_tokens
from motionile.engine.ai.skills.loader import (
    LIBRARY_ROOT,
    MAX_FILE_CHARACTERS,
    SHIPPED_SKILLS,
    SkillLibraryError,
    load_library,
    parse_skill_document,
    token_count_of,
)

MAX_DESCRIPTION_OVERLAP = 0.35
WORD = re.compile(r"[a-z0-9]+")


def words(text: str) -> set[str]:
    return set(WORD.findall(text.lower()))


def overlap(first: str, second: str) -> float:
    left, right = words(first), words(second)
    return len(left & right) / len(left | right)


def problems_of(text: str, layer: SkillLayer = SkillLayer.STYLE, folder: str = "minimal-dark") -> str:
    with pytest.raises(SkillLibraryError) as raised:
        parse_skill_document(text, folder_layer=layer, folder_name=folder)
    return str(raised.value)


def test_the_shipped_library_loads_with_exactly_the_documented_skills() -> None:
    documents = library()

    assert len(documents) == 30
    for layer, slugs in SHIPPED_SKILLS.items():
        assert {document.slug for document in documents_in(layer)} == set(slugs)
    assert [len(documents_in(layer)) for layer in SkillLayer] == [5, 10, 15]


def test_the_library_is_returned_in_layer_then_slug_order() -> None:
    documents = library()

    assert [document.layer for document in documents] == sorted(
        (document.layer for document in documents),
        key=list(SkillLayer).index,
    )
    for layer in SkillLayer:
        slugs = [document.slug for document in documents_in(layer)]
        assert slugs == sorted(slugs)


def test_every_skill_has_the_metadata_the_database_and_router_need() -> None:
    for document in library():
        assert re.fullmatch(SLUG_PATTERN, document.slug)
        assert len(document.slug) <= 64
        assert 1 <= len(document.name) <= 64
        assert 1 <= len(document.description) <= 1024
        assert len(document.checksum) == 32
        assert document.body.startswith("# ")
        assert document.body.endswith("\n")
        assert document.token_count == token_count_of(document.body) > 0
        assert document.frontmatter["name"] == document.slug
        assert document.frontmatter["description"] == document.description


def test_the_checksum_is_the_sha256_of_the_normalized_file() -> None:
    document = library()[0]
    text = skill_text(document.layer, document.slug)

    expected = hashlib.sha256(text.replace("\r\n", "\n").rstrip("\n").encode("utf-8") + b"\n").digest()

    assert document.checksum == expected


def test_the_checksum_ignores_line_endings_and_trailing_whitespace_but_not_content() -> None:
    text = skill_text(SkillLayer.STYLE, "whiteboard")
    original = parse_skill_document(text, folder_layer=SkillLayer.STYLE, folder_name="whiteboard")

    crlf = parse_skill_document(text.replace("\n", "  \r\n"), folder_layer=SkillLayer.STYLE, folder_name="whiteboard")
    edited = parse_skill_document(
        text.replace("## Do\n", "## Do\n\n- Keep it short.\n"), folder_layer=SkillLayer.STYLE, folder_name="whiteboard"
    )

    assert crlf.checksum == original.checksum
    assert crlf.body == original.body
    assert edited.checksum != original.checksum


def test_checksums_are_unique_across_the_library() -> None:
    checksums = [document.checksum for document in library()]

    assert len(set(checksums)) == len(checksums)


@pytest.mark.parametrize("layer", list(SkillLayer))
def test_files_stay_within_the_size_budget_of_their_layer(layer: SkillLayer) -> None:
    for document in documents_in(layer):
        assert document.characters <= MAX_FILE_CHARACTERS[layer], document.slug


def test_the_size_budgets_are_the_documented_ones() -> None:
    assert dict(MAX_FILE_CHARACTERS) == {SkillLayer.STYLE: 3_600, SkillLayer.VISUAL: 12_000, SkillLayer.DOMAIN: 7_200}


def test_only_style_skills_carry_tokens_and_they_equal_the_shipped_token_sets() -> None:
    for document in library():
        if document.layer is not SkillLayer.STYLE:
            assert document.tokens == ""
            continue
        parsed = parse_style_tokens(document.tokens, slug=document.slug)
        assert dict(parsed.properties) == dict(STYLE_TOKEN_SETS[document.slug].properties)
    assert {document.slug for document in documents_in(SkillLayer.STYLE)} == set(STYLE_TOKEN_SETS)
    minimal = next(document for document in library() if document.slug == "minimal-dark")
    assert minimal.tokens == ""


def test_descriptions_are_pairwise_distinct_and_lexically_apart() -> None:
    documents = library()
    descriptions = [document.description for document in documents]

    assert len(set(descriptions)) == len(descriptions)
    for first, second in itertools.combinations(documents, 2):
        assert overlap(first.description, second.description) < MAX_DESCRIPTION_OVERLAP, (first.slug, second.slug)


def test_the_loader_rejects_a_missing_frontmatter_block() -> None:
    assert "frontmatter block" in problems_of("# Minimal dark\n")


def test_the_loader_rejects_invalid_yaml() -> None:
    assert "not valid YAML" in problems_of("---\nname: [unclosed\n---\n# Title\n")


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("name: minimal-dark", "name: Minimal_Dark", "frontmatter name"),
        ("name: minimal-dark", "name: whiteboard", "must equal the folder name minimal-dark"),
        ("layer: style", "layer: visual", "must equal style"),
        ("layer: style", "layer: nonsense", "frontmatter metadata.layer"),
        ("metadata:\n", "extra: 1\nmetadata:\n", "frontmatter extra"),
    ],
)
def test_the_loader_rejects_bad_names_layers_and_unknown_keys(old: str, new: str, expected: str) -> None:
    text = skill_text(SkillLayer.STYLE, "minimal-dark").replace(old, new, 1)

    assert expected in problems_of(text)


def test_the_loader_rejects_a_missing_empty_or_oversized_description() -> None:
    text = skill_text(SkillLayer.STYLE, "minimal-dark")
    description = next(line for line in text.splitlines() if line.startswith("description:"))

    assert "frontmatter description" in problems_of(text.replace(description, "description: ''", 1))
    assert "frontmatter description" in problems_of(text.replace(description, "description: " + "x" * 1025, 1))
    assert "frontmatter description" in problems_of(text.replace(description + "\n", "", 1))


def test_the_loader_accepts_a_description_of_exactly_1024_characters() -> None:
    text = skill_text(SkillLayer.STYLE, "minimal-dark")
    description = next(line for line in text.splitlines() if line.startswith("description:"))

    document = parse_skill_document(
        text.replace(description, "description: " + "x" * 1024, 1),
        folder_layer=SkillLayer.STYLE,
        folder_name="minimal-dark",
    )

    assert len(document.description) == 1024


def test_the_loader_rejects_style_token_problems() -> None:
    text = skill_text(SkillLayer.STYLE, "whiteboard")
    tokens = next(line for line in text.splitlines() if line.strip().startswith("tokens:"))

    assert "needs metadata.tokens" in problems_of(text.replace(tokens + "\n", "", 1), folder="whiteboard")
    assert "--mo-bogus is not a style token" in problems_of(
        text.replace(tokens, '  tokens: "--mo-bogus: #ffffff"', 1), folder="whiteboard"
    )
    assert "contrast" in problems_of(
        text.replace(tokens, '  tokens: "--mo-bg: #ffffff; --mo-text: #eeeeee"', 1), folder="whiteboard"
    )
    assert "differ from the style token set shipped" in problems_of(
        text.replace("--mo-accent: #1d4ed8", "--mo-accent: #112233", 1), folder="whiteboard"
    )


def test_the_loader_rejects_tokens_on_a_skill_that_is_not_a_style() -> None:
    text = skill_text(SkillLayer.VISUAL, "flow-diagram").replace(
        "layer: visual", 'layer: visual\n  tokens: "--mo-bg: #000000"', 1
    )

    assert "only style skills carry metadata.tokens" in problems_of(text, SkillLayer.VISUAL, "flow-diagram")


def test_the_loader_rejects_an_oversized_file_and_a_missing_title() -> None:
    text = skill_text(SkillLayer.STYLE, "minimal-dark")

    assert "exceed the style limit of 3600" in problems_of(text + "filler\n" * 400)
    assert "level-1 title" in problems_of(text.replace("# Minimal dark", "Minimal dark", 1))


def copy_library(destination: Path) -> Path:
    root = destination / "library"
    shutil.copytree(LIBRARY_ROOT, root, ignore=shutil.ignore_patterns("__pycache__"))
    return root


def test_a_copy_of_the_library_loads_to_identical_documents(tmp_path: Path) -> None:
    root = copy_library(tmp_path)

    assert load_library(root) == library()


def test_loading_the_default_library_twice_gives_equal_results() -> None:
    assert load_library() == load_library()


def test_a_missing_shipped_skill_is_reported(tmp_path: Path) -> None:
    root = copy_library(tmp_path)
    shutil.rmtree(root / "domain" / "physics")

    with pytest.raises(SkillLibraryError) as raised:
        load_library(root)

    assert raised.value.problems == ("domain/physics: the shipped skill is missing",)


def test_an_unexpected_skill_is_reported(tmp_path: Path) -> None:
    root = copy_library(tmp_path)
    shutil.copytree(root / "domain" / "physics", root / "domain" / "astronomy")
    text = (root / "domain" / "astronomy" / "SKILL.md").read_text(encoding="utf-8")
    (root / "domain" / "astronomy" / "SKILL.md").write_text(text.replace("name: physics", "name: astronomy", 1))

    with pytest.raises(SkillLibraryError) as raised:
        load_library(root)

    assert "domain/astronomy: the skill is not in the shipped list" in raised.value.problems


def test_extra_files_and_unknown_layers_are_reported(tmp_path: Path) -> None:
    root = copy_library(tmp_path)
    (root / "domain" / "physics" / "notes.txt").write_text("x", encoding="utf-8")
    (root / "misc").mkdir()

    with pytest.raises(SkillLibraryError) as raised:
        load_library(root)

    assert "domain/physics: the folder must hold only SKILL.md" in raised.value.problems
    assert "misc: only the style, visual and domain folders may sit in the library" in raised.value.problems


def test_a_slug_in_two_layers_is_reported(tmp_path: Path) -> None:
    root = copy_library(tmp_path)
    shutil.copytree(root / "domain" / "concepts", root / "visual" / "concepts")
    text = (root / "visual" / "concepts" / "SKILL.md").read_text(encoding="utf-8")
    (root / "visual" / "concepts" / "SKILL.md").write_text(text.replace("layer: domain", "layer: visual", 1))

    with pytest.raises(SkillLibraryError) as raised:
        load_library(root)

    assert "concepts: the slug exists in more than one layer" in raised.value.problems
