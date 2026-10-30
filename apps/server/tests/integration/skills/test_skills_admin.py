import json

from httpx import AsyncClient
from tests.integration.skills.support import ADMIN, SkillsApi
from tests.integration.test_auth import csrf

from motionile.engine.ai.skills.loader import load_library

LIBRARY = load_library()
LIBRARY_SIZE = len(LIBRARY)
MIN_LINE_LENGTH = 30


async def reseed(client: AsyncClient) -> dict[str, int]:
    response = await client.post(f"{ADMIN}/reseed", headers=csrf(client))
    assert response.status_code == 202, response.text
    return dict(response.json())


async def test_the_admin_endpoints_need_the_skills_manage_permission(skills_api: SkillsApi) -> None:
    primary = skills_api.media.primary

    responses = [
        await primary.get(ADMIN),
        await primary.get(f"{ADMIN}/flow-diagram"),
        await primary.post(f"{ADMIN}/reseed", headers=csrf(primary)),
    ]

    assert [response.status_code for response in responses] == [403] * 3
    assert (await skills_api.media.anonymous.get(ADMIN)).status_code == 401
    assert await skills_api.scalar("SELECT count(*) FROM skills WHERE visibility = 'system'") == 0


async def test_reseed_creates_every_system_skill_once(skills_api: SkillsApi) -> None:
    first = await reseed(skills_api.curator)
    second = await reseed(skills_api.curator)

    assert first == {"created": LIBRARY_SIZE, "updated": 0, "unchanged": 0, "embedded": LIBRARY_SIZE}
    assert second == {"created": 0, "updated": 0, "unchanged": LIBRARY_SIZE, "embedded": 0}
    assert await skills_api.scalar("SELECT count(*) FROM skills WHERE visibility = 'system'") == LIBRARY_SIZE
    assert await skills_api.scalar("SELECT count(*) FROM skill_versions") == LIBRARY_SIZE
    assert await skills_api.scalar("SELECT count(*) FROM skill_embeddings") == LIBRARY_SIZE


async def test_the_list_reports_version_checksum_prefix_token_count_and_embedding_status(
    skills_api: SkillsApi,
) -> None:
    await reseed(skills_api.curator)

    response = await skills_api.curator.get(f"{ADMIN}?limit=100")

    assert response.status_code == 200, response.text
    items = {item["slug"]: item for item in response.json()["items"]}
    assert set(items) == {document.slug for document in LIBRARY}
    for document in LIBRARY:
        item = items[document.slug]
        assert item["name"] == document.name
        assert item["description"] == document.description
        assert item["layer"] == document.layer.value
        assert item["version"] == 1
        assert item["checksum"] == document.checksum.hex()[:12]
        assert item["tokenCount"] == document.token_count
        assert item["embeddingStatus"] == "ready"
        assert item["updatedAt"]
    assert response.json()["nextCursor"] is None


async def test_the_list_filters_by_layer_and_pages_with_cursors(skills_api: SkillsApi) -> None:
    await reseed(skills_api.curator)
    client = skills_api.curator

    styles = (await client.get(f"{ADMIN}?layer=style")).json()["items"]
    seen: list[str] = []
    url = f"{ADMIN}?limit=7"
    pages = 0
    while True:
        page = (await client.get(url)).json()
        seen.extend(item["slug"] for item in page["items"])
        pages += 1
        if page["nextCursor"] is None:
            break
        url = f"{ADMIN}?limit=7&cursor={page['nextCursor']}"

    assert {item["layer"] for item in styles} == {"style"}
    assert len(styles) == 5
    assert pages == 5
    assert len(seen) == len(set(seen)) == LIBRARY_SIZE
    assert (await client.get(f"{ADMIN}?limit=0")).status_code == 422
    assert (await client.get(f"{ADMIN}?layer=other")).status_code == 422
    assert (await client.get(f"{ADMIN}?cursor=garbage")).status_code == 422


async def test_embedding_status_is_stale_for_another_model_and_missing_without_a_row(skills_api: SkillsApi) -> None:
    await reseed(skills_api.curator)
    await skills_api.execute(
        "UPDATE skill_embeddings SET model = 'older-model' WHERE skill_version_id = "
        "(SELECT current_version_id FROM skills WHERE slug = 'backend')"
    )
    await skills_api.execute(
        "DELETE FROM skill_embeddings WHERE skill_version_id = "
        "(SELECT current_version_id FROM skills WHERE slug = 'physics')"
    )

    backend = (await skills_api.curator.get(f"{ADMIN}/backend")).json()
    physics = (await skills_api.curator.get(f"{ADMIN}/physics")).json()
    healthy = (await skills_api.curator.get(f"{ADMIN}/flow-diagram")).json()

    assert (backend["embeddingStatus"], physics["embeddingStatus"], healthy["embeddingStatus"]) == (
        "stale",
        "missing",
        "ready",
    )
    repaired = await reseed(skills_api.curator)
    assert repaired == {"created": 0, "updated": 0, "unchanged": LIBRARY_SIZE, "embedded": 2}
    assert (await skills_api.curator.get(f"{ADMIN}/backend")).json()["embeddingStatus"] == "ready"


async def test_a_changed_skill_gets_a_new_version_and_the_detail_lists_both(skills_api: SkillsApi) -> None:
    await reseed(skills_api.curator)
    await skills_api.execute(
        "UPDATE skill_versions SET checksum = decode(repeat('ab', 32), 'hex') WHERE id = "
        "(SELECT current_version_id FROM skills WHERE slug = 'flow-diagram')"
    )

    outcome = await reseed(skills_api.curator)
    detail = (await skills_api.curator.get(f"{ADMIN}/flow-diagram")).json()

    flow = next(document for document in LIBRARY if document.slug == "flow-diagram")
    assert outcome == {"created": 0, "updated": 1, "unchanged": LIBRARY_SIZE - 1, "embedded": 1}
    assert detail["version"] == 2
    assert detail["checksum"] == flow.checksum.hex()[:12]
    assert [(version["number"], version["checksum"]) for version in detail["versions"]] == [
        (2, flow.checksum.hex()[:12]),
        (1, "ab" * 6),
    ]
    assert all(version["createdAt"] for version in detail["versions"])
    assert await skills_api.scalar("SELECT count(*) FROM skill_versions") == LIBRARY_SIZE + 1
    assert await skills_api.scalar("SELECT count(*) FROM skill_embeddings") == LIBRARY_SIZE + 1


async def test_an_unknown_or_malformed_slug_is_rejected(skills_api: SkillsApi) -> None:
    await reseed(skills_api.curator)

    missing = await skills_api.curator.get(f"{ADMIN}/does-not-exist")
    malformed = await skills_api.curator.get(f"{ADMIN}/Not_A_Slug")

    assert (missing.status_code, missing.json()["code"]) == (404, "skill_not_found")
    assert malformed.status_code == 422


async def test_no_response_carries_the_text_of_a_skill(skills_api: SkillsApi) -> None:
    reseed_response = await skills_api.curator.post(f"{ADMIN}/reseed", headers=csrf(skills_api.curator))
    listing = await skills_api.curator.get(f"{ADMIN}?limit=100")
    details = [await skills_api.curator.get(f"{ADMIN}/{document.slug}") for document in LIBRARY]

    payload = "\n".join([reseed_response.text, listing.text, *(detail.text for detail in details)])

    for document in LIBRARY:
        lines = [line.strip() for line in document.body.splitlines() if len(line.strip()) >= MIN_LINE_LENGTH]
        assert [line for line in lines if line in payload] == [], document.slug
    assert {key for item in listing.json()["items"] for key in item} == {
        "slug",
        "name",
        "description",
        "layer",
        "version",
        "checksum",
        "tokenCount",
        "embeddingStatus",
        "updatedAt",
    }
    assert set(json.loads(details[0].text)) == {
        "slug",
        "name",
        "description",
        "layer",
        "version",
        "checksum",
        "tokenCount",
        "embeddingStatus",
        "updatedAt",
        "versions",
    }


async def test_reseed_is_audited_with_the_actor_and_the_counts(skills_api: SkillsApi) -> None:
    await reseed(skills_api.curator)
    await reseed(skills_api.curator)

    rows = await skills_api.rows(
        "SELECT actor_type, actor_user_id, target_type, metadata FROM audit_log WHERE action = 'skills.reseeded' "
        "ORDER BY created_at, id"
    )
    system_rows = await skills_api.rows(
        "SELECT action, actor_type, actor_user_id FROM audit_log WHERE action IN ('skills.created', "
        "'skills.version_added')"
    )

    assert [(row[0], row[1], row[2]) for row in rows] == [("admin", skills_api.curator_id, "skill")] * 2
    assert rows[0][3] == {"created": LIBRARY_SIZE, "updated": 0, "unchanged": 0, "embedded": LIBRARY_SIZE}
    assert rows[1][3] == {"created": 0, "updated": 0, "unchanged": LIBRARY_SIZE, "embedded": 0}
    assert len(system_rows) == LIBRARY_SIZE
    assert {(row[0], row[1], row[2]) for row in system_rows} == {("skills.created", "system", None)}
