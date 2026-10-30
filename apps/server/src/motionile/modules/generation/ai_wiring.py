import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.engine.ai.guardrails import GuardResult, InputKind
from motionile.engine.ai.llm.models import CallContext, LlmError, LlmTask, LlmUsage, RoutingConfig
from motionile.engine.ai.llm.routing import parse_routing
from motionile.modules.credits import UsageEntry, UsageRecord, record_usage
from motionile.modules.generation.exceptions import AiUnavailableError
from motionile.modules.platform import SettingValue

MAX_GUARD_CHARS = 30_000
TEXT_SEPARATOR = "\n\n"
GUARD_STAGE = "guard"
KEY_PREFIX = "llm:"
MAX_CONCURRENT_GUARDS = 8

type SettingRead = Callable[[str], Awaitable[SettingValue]]
type UsageRecorder = Callable[[AsyncSession, UsageEntry], Awaitable[UUID]]
type Transaction = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class SettingsRoutingProvider:
    def __init__(self, read: SettingRead) -> None:
        self._read = read

    async def routing(self) -> RoutingConfig:
        value = await self._read("ai.model_routing")
        if not isinstance(value, str):
            raise TypeError("setting ai.model_routing is not a string")
        return parse_routing(value)


class SettingsBudgetProvider:
    def __init__(self, read: SettingRead) -> None:
        self._read = read

    async def job_token_budget(self) -> int:
        value = await self._read("ai.job_token_budget")
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("setting ai.job_token_budget is not an integer")
        return value


def usage_key(call_key: str) -> str:
    return KEY_PREFIX + hashlib.sha256(call_key.encode("utf-8")).hexdigest()


class RecordedUsageLedger:
    def __init__(self, transaction: Transaction, record: UsageRecorder = record_usage) -> None:
        self._transaction = transaction
        self._record = record

    async def record(self, context: CallContext, task: LlmTask, usage: LlmUsage) -> None:
        del task
        entry = UsageEntry(
            user_id=context.user_id,
            stage=context.stage,
            provider=usage.provider,
            key=usage_key(context.call_key),
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_micros_usd=usage.cost_micros_usd,
            job_id=context.job_id,
        )
        async with self._transaction() as session:
            await self._record(session, entry)

    async def tokens_used(self, job_id: UUID) -> int:
        statement = select(func.coalesce(func.sum(UsageRecord.input_tokens + UsageRecord.output_tokens), 0)).where(
            UsageRecord.job_id == job_id
        )
        async with self._transaction() as session:
            return int(await session.scalar(statement) or 0)


def chunk_texts(texts: Sequence[str], limit: int = MAX_GUARD_CHARS) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for text in texts:
        addition = len(text) + len(TEXT_SEPARATOR)
        if current and size + addition > limit:
            chunks.append(TEXT_SEPARATOR.join(current))
            current, size = [], 0
        current.append(text[:limit])
        size += addition
    if current:
        chunks.append(TEXT_SEPARATOR.join(current))
    return chunks


def guard_context(user_id: UUID, job_id: UUID, kind: InputKind) -> CallContext:
    return CallContext(user_id=user_id, job_id=job_id, stage=GUARD_STAGE, call_key=f"edit:{kind}:{job_id}:{new_id()}")


class TextGuard(Protocol):
    async def check(self, text: str, context: CallContext, kind: InputKind) -> GuardResult: ...


class InputGuardEditGuard:
    def __init__(self, guard: TextGuard, *, max_concurrent: int = MAX_CONCURRENT_GUARDS) -> None:
        self._guard = guard
        self._slots = asyncio.Semaphore(max_concurrent)

    async def check_edit(self, user_id: UUID, job_id: UUID, texts: Sequence[str]) -> GuardResult:
        for chunk in chunk_texts(texts):
            result = await self._check(chunk, guard_context(user_id, job_id, "storyboard_edit"), "storyboard_edit")
            if not result.allowed:
                return result
        return GuardResult.allow()

    async def check_instructions(self, user_id: UUID, job_id: UUID, text: str) -> GuardResult:
        return await self._check(text, guard_context(user_id, job_id, "instructions"), "instructions")

    async def _check(self, text: str, context: CallContext, kind: InputKind) -> GuardResult:
        async with self._slots:
            try:
                return await self._guard.check(text, context, kind)
            except LlmError as error:
                raise AiUnavailableError(error.code) from None
