from collections.abc import Callable, Mapping, Sequence
from datetime import timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.engine.audio.narration_models import NarrationDocument
from motionile.modules.audit import AuditContext
from motionile.modules.media.delivery import MediaDelivery, MediaSessionGrant
from motionile.modules.media.domain import Aspect, AssetStatus, RenderSource, RenditionStatus
from motionile.modules.media.exceptions import RenderNotFoundError
from motionile.modules.media.models import Asset, Render, Rendition
from motionile.modules.media.render_commands import RenderCommands
from motionile.modules.media.render_options import RenderOptions, ResolvedVoice, SceneScript
from motionile.modules.media.render_view import music_track_id, render_view
from motionile.modules.media.repository import RenderStore, SqlRenderRepository
from motionile.modules.media.schemas import MusicAttributionView, MusicTrackView, RenderView, RenditionView

type RenderStoreFactory = Callable[[AsyncSession], RenderStore]

ASPECT_ORDER = {aspect: position for position, aspect in enumerate((Aspect.LANDSCAPE, Aspect.PORTRAIT, Aspect.SQUARE))}


class MediaService:
    def __init__(
        self,
        delivery: MediaDelivery,
        store_factory: RenderStoreFactory = SqlRenderRepository,
        *,
        commands: RenderCommands | None = None,
    ) -> None:
        self._delivery = delivery
        self._store_factory = store_factory
        self._commands = commands

    @property
    def delivery(self) -> MediaDelivery:
        return self._delivery

    def media_session(self, user_id: UUID) -> MediaSessionGrant:
        return self._delivery.session(user_id)

    async def signed_url(self, key: str, ttl: timedelta, *, owner_user_id: UUID | None = None) -> str:
        return await self._delivery.signed_url(key, ttl, owner_user_id=owner_user_id)

    def _render_commands(self) -> RenderCommands:
        if self._commands is None:
            raise RuntimeError("this MediaService was built without render commands")
        return self._commands

    async def create_render(  # noqa: PLR0913
        self,
        session: AsyncSession,
        user_id: UUID,
        composition_html: str,
        options: RenderOptions,
        source: RenderSource,
        *,
        audio_uploads: Mapping[str, bytes] | None = None,
        context: AuditContext | None = None,
    ) -> RenderView:
        return await self._render_commands().create_render(
            session, user_id, composition_html, options, source, audio_uploads=audio_uploads, context=context
        )

    async def cancel_render(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> RenderView:
        return await self._render_commands().cancel_render(session, user_id, render_id)

    async def narrate(
        self,
        session: AsyncSession,
        user_id: UUID,
        scenes: Sequence[SceneScript],
        voice: ResolvedVoice,
        *,
        padding_ms: int | None = None,
    ) -> NarrationDocument:
        return await self._render_commands().narrate(session, user_id, scenes, voice, padding_ms=padding_ms)

    async def selectable_music(self, session: AsyncSession) -> list[MusicTrackView]:
        return await self._render_commands().selectable_music(session)

    async def get_render(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> RenderView:
        return render_view(await self._owned_render(session, user_id, render_id))

    async def renditions_for(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> list[RenditionView]:
        render = await self._owned_render(session, user_id, render_id)
        store = self._store_factory(session)
        renditions = sorted(
            await store.renditions(render.id), key=lambda item: ASPECT_ORDER.get(Aspect(item.aspect), len(ASPECT_ORDER))
        )
        asset_ids = {
            asset_id
            for asset_id in (
                render.subtitles_vtt_asset_id,
                render.subtitles_srt_asset_id,
                *(item.asset_id for item in renditions),
                *(item.poster_webp_asset_id for item in renditions),
                *(item.poster_jpeg_asset_id for item in renditions),
            )
            if asset_id is not None
        }
        assets = await store.assets_by_ids(user_id, asset_ids)
        attribution = await self._attribution(store, render)
        subtitles_url = await self._url(user_id, assets, render.subtitles_vtt_asset_id)
        subtitles_srt_url = await self._url(user_id, assets, render.subtitles_srt_asset_id)
        return [
            await self._rendition_view(
                user_id,
                item,
                assets,
                attribution=attribution,
                subtitles_url=subtitles_url,
                subtitles_srt_url=subtitles_srt_url,
            )
            for item in renditions
        ]

    async def _owned_render(self, session: AsyncSession, user_id: UUID, render_id: UUID) -> Render:
        render = await self._store_factory(session).get_render(user_id, render_id)
        if render is None:
            raise RenderNotFoundError
        return render

    async def _attribution(self, store: RenderStore, render: Render) -> MusicAttributionView | None:
        track_id = music_track_id(render)
        if track_id is None:
            return None
        track = await store.music_track(track_id)
        if track is None:
            return None
        return MusicAttributionView(
            track_id=track.id,
            title=track.title,
            license_name=track.license_name,
            license_url=track.license_url,
            attribution_text=track.attribution_text,
        )

    async def _url(self, owner_user_id: UUID, assets: dict[UUID, Asset], asset_id: UUID | None) -> str | None:
        asset = assets.get(asset_id) if asset_id is not None else None
        if asset is None or asset.status != AssetStatus.READY.value:
            return None
        return await self._delivery.url_for(asset.storage_key, owner_user_id=owner_user_id)

    async def _rendition_view(  # noqa: PLR0913
        self,
        owner_user_id: UUID,
        rendition: Rendition,
        assets: dict[UUID, Asset],
        *,
        attribution: MusicAttributionView | None,
        subtitles_url: str | None,
        subtitles_srt_url: str | None,
    ) -> RenditionView:
        ready = rendition.status == RenditionStatus.READY.value
        return RenditionView(
            id=rendition.id,
            aspect=Aspect(rendition.aspect),
            width=rendition.width,
            height=rendition.height,
            duration_ms=rendition.duration_ms,
            status=RenditionStatus(rendition.status),
            burned_in_subtitles=rendition.burned_in_subtitles,
            url=await self._url(owner_user_id, assets, rendition.asset_id) if ready else None,
            poster_url=await self._url(owner_user_id, assets, rendition.poster_webp_asset_id),
            poster_jpeg_url=await self._url(owner_user_id, assets, rendition.poster_jpeg_asset_id),
            subtitles_url=subtitles_url,
            subtitles_srt_url=subtitles_srt_url,
            attribution=attribution,
        )
