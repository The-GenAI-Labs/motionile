from typing import ClassVar
from uuid import UUID

from motionile.core.events import DomainEvent


class JobCompleted(DomainEvent):
    name: ClassVar[str] = "generation.job_completed"

    job_id: UUID
    user_id: UUID
    duration_ms: int
    credits_charged: int
