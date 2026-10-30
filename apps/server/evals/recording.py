from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from evals.errors import RecordingError
from evals.report import RunReport, SuiteReport
from motionile.core.config import Settings
from motionile.core.db import Database, create_engine
from motionile.modules.prompts import ExternalRun, record_external_run
from motionile.modules.prompts.domain import RunTrigger

APPLICATION_NAME: Final = "motionile-evals"
CASE_ERROR_CODE: Final = "eval_case_failed"
TRIGGERS: Final = {"ci": RunTrigger.CI, "nightly": RunTrigger.NIGHTLY}


def run_for(
    suite: SuiteReport,
    report: RunReport,
    trigger: RunTrigger,
    version_ids: Sequence[UUID],
    finished_at: datetime,
) -> ExternalRun:
    configuration: dict[str, Any] = {
        "mode": report.mode.value,
        "selection": report.selection.value,
        "promptSource": report.prompt_source,
        "routing": {task: route.model_dump(by_alias=True) for task, route in report.model_configuration.items()},
        "measuredCases": suite.measured_cases,
        "skippedCases": suite.skipped_cases,
        "liveSpendMicrosUsd": report.live_spend_micros_usd,
    }
    return ExternalRun(
        suite=suite.name,
        trigger=trigger,
        dataset_version="_".join(sorted(set(suite.dataset_versions.values()))),
        prompt_version_ids=list(version_ids),
        model_configuration=configuration,
        scores=dict(suite.metrics),
        passed=suite.status == "passed",
        started_at=report.started_at,
        finished_at=finished_at,
        error_code=CASE_ERROR_CODE if suite.status == "errored" else None,
    )


async def record_report(settings: Settings, report: RunReport, trigger: str, version_ids: Sequence[UUID]) -> list[UUID]:
    runs = [
        run_for(suite, report, TRIGGERS[trigger], version_ids, report.finished_at)
        for suite in report.suites
        if suite.status != "skipped"
    ]
    database = Database(create_engine(settings.database, application_name=APPLICATION_NAME))
    recorded: list[UUID] = []
    try:
        for run in runs:
            async with database.transaction() as session:
                recorded.append(await record_external_run(session, run))
    except Exception as error:
        raise RecordingError(f"the results could not be recorded ({type(error).__name__})") from error
    finally:
        await database.dispose()
    return recorded
