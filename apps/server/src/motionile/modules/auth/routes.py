from collections.abc import Callable, Coroutine
from typing import Any

import structlog
from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute

from motionile.core.errors import AppError
from motionile.modules.auth.dependencies import get_auth_service, get_runtime

logger = structlog.get_logger(__name__)


class AuthRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def audited(request: Request) -> Response:
            try:
                return await handler(request)
            except (AppError, RequestValidationError):
                service = get_auth_service(request, get_runtime(request))
                try:
                    async with service.resources.database.transaction() as session:
                        await service.audit(session, f"{self.name}.rejected")
                except Exception:
                    logger.warning("auth.rejection_audit_unavailable", action=self.name)
                raise

        return audited
