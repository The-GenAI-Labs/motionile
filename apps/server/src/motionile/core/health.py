from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]


health_router = APIRouter(prefix="/health", tags=["health"])


@health_router.get(
    "/live",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    operation_id="getLiveness",
    summary="Report that the process is running",
)
async def live() -> HealthResponse:
    return HealthResponse(status="ok")


@health_router.get(
    "/ready",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    operation_id="getReadiness",
    summary="Report that the process is ready to serve traffic",
)
async def ready() -> HealthResponse:
    return HealthResponse(status="ok")
