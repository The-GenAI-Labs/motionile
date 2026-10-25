from typing import cast

import pytest
from fastapi import FastAPI
from tests.unit.modules.skills.support import ADMIN, CONTEXT, Harness, make_harness

from motionile.modules.skills import admin_skills_router
from motionile.modules.skills.schemas import SkillDetailView, SkillPage

FORBIDDEN_FIELD_WORDS = ("body", "content", "markdown", "text", "frontmatter", "canary", "tokens", "prompt")
MIN_LINE_LENGTH = 30


def property_names(node: object) -> set[str]:
    names: set[str] = set()
    if isinstance(node, dict):
        entries = cast("dict[str, object]", node)
        properties = entries.get("properties")
        if isinstance(properties, dict):
            names.update(cast("dict[str, object]", properties))
        for value in entries.values():
            names.update(property_names(value))
    elif isinstance(node, list):
        for item in cast("list[object]", node):
            names.update(property_names(item))
    return names


def test_no_admin_skill_schema_has_a_field_that_could_carry_the_text_of_a_skill() -> None:
    app = FastAPI()
    app.include_router(admin_skills_router, prefix="/v1")

    components = app.openapi()["components"]["schemas"]
    names = {name.lower() for name in property_names(components)}

    assert {"slug", "name", "description", "layer", "embeddingstatus", "tokencount"} <= names
    for name in names:
        assert not any(word in name for word in FORBIDDEN_FIELD_WORDS), name


def test_the_view_models_declare_exactly_the_documented_fields() -> None:
    page_fields = set(SkillPage.model_fields)
    detail_fields = set(SkillDetailView.model_fields)

    assert page_fields == {"items", "next_cursor"}
    assert detail_fields == {
        "slug",
        "name",
        "description",
        "layer",
        "version",
        "checksum",
        "token_count",
        "embedding_status",
        "updated_at",
        "versions",
    }


async def test_no_response_ever_contains_a_line_of_a_skill_body(monkeypatch: pytest.MonkeyPatch) -> None:
    harness: Harness = make_harness(monkeypatch)
    reseed = await harness.service.reseed(ADMIN, CONTEXT)
    listing = await harness.service.list_skills(None, None, 100)
    details = [await harness.service.get_skill(item.slug) for item in listing.items]

    payload = "\n".join(
        [
            reseed.model_dump_json(by_alias=True),
            SkillPage(items=listing.items, next_cursor=None).model_dump_json(by_alias=True),
            *(detail.model_dump_json(by_alias=True) for detail in details),
        ]
    )

    assert len(details) == len(harness.documents)
    for document in harness.documents:
        lines = [line.strip() for line in document.body.splitlines() if len(line.strip()) >= MIN_LINE_LENGTH]
        assert lines
        assert [line for line in lines if line in payload] == [], document.slug
        assert document.tokens == "" or document.tokens not in payload
