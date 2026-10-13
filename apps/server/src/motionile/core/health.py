import asyncio
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Literal

import structlog
from fastapi import APIRouter, Response, status

from motionile.core.dependencies import ResourcesDep
from motionile.core.errors import problem_responses
from motionile.core.schemas import ResponseModel

logger = structlog.get_logger(__name__)


class DependencyStatus(StrEnum):
    OK = "ok"
    UNAVAILABLE = "unavailable"


class LivenessResponse(ResponseModel):
    status: Literal["ok"]


class ReadinessChecks(ResponseModel):
    postgres: DependencyStatus
    redis: DependencyStatus


class ReadinessResponse(ResponseModel):
    status: Literal["ok", "unavailable"]
    checks: ReadinessChecks


health_router = APIRouter(prefix="/health", tags=["health"])


async def probe(name: str, check: Callable[[], Awaitable[None]]) -> DependencyStatus:
    try:
        await check()
    except (Exception, asyncio.CancelledError) as error:
        logger.warning("health.dependency_unavailable", dependency=name, error=type(error).__name__)
        return DependencyStatus.UNAVAILABLE
    return DependencyStatus.OK


@health_router.get(
    "/live",
    response_model=LivenessResponse,
    status_code=status.HTTP_200_OK,
    summary="Report that the process is running",
    responses=problem_responses(status.HTTP_500_INTERNAL_SERVER_ERROR),
)
async def live() -> LivenessResponse:
    return LivenessResponse(status="ok")


@health_router.get(
    "/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Report whether Postgres and Redis are reachable",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse, "description": "A dependency is down"}}
    | problem_responses(status.HTTP_500_INTERNAL_SERVER_ERROR),
)
async def ready(resources: ResourcesDep, response: Response) -> ReadinessResponse:
    settings = resources.settings
    postgres, redis = await asyncio.gather(
        probe("postgres", lambda: resources.database.ping(settings.database.health_timeout_seconds)),
        probe("redis", lambda: resources.redis_store.ping(settings.redis.health_timeout_seconds)),
    )
    checks = ReadinessChecks(postgres=postgres, redis=redis)
    healthy = postgres is DependencyStatus.OK and redis is DependencyStatus.OK
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ok" if healthy else "unavailable", checks=checks)
