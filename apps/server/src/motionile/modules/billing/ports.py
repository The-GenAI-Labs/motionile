from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.audit import AuditEvent
from motionile.modules.billing.repository import BillingStore

type Transaction = Callable[[], AbstractAsyncContextManager[AsyncSession]]
type StoreFactory = Callable[[AsyncSession], BillingStore]
type AuditRecorder = Callable[[AsyncSession, AuditEvent], Awaitable[UUID]]
type Alert = Callable[..., None]
type EventDispatcher = Callable[[AsyncSession, UUID, bool], None]
type Savepoint = Callable[[AsyncSession], AbstractAsyncContextManager[object]]
type Revalidation = Callable[[AsyncSession], None]


def begin_savepoint(session: AsyncSession) -> AbstractAsyncContextManager[object]:
    return session.begin_nested()
