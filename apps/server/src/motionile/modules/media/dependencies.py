from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, Request

from motionile.core.dependencies import ResourcesDep, SettingsDep
from motionile.core.errors import ServiceUnavailableError, UnauthorizedError
from motionile.modules.auth import CurrentPrincipalDep
from motionile.modules.media.assets import AssetService
from motionile.modules.media.delivery import MediaDelivery
from motionile.modules.media.factory import (
    assets_for,
    delivery_for,
    media_service_for,
    music_service_for,
    render_events_for,
    speech_for,
)
from motionile.modules.media.golden import GoldenCatalog, golden_directory
from motionile.modules.media.music import MusicService
from motionile.modules.media.render_events import RenderEvents
from motionile.modules.media.service import MediaService
from motionile.modules.media.speech import SpeechService
from motionile.modules.media.voice_lookup import VoiceLookup


def get_media_delivery(resources: ResourcesDep) -> MediaDelivery:
    return delivery_for(resources)


def get_asset_service(resources: ResourcesDep) -> AssetService:
    return assets_for(resources)


def get_media_service(resources: ResourcesDep) -> MediaService:
    return media_service_for(resources)


def get_music_service(resources: ResourcesDep) -> MusicService:
    return music_service_for(resources)


def get_speech_service(resources: ResourcesDep) -> SpeechService:
    return speech_for(resources)


def get_render_events(resources: ResourcesDep) -> RenderEvents:
    return render_events_for(resources)


def get_golden_catalog(settings: SettingsDep) -> GoldenCatalog:
    return GoldenCatalog(golden_directory(settings))


def get_voice_lookup(request: Request) -> VoiceLookup:
    lookup: object = getattr(request.app.state, "voice_lookup", None)
    if lookup is None:
        raise ServiceUnavailableError("Voice selection is not available.", code="voices_unavailable")
    return cast("VoiceLookup", lookup)


def get_current_user_id(principal: CurrentPrincipalDep) -> UUID:
    if principal.user_id is None:
        raise UnauthorizedError(code="unauthenticated")
    return principal.user_id


MediaDeliveryDep = Annotated[MediaDelivery, Depends(get_media_delivery)]
AssetServiceDep = Annotated[AssetService, Depends(get_asset_service)]
MediaServiceDep = Annotated[MediaService, Depends(get_media_service)]
MusicServiceDep = Annotated[MusicService, Depends(get_music_service)]
SpeechServiceDep = Annotated[SpeechService, Depends(get_speech_service)]
RenderEventsDep = Annotated[RenderEvents, Depends(get_render_events)]
GoldenCatalogDep = Annotated[GoldenCatalog, Depends(get_golden_catalog)]
VoiceLookupDep = Annotated[VoiceLookup, Depends(get_voice_lookup)]
CurrentUserIdDep = Annotated[UUID, Depends(get_current_user_id)]
