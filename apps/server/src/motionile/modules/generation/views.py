from collections.abc import Sequence

from pydantic import TypeAdapter

from motionile.core.errors import FieldError
from motionile.engine.ai.job_options import JobOptions, JobStatus
from motionile.engine.ai.ports import JobSource
from motionile.engine.ai.storyboard import (
    Storyboard,
    StoryboardExpectation,
    StoryboardIssue,
    StoryboardLimits,
    validate_storyboard,
)
from motionile.modules.generation.messages import describe_error
from motionile.modules.generation.models import Job
from motionile.modules.generation.models import Storyboard as StoryboardRow
from motionile.modules.generation.schemas import (
    JobOptionsView,
    JobView,
    OnScreenLimitView,
    RevisionView,
    StoryboardLimitsView,
    StoryboardView,
)

CONTENT_FIELD = "content"
JOB_SOURCES: TypeAdapter[JobSource] = TypeAdapter(JobSource)


def job_source(value: str) -> JobSource:
    return JOB_SOURCES.validate_python(value)


def options_view(options: JobOptions) -> JobOptionsView:
    revision = options.revision
    return JobOptionsView(
        duration_seconds=options.duration_seconds,
        aspects=options.aspects,
        style=options.style,
        voice_id=options.voice_id,
        voice_is_cloned=options.voice_is_cloned,
        language=options.language,
        review_storyboard=options.review_storyboard,
        music_track_id=options.music_track_id,
        subtitles=options.subtitles,
        burn_in_subtitles=options.burn_in_subtitles,
        revision=RevisionView(instructions=revision.instructions, scene_ids=list(revision.scene_ids))
        if revision is not None
        else None,
    )


def job_view(job: Job, fallback_scene_ids: Sequence[str] = ()) -> JobView:
    description = describe_error(job.error_code, job.error_message)
    return JobView(
        id=job.id,
        source=job_source(job.source),
        topic_id=job.topic_id,
        query=job.query,
        options=options_view(JobOptions.model_validate(job.options)),
        status=JobStatus(job.status),
        current_stage=job.current_stage,
        credits_estimated=job.credits_estimated,
        credits_reserved=job.credits_reserved,
        credits_charged=job.credits_charged,
        error_code=job.error_code,
        error_title=description.title if description else None,
        error_message=description.message if description else None,
        cancel_requested_at=job.cancel_requested_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        render_id=job.render_id,
        parent_job_id=job.parent_job_id,
        fallback_scene_ids=list(fallback_scene_ids),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def expectation_for(options: JobOptions) -> StoryboardExpectation:
    return StoryboardExpectation(
        duration_ms=options.target_duration_ms,
        aspects=options.aspects,
        language=options.language,
        style=options.style,
    )


def storyboard_issues(storyboard: Storyboard, options: JobOptions, limits: StoryboardLimits) -> list[StoryboardIssue]:
    return validate_storyboard(storyboard, expectation_for(options), limits)


def limits_view(limits: StoryboardLimits) -> StoryboardLimitsView:
    return StoryboardLimitsView(
        min_scenes=limits.min_scenes,
        max_scenes=limits.max_scenes,
        duration_tolerance_percent=limits.duration_tolerance_percent,
        min_words_per_second=limits.min_words_per_second,
        max_words_per_second=limits.max_words_per_second,
        nominal_words_per_second=limits.nominal_words_per_second,
        on_screen_text=[
            OnScreenLimitView(aspect=aspect, characters=characters)
            for aspect, characters in limits.on_screen_text_chars.items()
        ],
    )


def storyboard_view(row: StoryboardRow, options: JobOptions, limits: StoryboardLimits) -> StoryboardView:
    content = Storyboard.model_validate(row.content)
    return StoryboardView(
        version=row.version,
        approved=row.approved_at is not None,
        origin=row.origin,
        content=content,
        issues=storyboard_issues(content, options, limits),
        limits=limits_view(limits),
        updated_at=row.updated_at,
    )


def issue_errors(storyboard: Storyboard, issues: Sequence[StoryboardIssue]) -> list[FieldError]:
    positions = {scene.id: scene.position for scene in storyboard.scenes}
    errors: list[FieldError] = []
    for issue in issues:
        position = positions.get(issue.scene_id) if issue.scene_id is not None else None
        field = f"{CONTENT_FIELD}.scenes.{position}" if position is not None else CONTENT_FIELD
        errors.append(FieldError(field=field, message=issue.message, type=issue.code.value))
    return errors
