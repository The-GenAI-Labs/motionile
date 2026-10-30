from uuid import UUID

import pytest
from sqlalchemy import text
from tests.integration.pipeline.support import PipelineEnv

from motionile.engine.ai.llm.fake import FakeScript
from motionile.engine.ai.llm.models import LlmTask
from motionile.modules.generation import ResumeKind

pytestmark = pytest.mark.slow

FUNDS = 1_000
STAGE_ORDER = ["guard", "context", "plan", "critique", "approval", "voice", "scenes", "compose", "validate"]


async def started_stages(env: PipelineEnv, job_id: UUID) -> list[str]:
    async with env.generation.database.transaction() as session:
        rows = await session.execute(
            text("SELECT payload->>'stage' FROM job_events WHERE job_id = :job AND type = 'stage.started' ORDER BY id"),
            {"job": job_id},
        )
        return [row[0] for row in rows]


async def completed_job(env: PipelineEnv, **options: object) -> UUID:
    await env.fund(FUNDS)
    job_id = await env.run_to_end(**options)
    job = await env.job(job_id)
    assert job["status"] == "completed", (job["status"], job["errorCode"], job["errorMessage"])
    return job_id


async def test_a_job_without_review_runs_every_stage_and_charges_the_final_duration(pipeline_env: PipelineEnv) -> None:
    env = pipeline_env

    job_id = await completed_job(env)

    job = await env.job(job_id)
    assert job["fallbackSceneIds"] == []
    assert 0 < job["creditsCharged"] <= job["creditsReserved"]
    assert await env.generation.wallet(env.generation.primary_id) == (FUNDS - job["creditsCharged"], 0)
    stages = await started_stages(env, job_id)
    assert [stage for stage in stages if stage in STAGE_ORDER][: len(STAGE_ORDER)] == STAGE_ORDER
    assert stages[-2:] == ["render", "finalize"]
    types = await env.event_types(job_id)
    assert types[0] == "job.created"
    assert types[-1] == "job.completed"
    assert {"storyboard.ready", "scene.voiced", "scene.generated", "validation.completed", "review.completed"} <= set(
        types
    )
    renditions = await env.generation.primary.get(f"/v1/renders/{job['renderId']}/renditions")
    assert renditions.status_code == 200, renditions.text
    assert [item["status"] for item in renditions.json()["items"]] == ["ready"]


async def test_the_composition_checks_leave_both_reports_on_the_job_and_reach_the_vision_model(
    pipeline_env: PipelineEnv,
) -> None:
    env = pipeline_env

    job_id = await completed_job(env)

    reports = await env.generation.scalar("SELECT reports FROM jobs WHERE id = :job", job=job_id)
    assert reports["validation"]["valid"] is True
    assert reports["review"]["issues"] == []
    assert LlmTask.VISION_REVIEW in env.llm_calls


async def test_usage_is_recorded_for_the_model_and_the_voice(pipeline_env: PipelineEnv) -> None:
    env = pipeline_env

    job_id = await completed_job(env)

    assert await env.usage_rows(job_id, "plan") >= 1
    assert await env.usage_rows(job_id, "tts") >= 1
    assert (
        await env.generation.scalar("SELECT coalesce(sum(render_ms), 0) FROM usage_records WHERE job_id = :j", j=job_id)
        > 0
    )


async def test_a_job_with_review_waits_for_the_approval_and_finishes_after_it(pipeline_env: PipelineEnv) -> None:
    env = pipeline_env
    await env.fund(FUNDS)
    job_id = await env.start(reviewStoryboard=True)

    await env.runner().run(job_id)

    assert (await env.job(job_id))["status"] == "awaiting_approval"
    assert env.dispatched_renders == []
    storyboard = await env.generation.primary.get(f"/v1/jobs/{job_id}/storyboard")
    assert storyboard.status_code == 200, storyboard.text
    approved = await env.generation.post(
        env.generation.primary, f"/v1/jobs/{job_id}/approve", {"expectedVersion": storyboard.json()["version"]}
    )
    assert approved.status_code == 202, approved.text
    assert env.generation.dispatch.resumes == [(job_id, ResumeKind.APPROVE, None)]

    await env.runner().resume(job_id, ResumeKind.APPROVE, None)

    assert (await env.job(job_id))["status"] == "completed"
    assert "approval.granted" in await env.event_types(job_id)


async def test_a_new_runner_resumes_the_same_thread_without_repeating_paid_calls(pipeline_env: PipelineEnv) -> None:
    env = pipeline_env
    await env.fund(FUNDS)
    job_id = await env.start(reviewStoryboard=True)
    await env.runner().run(job_id)
    plans = await env.usage_rows(job_id, "plan")
    storyboard = await env.generation.primary.get(f"/v1/jobs/{job_id}/storyboard")
    await env.generation.post(
        env.generation.primary, f"/v1/jobs/{job_id}/approve", {"expectedVersion": storyboard.json()["version"]}
    )
    env.llm_calls.clear()

    await env.runner().resume(job_id, ResumeKind.APPROVE, None)

    assert LlmTask.PLAN not in env.llm_calls
    assert LlmTask.CRITIQUE not in env.llm_calls
    assert await env.usage_rows(job_id, "plan") == plans
    threads = await env.generation.scalar(
        "SELECT count(DISTINCT thread_id) FROM langgraph.checkpoints WHERE thread_id = :thread", thread=str(job_id)
    )
    assert threads == 1
    assert (await env.job(job_id))["status"] == "completed"


async def test_regenerating_returns_to_the_review_with_a_second_version(pipeline_env: PipelineEnv) -> None:
    env = pipeline_env
    await env.fund(FUNDS)
    job_id = await env.start(reviewStoryboard=True)
    await env.runner().run(job_id)

    regenerated = await env.generation.post(
        env.generation.primary, f"/v1/jobs/{job_id}/storyboard/regenerate", {"instructions": "Use a simpler example"}
    )
    assert regenerated.status_code == 202, regenerated.text
    await env.runner().resume(job_id, ResumeKind.REGENERATE, "Use a simpler example")

    assert (await env.job(job_id))["status"] == "awaiting_approval"
    storyboard = await env.generation.primary.get(f"/v1/jobs/{job_id}/storyboard")
    assert storyboard.json()["version"] == 2
    assert storyboard.json()["origin"] == "regeneration"


async def test_a_scene_that_cannot_be_repaired_falls_back_and_the_video_still_completes(
    pipeline_env: PipelineEnv,
) -> None:
    env = pipeline_env
    env.script = FakeScript.for_scene("example", ["broken-syntax"])

    job_id = await completed_job(env)

    job = await env.job(job_id)
    assert job["fallbackSceneIds"] == ["example"]
    row = await env.generation.row(
        "SELECT s.repair_attempts, s.is_fallback, jsonb_array_length(s.attempt_log) FROM scenes s "
        "JOIN storyboards b ON b.id = s.storyboard_id WHERE b.job_id = :job AND s.scene_key = 'example'",
        job=job_id,
    )
    assert row is not None
    assert row[0] == 2
    assert row[1] is True
    assert row[2] >= 3
    types = await env.event_types(job_id)
    assert types.count("scene.repaired") == 2
    assert types.count("scene.fallback") == 1


@pytest.mark.parametrize("task", [LlmTask.PLAN, LlmTask.SCENE, LlmTask.VISION_REVIEW])
async def test_cancelling_during_a_stage_ends_the_job_cancelled_and_returns_every_credit(
    pipeline_env: PipelineEnv, task: LlmTask
) -> None:
    env = pipeline_env
    await env.fund(FUNDS)
    job_id = await env.start()

    async def cancel() -> None:
        await env.cancel(job_id)

    env.before[task] = cancel

    await env.runner().run(job_id)

    job = await env.job(job_id)
    assert job["status"] == "cancelled"
    assert job["completedAt"] is not None
    assert await env.generation.wallet(env.generation.primary_id) == (FUNDS, 0)
    types = await env.event_types(job_id)
    assert types[-1] == "job.cancelled"
    assert "job.completed" not in types
    assert env.dispatched_renders == []


async def test_cancelling_a_waiting_job_is_immediate_and_a_late_resume_changes_nothing(
    pipeline_env: PipelineEnv,
) -> None:
    env = pipeline_env
    await env.fund(FUNDS)
    job_id = await env.start(reviewStoryboard=True)
    await env.runner().run(job_id)

    await env.cancel(job_id)
    await env.runner().resume(job_id, ResumeKind.APPROVE, None)

    assert (await env.job(job_id))["status"] == "cancelled"
    assert await env.generation.wallet(env.generation.primary_id) == (FUNDS, 0)


async def test_a_revision_reuses_the_cached_narration_of_unchanged_scenes(pipeline_env: PipelineEnv) -> None:
    env = pipeline_env
    parent_id = await completed_job(env)
    assert await env.usage_rows(parent_id, "tts") >= 1

    revised = await env.generation.post(
        env.generation.primary, f"/v1/jobs/{parent_id}/revise", {"instructions": "Keep it the same"}, key=True
    )
    assert revised.status_code == 202, revised.text
    child_id = UUID(revised.json()["id"])
    await env.runner().run(child_id)

    child = await env.job(child_id)
    assert child["status"] == "completed", (child["errorCode"], child["errorMessage"])
    assert child["parentJobId"] == str(parent_id)
    assert await env.usage_rows(child_id, "tts") == 0
    assert await env.usage_rows(child_id, "plan") >= 1
