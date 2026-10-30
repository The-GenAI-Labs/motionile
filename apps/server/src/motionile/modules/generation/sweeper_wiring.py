from motionile.core.resources import Resources
from motionile.modules.generation.factory import generation_service_for
from motionile.modules.generation.runtime_settings import PlatformSettingsReader, RuntimeSettings
from motionile.modules.generation.sweepers import Sweeper
from motionile.modules.media import media_service_for


def sweeper_for(resources: Resources) -> Sweeper:
    return Sweeper(
        resources.database.transaction,
        generation_service_for(resources),
        RuntimeSettings(PlatformSettingsReader(resources.redis_store)),
        resources.clock,
        media_service_for(resources),
    )
