import hashlib
from pathlib import Path

import pytest

from motionile.engine.ai.prompts import PROMPT_KEYS, PromptSourceError, load_prompt_sources
from motionile.engine.ai.prompts.loader import load_prompt_source, normalize_body, parse_prompt_source

SOURCE = "---\nkey: guard.input\nversion: 3\nvariables:\n  - canary\n---\nHello {{ canary }}\nSecond line\n"


def test_parse_extracts_key_version_variables_and_body() -> None:
    source = parse_prompt_source(SOURCE, origin="guard.input.md")

    assert source.key == "guard.input"
    assert source.version == 3
    assert source.variables == ("canary",)
    assert source.body == "Hello {{ canary }}\nSecond line\n"


def test_checksum_is_the_sha256_of_the_normalized_body() -> None:
    source = parse_prompt_source(SOURCE, origin="guard.input.md")

    assert source.checksum == hashlib.sha256(b"Hello {{ canary }}\nSecond line\n").digest()


def test_checksum_ignores_line_endings_and_trailing_whitespace() -> None:
    noisy = SOURCE.replace("\n", "\r\n").replace("Second line", "Second line   ") + "\r\n\r\n"

    assert parse_prompt_source(noisy, origin="a").checksum == parse_prompt_source(SOURCE, origin="a").checksum


def test_checksum_changes_with_the_body_but_not_with_the_version() -> None:
    base = parse_prompt_source(SOURCE, origin="a")
    edited = parse_prompt_source(SOURCE.replace("Second", "Third"), origin="a")
    bumped = parse_prompt_source(SOURCE.replace("version: 3", "version: 4"), origin="a")

    assert edited.checksum != base.checksum
    assert bumped.checksum == base.checksum


def test_normalize_body_is_idempotent() -> None:
    once = normalize_body("\n\nline  \r\nother\t\n\n\n")

    assert once == "line\nother\n"
    assert normalize_body(once) == once


@pytest.mark.parametrize(
    "text",
    [
        "no frontmatter at all",
        "---\nkey: guard.input\nversion: 1\nvariables: []\nextra: true\n---\nbody {{ canary }}\n",
        "---\nkey: Guard\nversion: 1\nvariables:\n  - canary\n---\nbody {{ canary }}\n",
        "---\nkey: guard.input\nversion: 0\nvariables:\n  - canary\n---\nbody {{ canary }}\n",
        "---\nkey: guard.input\nversion: 1\nvariables:\n  - canary\n  - canary\n---\nbody {{ canary }}\n",
        "---\nkey: guard.input\nversion: 1\nvariables: [canary\n---\nbody {{ canary }}\n",
    ],
)
def test_invalid_frontmatter_is_rejected(text: str) -> None:
    with pytest.raises(PromptSourceError):
        parse_prompt_source(text, origin="bad.md")


def test_undeclared_variable_in_the_body_is_rejected() -> None:
    text = SOURCE.replace("Hello {{ canary }}", "Hello {{ canary }} {{ topic }}")

    with pytest.raises(PromptSourceError, match="topic"):
        parse_prompt_source(text, origin="bad.md")


def test_declared_but_unused_variable_is_rejected() -> None:
    text = SOURCE.replace("  - canary\n", "  - canary\n  - topic\n")

    with pytest.raises(PromptSourceError, match="topic"):
        parse_prompt_source(text, origin="bad.md")


def test_a_prompt_without_the_canary_is_rejected() -> None:
    text = "---\nkey: guard.input\nversion: 1\nvariables: []\n---\nplain body\n"

    with pytest.raises(PromptSourceError, match="canary"):
        parse_prompt_source(text, origin="bad.md")


def test_a_broken_template_is_rejected() -> None:
    text = SOURCE.replace("{{ canary }}", "{% if %}{{ canary }}")

    with pytest.raises(PromptSourceError):
        parse_prompt_source(text, origin="bad.md")


def test_file_name_must_equal_the_key(tmp_path: Path) -> None:
    path = tmp_path / "other.name.md"
    path.write_text(SOURCE, encoding="utf-8")

    with pytest.raises(PromptSourceError, match="file name"):
        load_prompt_source(path)


def test_directory_loading_is_sorted_and_deterministic(tmp_path: Path) -> None:
    for key in ("b.second", "a.first"):
        (tmp_path / f"{key}.md").write_text(SOURCE.replace("guard.input", key), encoding="utf-8")

    first = load_prompt_sources(tmp_path)
    second = load_prompt_sources(tmp_path)

    assert [source.key for source in first] == ["a.first", "b.second"]
    assert first == second


def test_shipped_sources_are_exactly_the_documented_keys() -> None:
    sources = load_prompt_sources()

    assert [source.key for source in sources] == sorted(PROMPT_KEYS)
    assert load_prompt_sources() == sources
    assert len({source.checksum for source in sources}) == len(sources)
