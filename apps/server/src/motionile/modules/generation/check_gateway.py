import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Final
from uuid import UUID

from motionile.core.storage.base import Storage
from motionile.engine.render.models import RenderEngineError
from motionile.modules.generation.ports import CheckedFrame, CheckOutcome
from motionile.modules.media import (
    CHECK_REQUEST_NAME,
    CHECK_RESULT_NAME,
    CompositionCheckRequest,
    CompositionCheckResult,
    composition_check_key,
)

type Deferral = Callable[[UUID, str], Awaitable[None]]

JSON_CONTENT_TYPE: Final = "application/json"
POLL_SECONDS: Final = 1.0


class CheckTimedOutError(RenderEngineError):
    code = "check_timeout"

    def __init__(self) -> None:
        super().__init__("The composition check did not finish in time.")


async def single_chunk(data: bytes) -> AsyncIterator[bytes]:
    yield data


class StorageCheckGateway:
    def __init__(
        self, storage: Storage, defer: Deferral, *, timeout_seconds: float, poll_seconds: float = POLL_SECONDS
    ) -> None:
        self._storage = storage
        self._defer = defer
        self._timeout_seconds = timeout_seconds
        self._poll_seconds = poll_seconds

    async def run(self, job_id: UUID, request: CompositionCheckRequest) -> CheckOutcome:
        check_id = request.check_id
        result = await self._stored(job_id, check_id)
        if result is None:
            await self._submit(job_id, check_id, request)
            result = await self._wait(job_id, check_id)
        return await self._outcome(result)

    async def _submit(self, job_id: UUID, check_id: str, request: CompositionCheckRequest) -> None:
        key = composition_check_key(job_id, check_id, CHECK_REQUEST_NAME)
        if not await self._storage.exists(key):
            document = request.model_dump_json(by_alias=True).encode("utf-8")
            await self._storage.put(key, single_chunk(document), content_type=JSON_CONTENT_TYPE)
        await self._defer(job_id, check_id)

    async def _wait(self, job_id: UUID, check_id: str) -> CompositionCheckResult:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                while True:
                    await asyncio.sleep(self._poll_seconds)
                    result = await self._stored(job_id, check_id)
                    if result is not None:
                        return result
        except TimeoutError:
            raise CheckTimedOutError from None

    async def _stored(self, job_id: UUID, check_id: str) -> CompositionCheckResult | None:
        key = composition_check_key(job_id, check_id, CHECK_RESULT_NAME)
        if not await self._storage.exists(key):
            return None
        return CompositionCheckResult.model_validate_json(await self._read(key))

    async def _read(self, key: str) -> bytes:
        return b"".join([chunk async for chunk in self._storage.get(key)])

    async def _outcome(self, result: CompositionCheckResult) -> CheckOutcome:
        frames = tuple(
            [
                CheckedFrame(entry.scene_id, entry.aspect.value, entry.time_ms, await self._read(entry.key))
                for entry in result.frames
            ]
        )
        return CheckOutcome(report=result.report, frames=frames)
