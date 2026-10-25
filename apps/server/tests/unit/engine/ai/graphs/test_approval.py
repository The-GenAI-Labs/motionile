import pytest
from tests.fakes.pipeline import make_job
from tests.unit.engine.ai.graphs.support import SCENE_COUNT_FOR_THIRTY_SECONDS, Harness, build_harness

from motionile.engine.ai.graphs.resume import ApprovalKind, ApprovalResume
from motionile.engine.ai.graphs.run import RunOutcome
from motionile.engine.ai.guardrails.policy import POLICY_MESSAGES, PolicyCode
from motionile.engine.ai.job_options import JobStatus
from motionile.engine.ai.llm.fake import FakeScript
from motionile.engine.ai.llm.models import LlmTask
from motionile.engine.ai.ports import StoryboardOrigin


def reviewed_harness(script: FakeScript | None = None) -> Harness:
    return build_harness(job=make_job(duration_seconds=30, review_storyboard=True), script=script)


async def test_a_job_with_review_stops_at_the_interrupt_before_any_spend() -> None:
    harness = reviewed_harness()

    outcome = await harness.run()

    assert outcome is RunOutcome.AWAITING_APPROVAL
    assert harness.store.job.status is JobStatus.AWAITING_APPROVAL
    assert harness.store.stage_names[-1] == "approval"
    assert harness.narrator.calls == []
    assert harness.renders.started == []
    (requested,) = harness.store.events_of("approval.requested")
    assert requested.payload["version"] == 1
    assert requested.payload["expiresAt"] == "2026-10-31T12:00:00+00:00"
    assert harness.store.approved_ids == set()


async def test_approving_continues_to_the_end_and_records_the_grant() -> None:
    harness = reviewed_harness()
    await harness.run()

    outcome = await harness.run(ApprovalResume.approve())

    assert outcome is RunOutcome.FINISHED
    assert harness.store.job.status is JobStatus.COMPLETED
    assert harness.store.storyboards[0].id in harness.store.approved_ids
    (granted,) = harness.store.events_of("approval.granted")
    assert granted.payload == {"version": 1}
    assert harness.tasks[LlmTask.PLAN] == 1
    assert harness.tasks[LlmTask.SCENE] == SCENE_COUNT_FOR_THIRTY_SECONDS


async def test_a_restarted_worker_resumes_the_same_thread_without_repeating_paid_calls() -> None:
    first = reviewed_harness()
    await first.run()
    restarted = first.restarted()

    outcome = await restarted.run(ApprovalResume.approve())

    assert outcome is RunOutcome.FINISHED
    assert restarted.llm is not first.llm
    assert restarted.tasks[LlmTask.PLAN] == 0
    assert restarted.tasks[LlmTask.CRITIQUE] == 0
    assert restarted.tasks[LlmTask.SCENE] == SCENE_COUNT_FOR_THIRTY_SECONDS
    assert first.store.storyboards[0].id in first.store.approved_ids


async def test_a_run_without_a_resume_value_stays_at_the_interrupt() -> None:
    harness = reviewed_harness()
    await harness.run()
    guard_calls = harness.tasks[LlmTask.GUARD]

    outcome = await harness.restarted().run()

    assert outcome is RunOutcome.AWAITING_APPROVAL
    assert harness.tasks[LlmTask.GUARD] == guard_calls
    assert harness.narrator.calls == []


async def test_a_job_without_review_never_requests_approval() -> None:
    harness = build_harness()

    await harness.run()

    assert "approval.requested" not in harness.store.event_types
    assert "approval.granted" not in harness.store.event_types
    assert harness.store.storyboards[0].id in harness.store.approved_ids


async def test_regenerating_returns_to_the_planner_with_the_instructions_as_data() -> None:
    harness = reviewed_harness()
    await harness.run()

    outcome = await harness.run(ApprovalResume.regenerate("Make the opening shorter"))

    assert outcome is RunOutcome.AWAITING_APPROVAL
    assert harness.store.origins == [StoryboardOrigin.PLANNER, StoryboardOrigin.REGENERATION]
    first_plan, second_plan = harness.llm.calls_of(LlmTask.PLAN)
    assert not any("<revision_instructions>" in str(block) for block in first_plan.user_blocks)
    blocks = [str(block) for block in second_plan.user_blocks]
    assert any(block.startswith("<revision_instructions>\nMake the opening shorter") for block in blocks)
    assert any(block.startswith("<previous_attempt>") for block in blocks)
    assert first_plan.context.call_key != second_plan.context.call_key
    assert len(harness.store.events_of("approval.requested")) == 2
    assert harness.store.events_of("approval.requested")[1].payload["version"] == 2
    assert harness.narrator.calls == []


async def test_regenerate_then_approve_voices_the_new_version() -> None:
    harness = reviewed_harness()
    await harness.run()
    await harness.run(ApprovalResume.regenerate())

    outcome = await harness.run(ApprovalResume.approve())

    assert outcome is RunOutcome.FINISHED
    assert harness.store.storyboards[1].id in harness.store.approved_ids
    assert harness.store.storyboards[0].id not in harness.store.approved_ids
    assert harness.tasks[LlmTask.PLAN] == 2


async def test_refused_regeneration_instructions_fail_the_job_with_the_policy_code() -> None:
    script = FakeScript.for_task(LlmTask.GUARD, ["allow", "allow", "refuse-injection"])
    harness = reviewed_harness(script)
    await harness.run()

    outcome = await harness.run(ApprovalResume.regenerate("Make the opening shorter"))

    assert outcome is RunOutcome.FAILED
    assert harness.store.failure == (
        PolicyCode.PROMPT_INJECTION.value,
        POLICY_MESSAGES[PolicyCode.PROMPT_INJECTION],
    )
    assert harness.tasks[LlmTask.PLAN] == 1


async def test_edits_stored_before_the_resume_are_the_text_that_gets_voiced() -> None:
    harness = reviewed_harness()
    await harness.run()
    original = harness.store.storyboards[0].content
    scenes = [original.scenes[0].model_copy(update={"narration": original.scenes[0].narration + " And one more."})]
    edited = original.model_copy(update={"title": "An edited title", "scenes": [*scenes, *original.scenes[1:]]})
    await harness.store.save_storyboard(harness.job_id, edited, StoryboardOrigin.USER)
    guard_calls = harness.tasks[LlmTask.GUARD]

    outcome = await harness.run(ApprovalResume.approve())

    assert outcome is RunOutcome.FINISHED
    assert harness.narrator.calls[0][0].text.endswith("And one more.")
    assert harness.store.storyboards[1].id in harness.store.approved_ids
    assert harness.tasks[LlmTask.GUARD] == guard_calls + 1
    assert harness.tasks[LlmTask.PLAN] == 1


async def test_cancelling_while_waiting_ends_the_job_cancelled_on_resume() -> None:
    harness = reviewed_harness()
    await harness.run()
    harness.store.request_cancel()

    outcome = await harness.run(ApprovalResume.approve())

    assert outcome is RunOutcome.CANCELLED
    assert harness.store.job.status is JobStatus.CANCELLED
    assert harness.narrator.calls == []
    assert harness.store.event_types[-1] == "job.cancelled"


async def test_a_resume_for_a_job_that_already_ended_changes_nothing() -> None:
    harness = reviewed_harness()
    await harness.run()
    await harness.store.finish_cancellation(harness.job_id)

    outcome = await harness.run(ApprovalResume.approve())

    assert outcome is RunOutcome.CANCELLED
    assert harness.narrator.calls == []


def test_an_approval_cannot_carry_instructions() -> None:
    with pytest.raises(ValueError, match="approval carries no instructions"):
        ApprovalResume(kind=ApprovalKind.APPROVE, instructions="more")


def test_resume_values_round_trip_through_plain_json() -> None:
    resume = ApprovalResume.regenerate("Shorter")

    assert ApprovalResume.model_validate(resume.model_dump(mode="json")) == resume
    assert resume.model_dump(mode="json") == {"kind": "regenerate", "instructions": "Shorter"}
