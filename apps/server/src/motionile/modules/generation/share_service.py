import hashlib
from collections.abc import Callable
from datetime import timedelta
from typing import Final, Protocol
from uuid import UUID

import structlog
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.core.redis import RedisStore
from motionile.engine.ai.job_options import AspectName, JobStatus
from motionile.modules.generation.exceptions import (
    JobNotFoundError,
    JobNotShareableError,
    ShareNotFoundError,
    ShareRenditionNotFoundError,
)
from motionile.modules.generation.models import Job, ShareLink
from motionile.modules.generation.share_repository import ShareStore, SqlShareRepository
from motionile.modules.generation.share_schemas import ShareCreateRequest, SharedVideoView, ShareLinkView
from motionile.modules.generation.slugs import lookup_slug, new_slug
from motionile.modules.media import RenditionStatus, RenditionView, SignedRendition

type ShareStoreFactory = Callable[[AsyncSession], ShareStore]

VIEW_NAMESPACE: Final = "share.view"
VIEW_WINDOW: Final = timedelta(hours=1)
SLUG_ATTEMPTS: Final = 5
VIEWER_DIGEST_CHARS: Final = 32
ASPECT_NAMES: Final[tuple[AspectName, ...]] = ("16:9", "9:16", "1:1")

logger = structlog.get_logger(__name__)


class ShareMedia(Protocol):
    async def renditions_for(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> list[RenditionView]: ...

    async def signed_rendition(
        self, session: AsyncSession, owner_user_id: UUID, render_id: UUID, rendition_id: UUID, ttl: timedelta
    ) -> SignedRendition | None: ...


class ViewCounter(Protocol):
    async def first_view(self, slug: str, viewer: str) -> bool: ...


class RedisViewCounter:
    def __init__(self, store: RedisStore) -> None:
        self._store = store

    async def first_view(self, slug: str, viewer: str) -> bool:
        digest = hashlib.sha256(viewer.encode("utf-8")).hexdigest()[:VIEWER_DIGEST_CHARS]
        key = self._store.keys.key(VIEW_NAMESPACE, slug, digest)
        try:
            return await self._store.set_if_absent(key, b"1", ttl=VIEW_WINDOW)
        except (RedisError, OSError):
            logger.warning("generation.share_view_count_failed")
            return False


def share_url(web_origin: str, slug: str) -> str:
    return f"{web_origin.rstrip('/')}/v/{slug}"


def pick_rendition(renditions: list[RenditionView], request: ShareCreateRequest) -> RenditionView:
    for rendition in renditions:
        if rendition.status is not RenditionStatus.READY:
            continue
        if request.rendition_id is not None and rendition.id == request.rendition_id:
            return rendition
        if request.aspect is not None and rendition.aspect.value == request.aspect:
            return rendition
    raise ShareRenditionNotFoundError


def aspect_name(value: str) -> AspectName:
    return next(name for name in ASPECT_NAMES if name == value)


class ShareService:
    def __init__(  # noqa: PLR0913
        self,
        media: ShareMedia,
        clock: Clock,
        views: ViewCounter,
        *,
        web_origin: str,
        playback_ttl: timedelta,
        store_factory: ShareStoreFactory = SqlShareRepository,
        slug_factory: Callable[[], str] = new_slug,
    ) -> None:
        self._media = media
        self._clock = clock
        self._views = views
        self._web_origin = web_origin
        self._playback_ttl = playback_ttl
        self._store_factory = store_factory
        self._slug_factory = slug_factory

    async def create(
        self, session: AsyncSession, user_id: UUID, job_id: UUID, request: ShareCreateRequest
    ) -> ShareLinkView:
        store = self._store_factory(session)
        job = await store.owned_job(user_id, job_id)
        if job is None:
            raise JobNotFoundError
        if job.status != JobStatus.COMPLETED.value or job.render_id is None:
            raise JobNotShareableError
        renditions = await self._media.renditions_for(session, user_id, job.render_id)
        rendition = pick_rendition(renditions, request)
        await store.revoke(job.id, rendition.id, self._clock.now())
        link = await self._insert(store, job.id, rendition.id, request.allow_indexing)
        return ShareLinkView(
            slug=link.slug,
            url=share_url(self._web_origin, link.slug),
            rendition_id=rendition.id,
            aspect=aspect_name(rendition.aspect.value),
            allow_indexing=link.is_public,
            view_count=link.view_count,
            created_at=link.created_at,
        )

    async def revoke(self, session: AsyncSession, user_id: UUID, job_id: UUID) -> int:
        store = self._store_factory(session)
        job = await store.owned_job(user_id, job_id)
        if job is None:
            raise JobNotFoundError
        return await store.revoke(job.id, None, self._clock.now())

    async def view(self, session: AsyncSession, slug: str, viewer: str) -> SharedVideoView:
        store = self._store_factory(session)
        found = await store.find(lookup_slug(slug))
        if found is None or not self._available(found[0], found[1]):
            raise ShareNotFoundError
        link, job = found
        render_id = job.render_id
        signed = (
            await self._media.signed_rendition(session, job.user_id, render_id, link.rendition_id, self._playback_ttl)
            if render_id is not None
            else None
        )
        if signed is None:
            raise ShareNotFoundError
        content = await store.approved_content(job.id) or {}
        if await self._views.first_view(link.slug, viewer):
            await store.record_view(link.id)
        return SharedVideoView(
            title=str(content.get("title") or job.query),
            summary=str(content["summary"]) if content.get("summary") else None,
            language=str(content["language"]) if content.get("language") else None,
            duration_ms=signed.duration_ms,
            aspect=aspect_name(signed.aspect.value),
            width=signed.width,
            height=signed.height,
            poster_url=signed.poster_url,
            playback_url=signed.url,
            playback_expires_in_seconds=int(signed.expires_in.total_seconds()),
            allow_indexing=link.is_public,
        )

    def _available(self, link: ShareLink, job: Job) -> bool:
        expired = link.expires_at is not None and link.expires_at <= self._clock.now()
        return link.revoked_at is None and not expired and job.status == JobStatus.COMPLETED.value

    async def _insert(self, store: ShareStore, job_id: UUID, rendition_id: UUID, allow_indexing: bool) -> ShareLink:
        for _ in range(SLUG_ATTEMPTS):
            link = await store.insert(job_id, rendition_id, self._slug_factory(), allow_indexing=allow_indexing)
            if link is not None:
                return link
        raise ShareSlugExhaustedError


class ShareSlugExhaustedError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("could not allocate a share slug")
