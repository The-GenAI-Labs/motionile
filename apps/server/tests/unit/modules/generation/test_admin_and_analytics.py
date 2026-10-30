from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.fakes.generation import EPOCH, GenerationWorld, RecordingAudit
from tests.unit.modules.generation.support import storyboard_content

from motionile.core.clock import FrozenClock
from motionile.core.ids import new_id
from motionile.core.pagination import Cursor
from motionile.engine.ai.job_options import JobStatus
from motionile.modules.audit import ActorType
from motionile.modules.generation.admin_repository import AdminJobFilter, CostTotals, UsageTotals
from motionile.modules.generation.admin_schemas import AnalyticsQuery
from motionile.modules.generation.admin_service import AdminJobsService, TraceSettings, public_reports
from motionile.modules.generation.analytics import (
    MAX_RANGE_DAYS,
    AnalyticsRangeError,
    OutcomeCounts,
    SceneTotals,
    StageAverage,
    fallback_rate,
    overall_success_rate,
    ratio,
    repair_rate,
    resolve_range,
    stage_views,
    zero_filled_days,
)
from motionile.modules.generation.exceptions import JobNotFoundError
from motionile.modules.generation.models import Job, JobEvent, Scene, Storyboard

TODAY = date(2026, 10, 25)
NOW = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)


def test_the_default_range_is_the_last_thirty_days_ending_today() -> None:
    assert resolve_range(None, None, TODAY) == (date(2026, 9, 26), TODAY)


def test_an_explicit_range_is_kept_and_a_single_day_is_allowed() -> None:
    assert resolve_range(date(2026, 10, 1), date(2026, 10, 5), TODAY) == (date(2026, 10, 1), date(2026, 10, 5))
    assert resolve_range(TODAY, TODAY, TODAY) == (TODAY, TODAY)


def test_a_range_of_366_days_is_the_maximum() -> None:
    end = date(2026, 10, 25)
    start = end - timedelta(days=MAX_RANGE_DAYS - 1)

    assert resolve_range(start, end, TODAY) == (start, end)
    with pytest.raises(AnalyticsRangeError):
        resolve_range(start - timedelta(days=1), end, TODAY)


def test_a_backwards_range_is_refused() -> None:
    with pytest.raises(AnalyticsRangeError):
        resolve_range(date(2026, 10, 5), date(2026, 10, 1), TODAY)


def test_days_without_jobs_are_filled_with_zeros_and_no_rate() -> None:
    counts: OutcomeCounts = {
        (date(2026, 10, 2), "completed"): 3,
        (date(2026, 10, 2), "failed"): 1,
        (date(2026, 10, 2), "cancelled"): 2,
        (date(2026, 10, 4), "failed"): 2,
    }

    days = zero_filled_days(date(2026, 10, 1), date(2026, 10, 5), counts)

    assert [day.day.day for day in days] == [1, 2, 3, 4, 5]
    assert [(day.completed, day.failed, day.cancelled) for day in days] == [
        (0, 0, 0),
        (3, 1, 2),
        (0, 0, 0),
        (0, 2, 0),
        (0, 0, 0),
    ]
    assert [day.success_rate for day in days] == [None, 0.75, None, 0.0, None]
    assert overall_success_rate(days) == 0.5


def test_a_full_year_range_gets_one_entry_per_day() -> None:
    start = date(2025, 10, 25)

    assert len(zero_filled_days(start, date(2026, 10, 25), {})) == MAX_RANGE_DAYS


def test_ratios_round_and_guard_against_empty_denominators() -> None:
    assert ratio(1, 3) == 0.3333
    assert ratio(0, 0) is None
    assert repair_rate(SceneTotals(scenes=8, repaired=2, fallbacks=1)) == 0.25
    assert fallback_rate(SceneTotals(scenes=8, repaired=2, fallbacks=1)) == 0.125
    assert repair_rate(SceneTotals(0, 0, 0)) is None
    assert overall_success_rate([]) is None


def test_stage_averages_are_reported_in_seconds_sorted_by_stage() -> None:
    views = stage_views([StageAverage("scenes", 4_500.0, 7), StageAverage("plan", 1_250.5, 3)])

    assert [(view.stage, view.average_seconds, view.samples) for view in views] == [
        ("plan", 1.2505, 3),
        ("scenes", 4.5, 7),
    ]


def test_review_messages_are_removed_from_the_public_reports() -> None:
    reports = {
        "validation": {"valid": False, "issues": [{"code": "text_overflow", "message": "Text is 24px"}]},
        "review": {
            "issues": [{"code": "review_legibility", "sceneId": "intro", "message": "The model said this"}],
            "skipped": [{"sceneId": "x", "code": "llm_unavailable"}],
        },
    }

    cleaned = public_reports(reports)

    assert cleaned["validation"] == reports["validation"]
    assert cleaned["review"] == {
        "issues": [{"code": "review_legibility", "sceneId": "intro"}],
        "skipped": [{"sceneId": "x", "code": "llm_unavailable"}],
    }
    assert "The model said this" not in str(cleaned)
    assert "The model said this" in str(reports)


def test_reports_without_a_review_pass_through() -> None:
    assert public_reports({}) == {}
    assert public_reports({"validation": {"valid": True}}) == {"validation": {"valid": True}}


class FakeAdminStore:
    def __init__(self, world: GenerationWorld) -> None:
        self.world = world
        self.event_rows: list[JobEvent] = []
        self.totals = UsageTotals(1_000, 500, 1_200, 90_000, 42_000, 7)
        self.outcome_counts: OutcomeCounts = {}
        self.ranges: list[tuple[datetime, datetime]] = []

    async def page(self, job_filter: AdminJobFilter, cursor: Cursor | None, limit: int) -> list[Job]:
        rows = sorted(self.world.jobs.values(), key=lambda job: (job.created_at, job.id), reverse=True)
        if job_filter.status is not None:
            rows = [job for job in rows if job.status == job_filter.status.value]
        if job_filter.user_id is not None:
            rows = [job for job in rows if job.user_id == job_filter.user_id]
        if cursor is not None:
            rows = [job for job in rows if (job.created_at, job.id) < (cursor.created_at, cursor.id)]
        return rows[: limit + 1]

    async def job(self, job_id: UUID) -> Job | None:
        return self.world.jobs.get(job_id)

    async def events(self, job_id: UUID) -> list[JobEvent]:
        return [event for event in self.event_rows if event.job_id == job_id]

    async def storyboards(self, job_id: UUID) -> list[Storyboard]:
        return sorted((row for row in self.world.storyboards if row.job_id == job_id), key=lambda row: row.version)

    async def scenes(self, storyboard_id: UUID) -> list[Scene]:
        return [scene for scene in self.world.scenes if scene.storyboard_id == storyboard_id]

    async def usage(self, job_id: UUID) -> UsageTotals:
        del job_id
        return self.totals

    async def outcomes(self, start: datetime, end: datetime) -> OutcomeCounts:
        self.ranges.append((start, end))
        return self.outcome_counts

    async def stage_averages(self, start: datetime, end: datetime) -> list[StageAverage]:
        del start, end
        return [StageAverage("plan", 2_000.0, 4)]

    async def scene_totals(self, start: datetime, end: datetime) -> SceneTotals:
        del start, end
        return SceneTotals(10, 3, 1)

    async def cost_totals(self, start: datetime, end: datetime) -> CostTotals:
        del start, end
        return CostTotals(31_000.0, 82.5)


class Fixture:
    def __init__(self, *, tracing: bool = False) -> None:
        self.world = GenerationWorld()
        self.store = FakeAdminStore(self.world)
        self.session = AsyncSession()
        self.audit = RecordingAudit()
        self.admin_id = new_id()
        self.service = AdminJobsService(
            FrozenClock(NOW),
            TraceSettings(tracing, "https://langfuse.example", "proj-1"),
            lambda _session: self.store,
            self.audit,
        )


async def test_the_detail_shows_versions_the_approved_content_scenes_cost_and_trace() -> None:
    fixture = Fixture(tracing=True)
    job = fixture.world.add_job(
        new_id(), status="completed", credits_charged=82, reports={"validation": {"valid": True}}
    )
    fixture.world.add_storyboard(job, storyboard_content(), origin="planner")
    approved = fixture.world.add_storyboard(job, storyboard_content(title="Approved"), origin="user")
    approved.approved_at = EPOCH
    fixture.world.add_storyboard(job, storyboard_content(title="Later draft"), origin="regeneration")
    fixture.world.add_scene(approved, "scene-0", 0, is_fallback=False)
    fixture.world.add_scene(approved, "scene-1", 1, is_fallback=True)
    fixture.store.event_rows.append(
        JobEvent(
            id=new_id(), job_id=job.id, type="stage.started", stage="plan", payload={"stage": "plan"}, created_at=EPOCH
        )
    )

    detail = await fixture.service.detail(fixture.session, fixture.admin_id, job.id)

    assert [(item.version, item.origin, item.approved) for item in detail.storyboard_versions] == [
        (1, "planner", False),
        (2, "user", True),
        (3, "regeneration", False),
    ]
    assert detail.approved_storyboard is not None
    assert detail.approved_storyboard.title == "Approved"
    assert [(scene.scene_id, scene.is_fallback) for scene in detail.scenes] == [("scene-0", False), ("scene-1", True)]
    assert detail.job.fallback_scene_ids == ["scene-1"]
    assert [(event.type, event.payload) for event in detail.events] == [("stage.started", {"stage": "plan"})]
    assert (detail.cost.cost_micros_usd, detail.cost.render_ms, detail.cost.credits_charged) == (42_000, 90_000, 82)
    assert detail.trace_url is not None
    assert detail.trace_url.startswith("https://langfuse.example/project/proj-1/traces/")
    assert str(job.id) not in detail.trace_url


async def test_the_detail_has_no_trace_link_when_tracing_is_off() -> None:
    fixture = Fixture(tracing=False)
    job = fixture.world.add_job(new_id())

    detail = await fixture.service.detail(fixture.session, fixture.admin_id, job.id)

    assert detail.trace_url is None
    assert detail.approved_storyboard is None
    assert detail.scenes == []


async def test_the_detail_never_carries_prompt_material() -> None:
    fixture = Fixture(tracing=True)
    job = fixture.world.add_job(new_id())

    document = (
        (await fixture.service.detail(fixture.session, fixture.admin_id, job.id)).model_dump_json(by_alias=True).lower()
    )

    for forbidden in ("canary", "system_prompt", "skill_body", "raw_output"):
        assert forbidden not in document


async def test_an_unknown_job_is_not_found() -> None:
    fixture = Fixture()

    with pytest.raises(JobNotFoundError):
        await fixture.service.detail(fixture.session, fixture.admin_id, new_id())


async def test_the_list_is_paged_and_cut_to_the_query_preview() -> None:
    fixture = Fixture()
    for _ in range(3):
        fixture.world.add_job(new_id(), query="q" * 1_500)

    first = await fixture.service.list_jobs(fixture.session, AdminJobFilter(), None, 2)
    second = await fixture.service.list_jobs(fixture.session, AdminJobFilter(), first.next_cursor, 2)

    assert len(first.items) == 2
    assert first.next_cursor is not None
    assert len(second.items) == 1
    assert second.next_cursor is None
    assert all(len(item.query) == 200 for item in first.items)


async def test_the_list_filters_by_status_and_user() -> None:
    fixture = Fixture()
    user = new_id()
    fixture.world.add_job(user, status="failed", error_code="tts_failed")
    fixture.world.add_job(user, status="completed")
    fixture.world.add_job(new_id(), status="failed", error_code="tts_failed")

    result = await fixture.service.list_jobs(
        fixture.session, AdminJobFilter(status=JobStatus.FAILED, user_id=user), None, 10
    )

    assert [(item.user_id, item.status) for item in result.items] == [(user, JobStatus.FAILED)]


async def test_analytics_combines_the_zero_filled_days_with_the_rates() -> None:
    fixture = Fixture()
    fixture.store.outcome_counts = {(date(2026, 10, 24), "completed"): 4, (date(2026, 10, 24), "failed"): 1}

    view = await fixture.service.analytics(
        fixture.session, AnalyticsQuery(date_from=date(2026, 10, 23), date_to=date(2026, 10, 25))
    )

    assert [(day.day.day, day.completed) for day in view.days] == [(23, 0), (24, 4), (25, 0)]
    assert view.success_rate == 0.8
    assert (view.scenes, view.repair_rate, view.fallback_rate) == (10, 0.3, 0.1)
    assert (view.average_cost_micros_usd, view.average_credits_charged) == (31_000.0, 82.5)
    assert [(stage.stage, stage.average_seconds) for stage in view.stages] == [("plan", 2.0)]
    assert fixture.store.ranges == [(datetime(2026, 10, 23, tzinfo=UTC), datetime(2026, 10, 26, tzinfo=UTC))]


async def test_analytics_defaults_to_the_thirty_days_ending_today() -> None:
    fixture = Fixture()

    view = await fixture.service.analytics(fixture.session, AnalyticsQuery())

    assert len(view.days) == 30
    assert view.days[-1].day == TODAY
    assert view.success_rate is None


async def test_analytics_refuses_a_range_over_a_year() -> None:
    fixture = Fixture()

    with pytest.raises(AnalyticsRangeError):
        await fixture.service.analytics(
            fixture.session, AnalyticsQuery(date_from=date(2025, 1, 1), date_to=date(2026, 10, 25))
        )


async def test_an_admin_read_of_a_job_is_audited_with_the_admin_as_actor() -> None:
    fixture = Fixture()
    owner = new_id()
    job = fixture.world.add_job(owner)

    await fixture.service.detail(fixture.session, fixture.admin_id, job.id)

    [event] = fixture.audit.events
    assert (event.action, event.actor_type, event.actor_user_id) == (
        "job.admin_viewed",
        ActorType.ADMIN,
        fixture.admin_id,
    )
    assert (event.target_type, event.target_id) == ("job", str(job.id))
    assert event.metadata == {"ownerId": str(owner)}


async def test_reading_a_job_that_does_not_exist_writes_no_audit_entry() -> None:
    fixture = Fixture()

    with pytest.raises(JobNotFoundError):
        await fixture.service.detail(fixture.session, fixture.admin_id, new_id())

    assert fixture.audit.events == []
