import json
from dataclasses import dataclass
from uuid import UUID

import httpx
import pytest
from tests.fakes.settings import SHARE_INTERNAL_SECRET
from tests.integration.pipeline.support import PipelineEnv, SseFrame, parse_sse
from tests.integration.test_auth import csrf

pytestmark = pytest.mark.slow

FUNDS = 1_000
ADMIN_JOBS = "/v1/admin/jobs"
ANALYTICS = "/v1/admin/analytics/jobs"
LIBRARY = "/v1/library"


@dataclass
class Finished:
    env: PipelineEnv
    job_id: UUID

    @property
    def owner(self) -> httpx.AsyncClient:
        return self.env.generation.primary

    @property
    def outsider(self) -> httpx.AsyncClient:
        return self.env.generation.other

    @property
    def anonymous(self) -> httpx.AsyncClient:
        return self.env.generation.media.anonymous

    async def share(self, client: httpx.AsyncClient | None = None, **body: object) -> httpx.Response:
        return await (client or self.owner).post(
            f"/v1/jobs/{self.job_id}/share",
            json={"aspect": "16:9", **body},
            headers=csrf(client or self.owner),
        )

    async def unshare(self, client: httpx.AsyncClient | None = None) -> httpx.Response:
        return await (client or self.owner).delete(f"/v1/jobs/{self.job_id}/share", headers=csrf(client or self.owner))


@pytest.fixture
async def finished(pipeline_env: PipelineEnv) -> Finished:
    await pipeline_env.fund(FUNDS)
    job_id = await pipeline_env.run_to_end()
    assert (await pipeline_env.job(job_id))["status"] == "completed"
    return Finished(pipeline_env, job_id)


def frames_of(response: httpx.Response) -> list[SseFrame]:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    return parse_sse(response.text)


def types_of(frames: list[SseFrame]) -> list[str]:
    return [json.loads(frame.data)["type"] for frame in frames if frame.event == "job_event"]


async def test_the_event_stream_starts_with_a_snapshot_and_replays_every_stored_event(finished: Finished) -> None:
    response = await finished.owner.get(f"/v1/jobs/{finished.job_id}/events")

    frames = frames_of(response)
    assert frames[0].event == "snapshot"
    assert json.loads(frames[0].data)["status"] == "completed"
    identifiers = [frame.identifier for frame in frames[1:]]
    assert None not in identifiers
    assert identifiers == sorted(identifiers, key=lambda value: UUID(str(value)).int)
    stored = await finished.env.event_types(finished.job_id)
    assert types_of(frames) == stored
    assert stored[-1] == "job.completed"


async def test_the_stream_resumes_after_the_last_event_id(finished: Finished) -> None:
    everything = frames_of(await finished.owner.get(f"/v1/jobs/{finished.job_id}/events"))
    seen = everything[3]

    resumed = frames_of(
        await finished.owner.get(f"/v1/jobs/{finished.job_id}/events", headers={"Last-Event-ID": str(seen.identifier)})
    )

    assert resumed[0].event == "snapshot"
    assert [frame.identifier for frame in resumed[1:]] == [frame.identifier for frame in everything[4:]]


async def test_a_malformed_last_event_id_is_ignored(finished: Finished) -> None:
    everything = frames_of(await finished.owner.get(f"/v1/jobs/{finished.job_id}/events"))

    ignored = frames_of(
        await finished.owner.get(f"/v1/jobs/{finished.job_id}/events", headers={"Last-Event-ID": "not-a-uuid"})
    )

    assert [frame.identifier for frame in ignored] == [frame.identifier for frame in everything]


async def test_other_people_cannot_follow_or_see_the_job(finished: Finished) -> None:
    url = f"/v1/jobs/{finished.job_id}/events"

    stranger = await finished.outsider.get(url)
    signed_out = await finished.anonymous.get(url)

    assert stranger.status_code == 404
    assert stranger.json()["code"] == "job_not_found"
    assert signed_out.status_code == 401
    assert (await finished.outsider.get(f"/v1/jobs/{finished.job_id}")).status_code == 404


async def test_the_library_lists_the_finished_video_for_its_owner_only(finished: Finished) -> None:
    mine = await finished.owner.get(LIBRARY)
    theirs = await finished.outsider.get(LIBRARY)
    signed_out = await finished.anonymous.get(LIBRARY)

    assert mine.status_code == 200, mine.text
    (item,) = mine.json()["items"]
    assert item["jobId"] == str(finished.job_id)
    assert item["title"]
    assert item["aspects"] == ["16:9"]
    assert item["durationMs"] > 0
    assert item["thumbnailUrl"] is not None
    assert item["fallbackSceneIds"] == []
    assert [rendition["status"] for rendition in item["renditions"]] == ["ready"]
    assert theirs.json()["items"] == []
    assert signed_out.status_code == 401


async def test_the_library_searches_and_filters(finished: Finished) -> None:
    by_query = await finished.owner.get(LIBRARY, params={"q": "tcp"})
    nothing = await finished.owner.get(LIBRARY, params={"q": "zzz-no-such-video"})
    landscape = await finished.owner.get(LIBRARY, params={"aspect": "16:9"})
    portrait = await finished.owner.get(LIBRARY, params={"aspect": "9:16"})
    paged = await finished.owner.get(LIBRARY, params={"limit": 1})

    assert len(by_query.json()["items"]) == 1
    assert nothing.json()["items"] == []
    assert len(landscape.json()["items"]) == 1
    assert portrait.json()["items"] == []
    assert paged.json()["nextCursor"] is None


async def test_a_shared_video_opens_signed_out_without_revealing_the_owner(finished: Finished) -> None:
    created = await finished.share(allowIndexing=True)
    assert created.status_code == 201, created.text
    slug = created.json()["slug"]
    assert len(slug) == 22
    assert created.json()["url"].endswith(f"/v/{slug}")

    page = await finished.anonymous.get(f"/v1/share/{slug}")

    assert page.status_code == 200, page.text
    body = page.json()
    assert body["title"]
    assert body["aspect"] == "16:9"
    assert body["allowIndexing"] is True
    assert body["playbackUrl"]
    assert page.headers["cache-control"] == "no-store"
    assert str(finished.env.generation.primary_id) not in page.text
    assert str(finished.job_id) not in page.text
    async with httpx.AsyncClient(timeout=30) as raw:
        video = await raw.get(body["playbackUrl"], headers={"Range": "bytes=0-1023"})
    assert video.status_code in (200, 206)


async def test_a_view_is_counted_once_per_visitor_and_hour(finished: Finished) -> None:
    slug = (await finished.share()).json()["slug"]

    for _ in range(3):
        assert (await finished.anonymous.get(f"/v1/share/{slug}")).status_code == 200

    assert await view_count(finished, slug) == 1


async def view_count(finished: Finished, slug: str) -> object:
    return await finished.env.generation.scalar("SELECT view_count FROM share_links WHERE slug = :slug", slug=slug)


async def test_a_page_read_with_the_internal_secret_counts_no_view(finished: Finished) -> None:
    slug = (await finished.share()).json()["slug"]
    internal = {"X-Motionile-Internal": SHARE_INTERNAL_SECRET}

    for _ in range(3):
        assert (await finished.anonymous.get(f"/v1/share/{slug}", headers=internal)).status_code == 200

    assert await view_count(finished, slug) == 0


async def test_a_wrong_internal_secret_is_treated_as_a_public_read(finished: Finished) -> None:
    slug = (await finished.share()).json()["slug"]

    for _ in range(2):
        response = await finished.anonymous.get(f"/v1/share/{slug}", headers={"X-Motionile-Internal": "x" * 40})
        assert response.status_code == 200

    assert await view_count(finished, slug) == 1


async def test_the_browser_post_counts_one_view_per_visitor_and_hour(finished: Finished) -> None:
    slug = (await finished.share()).json()["slug"]
    internal = {"X-Motionile-Internal": SHARE_INTERNAL_SECRET}

    assert (await finished.anonymous.get(f"/v1/share/{slug}", headers=internal)).status_code == 200
    for _ in range(3):
        counted = await finished.anonymous.post(f"/v1/share/{slug}/views")
        assert counted.status_code == 204
        assert counted.content == b""

    assert await view_count(finished, slug) == 1


async def test_counting_a_view_of_a_dead_link_answers_like_reading_it(finished: Finished) -> None:
    revoked = (await finished.share()).json()["slug"]
    await finished.unshare()

    reads = [await finished.anonymous.get(f"/v1/share/{slug}") for slug in (revoked, "x" * 22, "short")]
    counts = [await finished.anonymous.post(f"/v1/share/{slug}/views") for slug in (revoked, "x" * 22, "short")]

    assert {response.status_code for response in [*reads, *counts]} == {404}
    assert (
        len(
            {
                (response.json()["code"], response.json()["title"], response.json()["detail"])
                for response in [*reads, *counts]
            }
        )
        == 1
    )
    assert await view_count(finished, revoked) == 0


async def test_a_new_link_replaces_the_old_one_and_revoking_ends_the_new_one(finished: Finished) -> None:
    first = (await finished.share()).json()["slug"]
    second = (await finished.share()).json()["slug"]

    assert (await finished.anonymous.get(f"/v1/share/{first}")).status_code == 404
    assert (await finished.anonymous.get(f"/v1/share/{second}")).status_code == 200
    assert (await finished.unshare()).status_code == 204
    assert (await finished.anonymous.get(f"/v1/share/{second}")).status_code == 404


async def test_every_dead_link_answers_the_same_way(finished: Finished) -> None:
    revoked = (await finished.share()).json()["slug"]
    await finished.unshare()

    answers = [await finished.anonymous.get(f"/v1/share/{slug}") for slug in (revoked, "x" * 22, "short", "A1_-" * 5)]

    assert {response.status_code for response in answers} == {404}
    assert {response.json()["code"] for response in answers} == {"share_not_found"}
    assert len({(response.json()["title"], response.json()["detail"]) for response in answers}) == 1


async def test_only_the_owner_can_manage_links(finished: Finished) -> None:
    created = await finished.share(finished.outsider)
    removed = await finished.unshare(finished.outsider)
    signed_out = await finished.share(finished.anonymous)

    assert (created.status_code, created.json()["code"]) == (404, "job_not_found")
    assert removed.status_code == 404
    assert signed_out.status_code == 401


async def test_a_video_that_is_not_finished_cannot_be_shared(pipeline_env: PipelineEnv) -> None:
    await pipeline_env.fund(FUNDS)
    job_id = await pipeline_env.start()

    response = await pipeline_env.generation.primary.post(
        f"/v1/jobs/{job_id}/share", json={"aspect": "16:9"}, headers=csrf(pipeline_env.generation.primary)
    )

    assert response.status_code == 409
    assert response.json()["code"] == "job_not_shareable"


async def test_the_admin_routes_need_the_jobs_permission(finished: Finished) -> None:
    detail = f"{ADMIN_JOBS}/{finished.job_id}"
    paths = [ADMIN_JOBS, detail, ANALYTICS]

    for path in paths:
        assert (await finished.anonymous.get(path)).status_code == 401
        assert (await finished.owner.get(path)).status_code == 403
        assert (await finished.outsider.get(path)).status_code == 403

    await finished.env.generation.media.grant_permissions(finished.env.generation.primary_id, "jobs", "jobs.read_all")

    assert (await finished.owner.get(ADMIN_JOBS)).status_code == 200
    assert (await finished.owner.get(detail)).status_code == 200
    assert (await finished.owner.get(ANALYTICS)).status_code == 200
    assert (await finished.outsider.get(ADMIN_JOBS)).status_code == 403


async def test_the_admin_detail_shows_the_internals_without_prompt_material(finished: Finished) -> None:
    await finished.env.generation.media.grant_permissions(finished.env.generation.primary_id, "jobs", "jobs.read_all")

    response = await finished.owner.get(f"{ADMIN_JOBS}/{finished.job_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job"]["id"] == str(finished.job_id)
    assert body["events"][0]["type"] == "job.created"
    assert body["storyboardVersions"][-1]["approved"] is True
    assert body["approvedStoryboard"]["scenes"]
    assert [scene["sceneId"] for scene in body["scenes"]] == [
        scene["id"] for scene in body["approvedStoryboard"]["scenes"]
    ]
    assert body["reports"]["validation"]["valid"] is True
    assert body["cost"]["inputTokens"] > 0
    assert body["cost"]["usageRecords"] > 0
    assert body["cost"]["creditsCharged"] == body["job"]["creditsCharged"]
    assert body["traceUrl"] is None
    lowered = response.text.lower()
    for forbidden in ("canary", "system_prompt", "mo-canary"):
        assert forbidden not in lowered


async def test_the_admin_list_filters_by_status_and_user(finished: Finished) -> None:
    await finished.env.generation.media.grant_permissions(finished.env.generation.primary_id, "jobs", "jobs.read_all")
    owner_id = finished.env.generation.primary_id

    completed = await finished.owner.get(ADMIN_JOBS, params={"status": "completed", "userId": str(owner_id)})
    failed = await finished.owner.get(ADMIN_JOBS, params={"status": "failed"})
    other_user = await finished.owner.get(ADMIN_JOBS, params={"userId": str(finished.env.generation.other_id)})

    assert [item["id"] for item in completed.json()["items"]] == [str(finished.job_id)]
    assert failed.json()["items"] == []
    assert other_user.json()["items"] == []


async def test_the_analytics_fill_every_day_and_count_the_finished_job(finished: Finished) -> None:
    await finished.env.generation.media.grant_permissions(finished.env.generation.primary_id, "jobs", "jobs.read_all")

    response = await finished.owner.get(ANALYTICS)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["days"]) == 30
    assert sum(day["completed"] for day in body["days"]) == 1
    assert body["successRate"] == 1.0
    assert body["scenes"] >= 3
    assert body["fallbackRate"] == 0.0
    assert {stage["stage"] for stage in body["stages"]} >= {"plan", "scenes", "render"}
    assert body["averageCreditsCharged"] > 0


async def test_the_analytics_refuse_a_range_over_a_year(finished: Finished) -> None:
    await finished.env.generation.media.grant_permissions(finished.env.generation.primary_id, "jobs", "jobs.read_all")

    response = await finished.owner.get(ANALYTICS, params={"dateFrom": "2025-01-01", "dateTo": "2026-10-25"})

    assert response.status_code == 422
    assert response.json()["code"] == "analytics_range_invalid"
