from uuid import UUID

from motionile.modules.prompts.domain import CHECKSUM_PREFIX_CHARS, EvalStatus
from motionile.modules.prompts.models import EvalRun, PromptVersion
from motionile.modules.prompts.repository import TemplateSummary
from motionile.modules.prompts.schemas import EvalRunView, TemplateView, VersionView


def template_view(summary: TemplateSummary) -> TemplateView:
    return TemplateView(
        key=summary.key,
        description=summary.description,
        active_version=summary.active_version,
        version_count=summary.version_count,
        latest_eval_status=EvalStatus(summary.latest_eval_status) if summary.latest_eval_status is not None else None,
    )


def version_view(version: PromptVersion, active_version_id: UUID | None) -> VersionView:
    return VersionView(
        id=version.id,
        version=version.version,
        checksum_prefix=version.checksum.hex()[:CHECKSUM_PREFIX_CHARS],
        eval_status=EvalStatus(version.eval_status),
        created_at=version.created_at,
        created_by=version.created_by,
        is_active=version.id == active_version_id,
    )


def eval_run_view(run: EvalRun) -> EvalRunView:
    return EvalRunView.model_validate(run)
