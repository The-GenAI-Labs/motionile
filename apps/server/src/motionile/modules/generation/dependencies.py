import hashlib
import hmac
from datetime import timedelta
from typing import Annotated, Final
from uuid import UUID

from fastapi import Depends, Request

from motionile.core.dependencies import ResourcesDep, SettingsDep
from motionile.core.errors import UnauthorizedError
from motionile.modules.auth import CurrentPrincipalDep
from motionile.modules.generation.admin_service import AdminJobsService, TraceSettings
from motionile.modules.generation.factory import generation_service_for, job_events_for
from motionile.modules.generation.job_events import JobEvents
from motionile.modules.generation.library_service import LibraryService
from motionile.modules.generation.service import GenerationService
from motionile.modules.generation.share_service import RedisViewCounter, ShareService
from motionile.modules.media import media_service_for

INTERNAL_HEADER: Final = "X-Motionile-Internal"


def digest_of(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def is_internal_share_caller(request: Request, settings: SettingsDep) -> bool:
    secret = settings.share.internal_secret
    supplied = request.headers.get(INTERNAL_HEADER)
    if secret is None or supplied is None:
        return False
    return hmac.compare_digest(digest_of(supplied), digest_of(secret.get_secret_value()))


def get_generation_service(resources: ResourcesDep) -> GenerationService:
    return generation_service_for(resources)


def get_library_service(resources: ResourcesDep) -> LibraryService:
    return LibraryService(media_service_for(resources))


def get_share_service(resources: ResourcesDep) -> ShareService:
    settings = resources.settings
    return ShareService(
        media_service_for(resources),
        resources.clock,
        RedisViewCounter(resources.redis_store),
        web_origin=settings.auth.web_origin,
        playback_ttl=timedelta(seconds=settings.media.signed_url_ttl_seconds),
    )


def get_admin_jobs_service(resources: ResourcesDep) -> AdminJobsService:
    ai = resources.settings.ai
    return AdminJobsService(
        resources.clock, TraceSettings(ai.tracing_enabled, ai.langfuse_host, ai.langfuse_project_id)
    )


def get_job_events(resources: ResourcesDep) -> JobEvents:
    return job_events_for(resources)


def get_current_user_id(principal: CurrentPrincipalDep) -> UUID:
    if principal.user_id is None:
        raise UnauthorizedError(code="unauthenticated")
    return principal.user_id


GenerationServiceDep = Annotated[GenerationService, Depends(get_generation_service)]
CurrentUserIdDep = Annotated[UUID, Depends(get_current_user_id)]
JobEventsDep = Annotated[JobEvents, Depends(get_job_events)]
LibraryServiceDep = Annotated[LibraryService, Depends(get_library_service)]
ShareServiceDep = Annotated[ShareService, Depends(get_share_service)]
InternalShareCallerDep = Annotated[bool, Depends(is_internal_share_caller)]
AdminJobsServiceDep = Annotated[AdminJobsService, Depends(get_admin_jobs_service)]
