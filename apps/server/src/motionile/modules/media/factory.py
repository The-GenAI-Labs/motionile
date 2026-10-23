from motionile.core.resources import Resources
from motionile.modules.media.builders import (
    assets_for,
    audio_check_for,
    delivery_for,
    music_service_for,
    render_commands_for,
    render_events_for,
    render_pipeline_for,
    speech_for,
    stream_slots_for,
)
from motionile.modules.media.service import MediaService
from motionile.modules.media.tasks import dispatch_render

SERVICE_KEY = "media.service"


def media_service_for(resources: Resources) -> MediaService:
    return resources.shared_instance(
        SERVICE_KEY,
        lambda: MediaService(delivery_for(resources), commands=render_commands_for(resources, dispatch_render)),
    )


__all__ = [
    "assets_for",
    "audio_check_for",
    "delivery_for",
    "media_service_for",
    "music_service_for",
    "render_commands_for",
    "render_events_for",
    "render_pipeline_for",
    "speech_for",
    "stream_slots_for",
]
