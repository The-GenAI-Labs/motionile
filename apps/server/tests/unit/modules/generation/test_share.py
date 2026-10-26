from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.generation import EPOCH, GenerationWorld

from motionile.core.clock import FrozenClock
from motionile.core.ids import new_id
from motionile.modules.generation.exceptions import (
    JobNotFoundError,
    JobNotShareableError,
    ShareNotFoundError,
    ShareRenditionNotFoundError,
)
from motionile.modules.generation.models import Job, ShareLink
from motionile.modules.generation.share_schemas import ShareCreateRequest
from motionile.modules.generation.share_service import ShareService, pick_rendition
from motionile.modules.generation.slugs import SLUG_PATTERN, UNKNOWN_SLUG, is_valid_slug, lookup_slug, new_slug
from motionile.modules.media import Aspect, RenditionStatus, RenditionView, SignedRendition

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
TTL = timedelta(minutes=15)
ORIGIN = "https://motionile.example"


def rendition(aspect: Aspect = Aspect.LANDSCAPE, status: RenditionStatus = RenditionStatus.READY) -> RenditionView:
    return RenditionView(
        id=new_id(),
        aspect=aspect,
        width=1920,
        height=1080,
        duration_ms=61_000,
        status=status,
        burned_in_subtitles=False,
        url="https://cdn.example/owner-cookie-url.mp4",
    )


class FakeMedia:
    def __init__(self, renditions: list[RenditionView]) -> None:
        self.renditions = renditions
        self.signed_for: list[tuple[UUID, UUID, UUID]] = []

    async def renditions_for(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> list[RenditionView]:
        del session, user_id, render_id
        return self.renditions

    async def signed_rendition(
        self, session: AsyncSession, owner_user_id: UUID, render_id: UUID, rendition_id: UUID, ttl: timedelta
    ) -> SignedRendition | None:
        del session
        self.signed_for.append((owner_user_id, render_id, rendition_id))
        match = next((item for item in self.renditions if item.id == rendition_id), None)
        if match is None or match.status is not RenditionStatus.READY:
            return None
        return SignedRendition(
            rendition_id=match.id,
            aspect=match.aspect,
            width=match.width,
            height=match.height,
            duration_ms=match.duration_ms,
            url=f"https://cdn.example/signed/{match.id}?sig=1",
            poster_url=f"https://cdn.example/signed/poster-{match.id}?sig=1",
            expires_in=ttl,
        )


@dataclass
class FakeShareStore:
    world: GenerationWorld
    links: list[ShareLink] = field(default_factory=list[ShareLink])
    taken: set[str] = field(default_factory=set[str])
    content: dict[str, Any] | None = None
    lookups: list[str] = field(default_factory=list[str])

    async def owned_job(self, user_id: UUID, job_id: UUID) -> Job | None:
        job = self.world.jobs.get(job_id)
        return job if job is not None and job.user_id == user_id else None

    async def revoke(self, job_id: UUID, rendition_id: UUID | None, at: datetime) -> int:
        revoked = 0
        for link in self.links:
            same = link.job_id == job_id and (rendition_id is None or link.rendition_id == rendition_id)
            if same and link.revoked_at is None:
                link.revoked_at = at
                revoked += 1
        return revoked

    async def insert(self, job_id: UUID, rendition_id: UUID, slug: str, *, allow_indexing: bool) -> ShareLink | None:
        if slug in self.taken or any(link.slug == slug for link in self.links):
            return None
        link = ShareLink(
            id=new_id(),
            job_id=job_id,
            slug=slug,
            rendition_id=rendition_id,
            is_public=allow_indexing,
            expires_at=None,
            view_count=0,
            revoked_at=None,
            created_at=EPOCH,
            updated_at=EPOCH,
        )
        self.links.append(link)
        return link

    async def find(self, slug: str) -> tuple[ShareLink, Job] | None:
        self.lookups.append(slug)
        link = next((item for item in self.links if item.slug == slug), None)
        return (link, self.world.jobs[link.job_id]) if link is not None else None

    async def record_view(self, link_id: UUID) -> None:
        next(link for link in self.links if link.id == link_id).view_count += 1

    async def approved_content(self, job_id: UUID) -> dict[str, Any] | None:
        del job_id
        return self.content


class FakeViews:
    def __init__(self) -> None:
        self.seen: set[tuple[str, str]] = set()

    async def first_view(self, slug: str, viewer: str) -> bool:
        key = (slug, viewer)
        fresh = key not in self.seen
        self.seen.add(key)
        return fresh


class Fixture:
    def __init__(self, slugs: list[str] | None = None) -> None:
        self.session = AsyncSession()
        self.world = GenerationWorld()
        self.store = FakeShareStore(self.world)
        self.clock = FrozenClock(NOW)
        self.owner = new_id()
        self.renditions = [rendition(Aspect.LANDSCAPE), rendition(Aspect.PORTRAIT)]
        self.media = FakeMedia(self.renditions)
        self.views = FakeViews()
        queue = list(slugs or [])
        self.job = self.world.add_job(self.owner, status="completed", render_id=new_id(), query="How does TCP work?")
        self.service = ShareService(
            self.media,
            self.clock,
            self.views,
            web_origin=ORIGIN + "/",
            playback_ttl=TTL,
            store_factory=lambda _session: self.store,
            slug_factory=(lambda: queue.pop(0)) if queue else new_slug,
        )

    def request(self, **values: Any) -> ShareCreateRequest:
        return ShareCreateRequest.model_validate({"aspect": "16:9", **values})


@pytest.fixture
async def fixture() -> Fixture:
    return Fixture()


def test_slugs_are_twenty_two_url_safe_characters_that_fit_the_table_check() -> None:
    slugs = {new_slug() for _ in range(200)}

    assert len(slugs) == 200
    assert all(len(slug) == 22 for slug in slugs)
    assert all(SLUG_PATTERN.fullmatch(slug) for slug in slugs)


@pytest.mark.parametrize(
    ("value", "valid"), [("a" * 22, True), ("a" * 9, False), ("a" * 33, False), ("a b" * 5, False), ("../" * 5, False)]
)
def test_slug_validity(value: str, valid: bool) -> None:
    assert is_valid_slug(value) is valid
    assert lookup_slug(value) == (value if valid else UNKNOWN_SLUG)


def test_a_share_request_names_exactly_one_target() -> None:
    with pytest.raises(ValidationError):
        ShareCreateRequest.model_validate({})
    with pytest.raises(ValidationError):
        ShareCreateRequest.model_validate({"aspect": "16:9", "renditionId": str(new_id())})
    with pytest.raises(ValidationError):
        ShareCreateRequest.model_validate({"aspect": "16:9", "extra": 1})


def test_a_rendition_is_picked_by_id_or_by_aspect_and_must_be_ready() -> None:
    ready = rendition(Aspect.PORTRAIT)
    pending = rendition(Aspect.SQUARE, RenditionStatus.PENDING)

    assert pick_rendition([ready, pending], ShareCreateRequest(rendition_id=ready.id)) is ready
    assert pick_rendition([ready, pending], ShareCreateRequest(aspect="9:16")) is ready
    with pytest.raises(ShareRenditionNotFoundError):
        pick_rendition([ready, pending], ShareCreateRequest(aspect="1:1"))
    with pytest.raises(ShareRenditionNotFoundError):
        pick_rendition([ready], ShareCreateRequest(rendition_id=new_id()))


async def test_creating_a_link_stores_it_and_returns_the_public_url(fixture: Fixture) -> None:
    view = await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request())

    assert view.url == f"{ORIGIN}/v/{view.slug}"
    assert (view.aspect, view.allow_indexing, view.view_count) == ("16:9", False, 0)
    assert view.rendition_id == fixture.renditions[0].id
    assert len(fixture.store.links) == 1


async def test_a_new_link_for_the_same_rendition_revokes_the_old_one(fixture: Fixture) -> None:
    first = await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request())
    second = await fixture.service.create(
        fixture.session, fixture.owner, fixture.job.id, fixture.request(allowIndexing=True)
    )

    active = [link for link in fixture.store.links if link.revoked_at is None]
    assert [link.slug for link in active] == [second.slug]
    assert second.allow_indexing
    assert first.slug != second.slug
    revoked = next(link for link in fixture.store.links if link.slug == first.slug)
    assert revoked.revoked_at == NOW


async def test_a_link_for_another_rendition_leaves_the_first_active(fixture: Fixture) -> None:
    await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request())
    await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request(aspect="9:16"))

    assert sum(link.revoked_at is None for link in fixture.store.links) == 2


async def test_a_slug_collision_draws_another_slug() -> None:
    fixture = Fixture(slugs=["taken-slug-0000000000", "fresh-slug-0000000000"])
    fixture.store.taken.add("taken-slug-0000000000")

    view = await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request())

    assert view.slug == "fresh-slug-0000000000"


async def test_only_the_owner_can_create_a_link(fixture: Fixture) -> None:
    with pytest.raises(JobNotFoundError):
        await fixture.service.create(fixture.session, new_id(), fixture.job.id, fixture.request())
    assert fixture.store.links == []


@pytest.mark.parametrize("status", ["queued", "rendering", "failed", "cancelled"])
async def test_only_a_finished_video_can_be_shared(fixture: Fixture, status: str) -> None:
    fixture.job.status = status

    with pytest.raises(JobNotShareableError):
        await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request())


async def test_revoking_disables_every_link_of_the_video_and_only_for_the_owner(fixture: Fixture) -> None:
    await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request())
    await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request(aspect="9:16"))

    with pytest.raises(JobNotFoundError):
        await fixture.service.revoke(fixture.session, new_id(), fixture.job.id)
    assert await fixture.service.revoke(fixture.session, fixture.owner, fixture.job.id) == 2
    assert await fixture.service.revoke(fixture.session, fixture.owner, fixture.job.id) == 0
    assert all(link.revoked_at is not None for link in fixture.store.links)


async def test_viewing_returns_the_page_data_without_owner_identity(fixture: Fixture) -> None:
    view = await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request())
    fixture.store.content = {"title": "How TCP works", "summary": "A tour.", "language": "en"}

    page = await fixture.service.view(fixture.session, view.slug, "viewer-1")

    assert (page.title, page.summary, page.language, page.aspect) == ("How TCP works", "A tour.", "en", "16:9")
    assert page.playback_url == f"https://cdn.example/signed/{fixture.renditions[0].id}?sig=1"
    assert page.poster_url is not None
    assert page.playback_expires_in_seconds == 900
    assert (page.duration_ms, page.width, page.height) == (61_000, 1920, 1080)
    serialized = page.model_dump_json(by_alias=True)
    assert str(fixture.owner) not in serialized
    assert str(fixture.job.id) not in serialized
    assert "owner-cookie-url" not in serialized
    assert fixture.media.signed_for == [(fixture.owner, fixture.job.render_id, fixture.renditions[0].id)]


async def test_the_title_falls_back_to_the_query_without_a_storyboard(fixture: Fixture) -> None:
    view = await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request())

    page = await fixture.service.view(fixture.session, view.slug, "viewer-1")

    assert (page.title, page.summary) == ("How does TCP work?", None)


async def test_a_view_counts_once_per_viewer_and_slug_in_the_window(fixture: Fixture) -> None:
    view = await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request())

    for viewer in ("viewer-1", "viewer-1", "viewer-2"):
        await fixture.service.view(fixture.session, view.slug, viewer)

    assert fixture.store.links[0].view_count == 2


async def test_indexing_is_reported_as_chosen(fixture: Fixture) -> None:
    view = await fixture.service.create(
        fixture.session, fixture.owner, fixture.job.id, fixture.request(allowIndexing=True)
    )

    assert (await fixture.service.view(fixture.session, view.slug, "v")).allow_indexing


async def test_every_kind_of_dead_link_looks_the_same(fixture: Fixture) -> None:
    live = await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request())
    revoked = await fixture.service.create(
        fixture.session, fixture.owner, fixture.job.id, fixture.request(aspect="9:16")
    )
    await fixture.service.revoke(fixture.session, fixture.owner, fixture.job.id)
    expired = await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request())
    next(link for link in fixture.store.links if link.slug == expired.slug).expires_at = NOW - timedelta(seconds=1)
    deleted_video = await fixture.service.create(
        fixture.session, fixture.owner, fixture.job.id, fixture.request(aspect="9:16")
    )
    fixture.job.status = "failed"

    errors: list[tuple[int, str, str | None]] = []
    for slug in (live.slug, revoked.slug, expired.slug, deleted_video.slug, new_slug(), "short", "../etc/passwd"):
        with pytest.raises(ShareNotFoundError) as caught:
            await fixture.service.view(fixture.session, slug, "viewer")
        errors.append((caught.value.status_code, caught.value.code, caught.value.detail))

    assert len(set(errors)) == 1
    assert errors[0][:2] == (404, "share_not_found")
    assert fixture.store.lookups[-1] == UNKNOWN_SLUG
    assert fixture.store.lookups[-2] == UNKNOWN_SLUG


async def test_a_rendition_that_cannot_be_signed_is_not_found(fixture: Fixture) -> None:
    view = await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request())
    fixture.renditions[0] = rendition(Aspect.LANDSCAPE, RenditionStatus.FAILED)
    fixture.media.renditions[:] = fixture.renditions

    with pytest.raises(ShareNotFoundError):
        await fixture.service.view(fixture.session, view.slug, "viewer")


async def test_a_dead_link_is_not_counted(fixture: Fixture) -> None:
    view = await fixture.service.create(fixture.session, fixture.owner, fixture.job.id, fixture.request())
    await fixture.service.revoke(fixture.session, fixture.owner, fixture.job.id)

    with pytest.raises(ShareNotFoundError):
        await fixture.service.view(fixture.session, view.slug, "viewer")

    assert fixture.store.links[0].view_count == 0
    assert fixture.views.seen == set()
