from collections.abc import Mapping

from motionile.engine.ai.job_options import TERMINAL_JOB_STATUSES, JobStatus

ACTIVE_JOB_STATUSES: frozenset[JobStatus] = frozenset(set(JobStatus) - TERMINAL_JOB_STATUSES)

JOB_TRANSITIONS: Mapping[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset(
        {
            JobStatus.PLANNING,
            JobStatus.VOICING,
            JobStatus.VALIDATING,
            JobStatus.CANCELLED,
            JobStatus.FAILED,
        }
    ),
    JobStatus.PLANNING: frozenset(
        {JobStatus.AWAITING_APPROVAL, JobStatus.VOICING, JobStatus.CANCELLED, JobStatus.FAILED}
    ),
    JobStatus.AWAITING_APPROVAL: frozenset({JobStatus.PLANNING, JobStatus.VOICING, JobStatus.CANCELLED}),
    JobStatus.VOICING: frozenset({JobStatus.GENERATING, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.GENERATING: frozenset({JobStatus.VALIDATING, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.VALIDATING: frozenset({JobStatus.GENERATING, JobStatus.RENDERING, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.RENDERING: frozenset({JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}

INITIAL_JOB_STATUS = JobStatus.QUEUED


class InvalidJobTransitionError(Exception):
    def __init__(self, current: JobStatus, target: JobStatus) -> None:
        super().__init__(f"jobs.status cannot move from {current.value} to {target.value}")
        self.current = current
        self.target = target


def can_transition(current: JobStatus, target: JobStatus) -> bool:
    return target in JOB_TRANSITIONS[current]


def require_transition(current: JobStatus, target: JobStatus) -> None:
    if not can_transition(current, target):
        raise InvalidJobTransitionError(current, target)


def is_terminal(status: JobStatus) -> bool:
    return status in TERMINAL_JOB_STATUSES
