import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from tests.fakes.generation import FakeEditGuard, RecordingDispatch
from tests.integration.generation_support import (
    JOBS,
    GenerationApi,
    build_generation_service,
    install_generation_data,
    purge_generation_data,
)
from tests.integration.media_support import MediaApi
from tests.integration.test_auth import csrf
from tests.unit.modules.generation.support import storyboard_content

from motionile.core.ids import new_id
from motionile.modules.generation import ResumeKind
from motionile.modules.generation.dependencies import get_generation_service


@pytest.fixture
async def generation_api(media_api: MediaApi) -> AsyncIterator[GenerationApi]:
    voice_id = await install_generation_data(media_api)
    dispatch = RecordingDispatch()
    guard = FakeEditGuard()
    service = build_generation_service(media_api, dispatch, guard)
    media_api.app.dependency_overrides[get_generation_service] = lambda: service
    yield GenerationApi(media_api, service, dispatch, guard, voice_id)
    media_api.app.dependency_overrides.pop(get_generation_service)
    await purge_generation_data(media_api.database)


async def test_creating_a_job_reserves_credits_and_replaying_the_key_returns_the_same_job(
    generation_api: GenerationApi,
) -> None:
    await generation_api.fund(generation_api.primary_id, 500)

    first = await generation_api.create(key="replay-1")
    second = await generation_api.create(key="replay-1")

    assert first.status_code == 202, first.text
    body = first.json()
    assert body["status"] == "queued"
    assert (body["creditsEstimated"], body["creditsReserved"], body["creditsCharged"]) == (140, 140, None)
    assert body["options"]["style"] == "minimal-dark"
    assert body["options"]["voiceId"] == str(generation_api.voice_id)
    assert first.headers["location"] == f"/v1/jobs/{body['id']}"
    assert second.status_code == 202
    assert second.json() == body
    assert second.headers["idempotent-replayed"] == "true"
    assert await generation_api.job_count(generation_api.primary_id) == 1
    assert await generation_api.wallet(generation_api.primary_id) == (500, 140)
    assert generation_api.dispatch.runs == [UUID(body["id"])]


async def test_a_key_reused_with_a_different_request_is_rejected(generation_api: GenerationApi) -> None:
    await generation_api.fund(generation_api.primary_id, 500)
    await generation_api.create(key="reuse-1")

    changed = await generation_api.create(key="reuse-1", body=generation_api.body(durationSeconds=30))

    assert changed.status_code == 409
    assert changed.json()["code"] == "idempotency_key_reused"
    assert await generation_api.job_count(generation_api.primary_id) == 1


async def test_creating_a_job_needs_an_idempotency_key(generation_api: GenerationApi) -> None:
    response = await generation_api.primary.post(JOBS, json=generation_api.body(), headers=csrf(generation_api.primary))

    assert response.status_code == 400
    assert response.json()["code"] == "idempotency_key_required"


async def test_insufficient_credits_return_402_with_the_shortfall_and_create_nothing(
    generation_api: GenerationApi,
) -> None:
    await generation_api.fund(generation_api.primary_id, 100)

    response = await generation_api.create()

    assert response.status_code == 402
    body = response.json()
    assert body["code"] == "insufficient_credits"
    assert (body["available"], body["required"], body["shortfall"]) == (100, 140, 40)
    assert response.headers["content-type"].startswith("application/problem+json")
    assert await generation_api.job_count(generation_api.primary_id) == 0
    assert await generation_api.wallet(generation_api.primary_id) == (100, 0)


async def test_the_estimate_reports_the_price_and_whether_it_is_affordable(generation_api: GenerationApi) -> None:
    await generation_api.fund(generation_api.primary_id, 150)

    response = await generation_api.post(
        generation_api.primary, f"{JOBS}/estimate", {"options": {"durationSeconds": 60, "aspects": ["16:9", "9:16"]}}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["credits"], body["availableCredits"], body["affordable"]) == (196, 150, False)
    assert body["parameters"] == {
        "baseCredits": 20,
        "creditsPerSecond": 2,
        "extraAspectPercent": 40,
        "clonedVoicePremium": 10,
    }


async def test_concurrent_creation_cannot_exceed_the_active_job_limit(generation_api: GenerationApi) -> None:
    await generation_api.fund(generation_api.primary_id, 5_000)

    responses = await asyncio.gather(*(generation_api.create() for _ in range(6)))

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [202, 202, 409, 409, 409, 409]
    assert {response.json()["code"] for response in responses if response.status_code == 409} == {
        "too_many_active_jobs"
    }
    assert await generation_api.job_count(generation_api.primary_id) == 2
    assert await generation_api.wallet(generation_api.primary_id) == (5_000, 280)


async def test_concurrent_creation_cannot_overspend_credits(generation_api: GenerationApi) -> None:
    await generation_api.set_setting("jobs.max_active_per_user", 5)
    await generation_api.fund(generation_api.primary_id, 300)

    responses = await asyncio.gather(*(generation_api.create() for _ in range(4)))

    assert sorted(response.status_code for response in responses) == [202, 202, 402, 402]
    assert await generation_api.wallet(generation_api.primary_id) == (300, 280)
    assert await generation_api.job_count(generation_api.primary_id) == 2


async def test_a_catalog_topic_becomes_the_job_query(generation_api: GenerationApi) -> None:
    await generation_api.fund(generation_api.primary_id, 500)
    topic_id = await generation_api.seed_topic()

    response = await generation_api.create(body={"topicId": str(topic_id), "options": {"durationSeconds": 30}})

    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["source"], body["topicId"], body["query"]) == ("catalog", str(topic_id), "How DNS works")


async def test_unknown_and_inactive_topics_are_not_found(generation_api: GenerationApi) -> None:
    await generation_api.fund(generation_api.primary_id, 500)
    inactive = await generation_api.seed_topic(active=False)

    for topic_id in (new_id(), inactive):
        response = await generation_api.create(body={"topicId": str(topic_id), "options": {"durationSeconds": 30}})
        assert response.status_code == 404
        assert response.json()["code"] == "topic_not_found"


async def test_an_unknown_style_is_a_validation_problem(generation_api: GenerationApi) -> None:
    await generation_api.fund(generation_api.primary_id, 500)

    response = await generation_api.create(body=generation_api.body(style="no-such-style"))

    assert response.status_code == 422
    assert response.json()["code"] == "style_not_found"


async def test_invalid_bodies_are_validation_problems(generation_api: GenerationApi) -> None:
    for body in (
        {"options": {"durationSeconds": 30}},
        {"query": "x", "topicId": str(new_id()), "options": {"durationSeconds": 30}},
        {"query": "x", "options": {"durationSeconds": 5}},
        {"query": "x", "options": {"durationSeconds": 30}, "extra": True},
    ):
        response = await generation_api.create(body=body)
        assert response.status_code == 422
        assert response.json()["code"] == "validation_failed"


async def test_cancelling_a_queued_job_releases_its_credits(generation_api: GenerationApi) -> None:
    await generation_api.fund(generation_api.primary_id, 500)
    job_id = (await generation_api.create()).json()["id"]

    response = await generation_api.post(generation_api.primary, f"{JOBS}/{job_id}/cancel")
    again = await generation_api.post(generation_api.primary, f"{JOBS}/{job_id}/cancel")

    assert response.status_code == 202
    assert response.json()["status"] == "cancelled"
    assert again.json()["status"] == "cancelled"
    assert await generation_api.wallet(generation_api.primary_id) == (500, 0)
    reasons = await generation_api.scalar(
        "SELECT string_agg(reason, ',' ORDER BY created_at, id) FROM credit_ledger WHERE user_id = :u",
        u=generation_api.primary_id,
    )
    assert reasons == "purchase,reserve,release"


async def test_cancelling_a_running_job_only_flags_it(generation_api: GenerationApi) -> None:
    await generation_api.fund(generation_api.primary_id, 500)
    job_id = (await generation_api.create()).json()["id"]
    await generation_api.set_status(job_id, "generating")

    response = await generation_api.post(generation_api.primary, f"{JOBS}/{job_id}/cancel")

    assert response.json()["status"] == "generating"
    assert response.json()["cancelRequestedAt"] is not None
    assert await generation_api.wallet(generation_api.primary_id) == (500, 140)


async def test_completing_a_job_commits_only_the_formula_and_failing_releases_everything(
    generation_api: GenerationApi,
) -> None:
    await generation_api.fund(generation_api.primary_id, 1_000)
    done = UUID((await generation_api.create()).json()["id"])
    failed = UUID((await generation_api.create()).json()["id"])
    await generation_api.set_status(done, "rendering")
    await generation_api.set_status(failed, "generating")

    async with generation_api.database.transaction() as session:
        charged = await generation_api.service.complete_job(session, done, 30_000)
    async with generation_api.database.transaction() as session:
        assert await generation_api.service.fail_job(session, failed, "model_output_invalid", "bad output")

    assert charged == 80
    assert await generation_api.wallet(generation_api.primary_id) == (920, 0)
    assert await generation_api.job_status(done) == "completed"
    view = await generation_api.primary.get(f"{JOBS}/{failed}")
    assert view.json()["status"] == "failed"
    assert view.json()["errorCode"] == "model_output_invalid"
    assert view.json()["errorTitle"]


async def test_every_job_route_treats_another_users_job_as_not_found(generation_api: GenerationApi) -> None:
    job_id = await generation_api.seed_job(generation_api.primary_id, "awaiting_approval")
    await generation_api.seed_storyboard(job_id)
    other = generation_api.other
    revise_body = {"instructions": "shorter"}
    update_body = {"expectedVersion": 1, "content": storyboard_content()}

    responses = [
        await other.get(f"{JOBS}/{job_id}"),
        await other.get(f"{JOBS}/{job_id}/storyboard"),
        await other.put(f"{JOBS}/{job_id}/storyboard", json=update_body, headers=csrf(other)),
        await generation_api.post(other, f"{JOBS}/{job_id}/storyboard/regenerate", {"instructions": "x"}),
        await generation_api.post(other, f"{JOBS}/{job_id}/approve", {"expectedVersion": 1}),
        await generation_api.post(other, f"{JOBS}/{job_id}/cancel"),
        await generation_api.post(other, f"{JOBS}/{job_id}/revise", revise_body, key=True),
        await other.delete(f"{JOBS}/{job_id}", headers=csrf(other)),
    ]

    for response in responses:
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "job_not_found"
    assert await generation_api.job_status(job_id) == "awaiting_approval"
    assert generation_api.dispatch.resumes == []
    unknown = await other.get(f"{JOBS}/{new_id()}")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "job_not_found"


async def test_jobs_require_authentication(generation_api: GenerationApi) -> None:
    anonymous = generation_api.media.anonymous

    assert (await anonymous.get(JOBS)).status_code == 401
    assert (await anonymous.get(f"{JOBS}/{new_id()}")).status_code == 401


async def test_another_users_jobs_never_appear_in_the_list(generation_api: GenerationApi) -> None:
    await generation_api.seed_job(generation_api.other_id)

    page = (await generation_api.primary.get(JOBS)).json()

    assert page == {"items": [], "nextCursor": None}


async def test_the_list_filters_by_status_and_pages_with_cursors(generation_api: GenerationApi) -> None:
    oldest = await generation_api.seed_job(generation_api.primary_id, "completed")
    middle = await generation_api.seed_job(generation_api.primary_id, "failed")
    newest = await generation_api.seed_job(generation_api.primary_id, "completed")

    first = (await generation_api.primary.get(JOBS, params={"limit": 2})).json()
    second = (await generation_api.primary.get(JOBS, params={"limit": 2, "cursor": first["nextCursor"]})).json()
    failed = (await generation_api.primary.get(JOBS, params={"status": "failed"})).json()
    forged = await generation_api.primary.get(JOBS, params={"cursor": "forged.cursor"})

    assert [item["id"] for item in first["items"]] == [str(newest), str(middle)]
    assert first["nextCursor"] is not None
    assert [item["id"] for item in second["items"]] == [str(oldest)]
    assert second["nextCursor"] is None
    assert [item["id"] for item in failed["items"]] == [str(middle)]
    assert forged.status_code == 422
    assert forged.json()["code"] == "invalid_cursor"


async def test_the_storyboard_can_be_read_edited_and_approved(generation_api: GenerationApi) -> None:
    job_id = await generation_api.seed_job(generation_api.primary_id, "awaiting_approval")
    await generation_api.seed_storyboard(job_id)
    client = generation_api.primary
    path = f"{JOBS}/{job_id}/storyboard"

    shown = (await client.get(path)).json()
    edited = {**shown["content"], "title": "A better title"}
    saved = await client.put(path, json={"expectedVersion": 1, "content": edited}, headers=csrf(client))
    stale = await client.put(path, json={"expectedVersion": 1, "content": edited}, headers=csrf(client))
    approved = await generation_api.post(client, f"{JOBS}/{job_id}/approve", {"expectedVersion": 2})
    again = await generation_api.post(client, f"{JOBS}/{job_id}/approve", {"expectedVersion": 2})

    assert (shown["version"], shown["approved"], shown["issues"]) == (1, False, [])
    assert shown["limits"]["minWordsPerSecond"] == 2.0
    assert saved.status_code == 200, saved.text
    assert (saved.json()["version"], saved.json()["origin"]) == (2, "user")
    assert stale.status_code == 409
    assert stale.json()["code"] == "storyboard_version_conflict"
    assert stale.json()["currentVersion"] == 2
    assert approved.status_code == 202
    assert again.status_code == 409
    assert await generation_api.scalar(
        "SELECT approved_at IS NOT NULL FROM storyboards WHERE job_id = :id AND version = 2", id=job_id
    )
    assert [(item[0], item[1], item[2]) for item in generation_api.dispatch.resumes] == [
        (job_id, ResumeKind.APPROVE, None)
    ]


async def test_a_storyboard_with_blocking_issues_is_rejected_with_field_errors(generation_api: GenerationApi) -> None:
    job_id = await generation_api.seed_job(generation_api.primary_id, "awaiting_approval")
    await generation_api.seed_storyboard(job_id)
    content = storyboard_content()
    content["scenes"][0]["narration"] = " ".join(["word"] * 150)

    response = await generation_api.primary.put(
        f"{JOBS}/{job_id}/storyboard",
        json={"expectedVersion": 1, "content": content},
        headers=csrf(generation_api.primary),
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "storyboard_invalid"
    assert [(error["field"], error["type"]) for error in body["errors"]] == [("content.scenes.0", "speaking_rate_high")]


async def test_regeneration_returns_the_job_to_planning(generation_api: GenerationApi) -> None:
    job_id = await generation_api.seed_job(generation_api.primary_id, "awaiting_approval")
    await generation_api.seed_storyboard(job_id)

    response = await generation_api.post(
        generation_api.primary, f"{JOBS}/{job_id}/storyboard/regenerate", {"instructions": "Make it friendlier"}
    )

    assert response.status_code == 202
    assert response.json()["status"] == "planning"
    assert generation_api.dispatch.resumes[0][2] == "Make it friendlier"
    payload = await generation_api.scalar(
        "SELECT payload::text FROM job_events WHERE job_id = :id AND type = 'storyboard.regenerate_requested'",
        id=job_id,
    )
    assert "friendlier" not in payload


async def test_a_storyboard_outside_approval_cannot_be_edited(generation_api: GenerationApi) -> None:
    job_id = await generation_api.seed_job(generation_api.primary_id, "generating")
    await generation_api.seed_storyboard(job_id)

    response = await generation_api.primary.put(
        f"{JOBS}/{job_id}/storyboard",
        json={"expectedVersion": 1, "content": storyboard_content()},
        headers=csrf(generation_api.primary),
    )

    assert response.status_code == 409
    assert response.json()["code"] == "storyboard_not_editable"


async def test_a_revision_is_a_child_job_with_its_own_reservation(generation_api: GenerationApi) -> None:
    await generation_api.fund(generation_api.primary_id, 1_000)
    parent = await generation_api.seed_job(generation_api.primary_id, "completed")
    await generation_api.seed_storyboard(parent, approved=True)

    response = await generation_api.post(
        generation_api.primary,
        f"{JOBS}/{parent}/revise",
        {"instructions": "Make the second scene shorter", "sceneIds": ["scene-1"]},
        key=True,
    )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["parentJobId"] == str(parent)
    assert body["id"] != str(parent)
    assert body["options"]["revision"] == {"instructions": "Make the second scene shorter", "sceneIds": ["scene-1"]}
    assert body["creditsReserved"] == 140
    assert await generation_api.wallet(generation_api.primary_id) == (1_000, 140)
    assert await generation_api.job_status(parent) == "completed"
    reservation_refs = await generation_api.scalar(
        "SELECT count(*) FROM credit_reservations WHERE ref_type = 'job' AND ref_id = :id", id=UUID(body["id"])
    )
    assert reservation_refs == 1


async def test_only_a_completed_job_can_be_revised(generation_api: GenerationApi) -> None:
    await generation_api.fund(generation_api.primary_id, 500)
    running = await generation_api.seed_job(generation_api.primary_id, "rendering")

    response = await generation_api.post(
        generation_api.primary, f"{JOBS}/{running}/revise", {"instructions": "shorter"}, key=True
    )

    assert response.status_code == 409
    assert response.json()["code"] == "job_not_revisable"


async def test_deleting_a_job_removes_its_render_and_stored_files(generation_api: GenerationApi) -> None:
    media = generation_api.media
    render_id = await media.seed_render(generation_api.primary_id)
    job_id = await generation_api.seed_job(generation_api.primary_id, "completed", render_id=render_id)
    prefix = f"media/u/{generation_api.primary_id}/renders/{render_id}/"
    key = f"{prefix}16x9.mp4"
    assert await media.storage.exists(key)

    foreign = await generation_api.other.delete(f"{JOBS}/{job_id}", headers=csrf(generation_api.other))
    response = await generation_api.primary.delete(f"{JOBS}/{job_id}", headers=csrf(generation_api.primary))

    assert foreign.status_code == 404
    assert response.status_code == 204
    assert not await media.storage.exists(key)
    assert await generation_api.job_status(job_id) is None
    assert await generation_api.scalar("SELECT count(*) FROM renders WHERE id = :id", id=render_id) == 0
    assert await generation_api.scalar("SELECT count(*) FROM assets WHERE storage_key LIKE :p", p=f"{prefix}%") == 0
    assert (await generation_api.primary.get(f"{JOBS}/{job_id}")).status_code == 404


async def test_a_job_that_is_still_running_cannot_be_deleted(generation_api: GenerationApi) -> None:
    job_id = await generation_api.seed_job(generation_api.primary_id, "voicing")

    response = await generation_api.primary.delete(f"{JOBS}/{job_id}", headers=csrf(generation_api.primary))

    assert response.status_code == 409
    assert response.json()["code"] == "job_not_deletable"
    assert await generation_api.job_status(job_id) == "voicing"
