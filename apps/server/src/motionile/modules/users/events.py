from typing import ClassVar
from uuid import UUID

from motionile.core.events import DomainEvent


class UserDeletionRequested(DomainEvent):
    name: ClassVar[str] = "user.deletion_requested"
    user_id: UUID


class UserPurged(DomainEvent):
    name: ClassVar[str] = "user.purged"
    user_id: UUID
