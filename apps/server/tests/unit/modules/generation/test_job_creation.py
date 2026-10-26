from typing import Any

import pytest
from pydantic import ValidationError
from tests.unit.modules.generation.support import Harness

from motionile.core.ids import new_id
from motionile.engine.ai.job_options import JobStatus
from motionile.modules.generation import (
    AspectNotAllowedError,
    EstimateRequest,
    JobCreateRequest,
    JobInsufficientCreditsError,
    JobOptionsInvalidError,
    LanguageNotSupportedError,
    StyleNotFoundError,
    TooManyActiveJobsError,
    TopicNotFoundError,
)
from motionile.modules.generation.ports import UserPreferences
from motionile.modules.generation.schemas import JobOptionsRequest
from motionile.modules.media import MusicTrackUnavailableError


def options(**overrides: Any) -> EstimateRequest:
    return EstimateRequest(options=JobOptionsRequest(duration_seconds=60, **overrides))


async def test_an_estimate_reports_the_formula_and_the_balance(harness: Harness) -> None:
    await harness.fund(500)

    view = await harness.service.estimate(harness.session, harness.user_id, options(aspects=["16:9", "9:16"]))

    assert view.credits == 196
    assert view.available_credits == 500
    assert view.affordable
    assert (view.seconds, view.aspect_count, view.cloned_voice) == (60, 2, False)
    assert view.parameters.base_credits == 20


async def test_an_estimate_beyond_the_balance_is_not_affordable(harness: Harness) -> None:
    await harness.fund(100)

    view = await harness.service.estimate(harness.session, harness.user_id, options())

    assert (view.credits, view.available_credits, view.affordable) == (140, 100, False)


async def test_a_cloned_voice_adds_the_premium_to_the_estimate(harness: Harness) -> None:
    voice_id = new_id()
    harness.voices.cloned.add(voice_id)

    view = await harness.service.estimate(harness.session, harness.user_id, options(voice_id=voice_id))

    assert view.credits == 150
    assert view.cloned_voice


async def test_creating_a_job_reserves_credits_and_dispatches_it(harness: Harness) -> None:
    await harness.fund(500)

    view = await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())

    assert view.status is JobStatus.QUEUED
    assert (view.credits_estimated, view.credits_reserved, view.credits_charged) == (140, 140, None)
    assert view.query == "How does TCP work?"
    assert view.source == "query"
    assert harness.wallet() == (500, 140)
    assert harness.dispatch.runs == [view.id]
    assert harness.world.event_types(view.id) == ["job.created"]
    assert harness.audit.actions == ["job.created"]
    assert harness.world.locked_creations == [harness.user_id]
    reservation = await harness.credits.active_reservation(harness.session, harness.user_id, "job", view.id)
    assert reservation is not None
    assert reservation.amount == 140


async def test_a_repeated_idempotency_key_returns_the_same_job_without_charging_twice(harness: Harness) -> None:
    await harness.fund(500)
    key = harness.key()

    first = await harness.service.create(harness.session, harness.user_id, harness.request(), key)
    second = await harness.service.create(harness.session, harness.user_id, harness.request(), key)

    assert first.id == second.id
    assert len(harness.world.jobs) == 1
    assert harness.wallet() == (500, 140)
    assert harness.dispatch.runs == [first.id]


async def test_the_same_key_from_another_user_creates_another_job(harness: Harness) -> None:
    await harness.fund(500)
    await harness.fund(500, harness.other_id)
    key = harness.key()

    first = await harness.service.create(harness.session, harness.user_id, harness.request(), key)
    second = await harness.service.create(harness.session, harness.other_id, harness.request(), key)

    assert first.id != second.id


async def test_insufficient_credits_report_the_shortfall_and_create_nothing_reserved(harness: Harness) -> None:
    await harness.fund(100)

    with pytest.raises(JobInsufficientCreditsError) as caught:
        await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())

    assert caught.value.status_code == 402
    assert caught.value.code == "insufficient_credits"
    assert caught.value.extensions == {"available": 100, "required": 140, "shortfall": 40}
    assert harness.wallet() == (100, 0)


async def test_a_user_without_a_wallet_cannot_start_a_job(harness: Harness) -> None:
    with pytest.raises(JobInsufficientCreditsError) as caught:
        await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())

    assert caught.value.extensions["shortfall"] == 140


async def test_active_jobs_are_capped_per_user(harness: Harness) -> None:
    await harness.fund(1_000)
    await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())
    await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())

    with pytest.raises(TooManyActiveJobsError) as caught:
        await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())

    assert caught.value.status_code == 409
    assert caught.value.code == "too_many_active_jobs"
    assert caught.value.extensions == {"limit": 2}
    assert harness.wallet() == (1_000, 280)


async def test_finished_jobs_do_not_count_against_the_cap(harness: Harness) -> None:
    await harness.fund(1_000)
    harness.world.add_job(harness.user_id, status="completed")
    harness.world.add_job(harness.user_id, status="failed", error_code="tts_failed")
    harness.world.add_job(harness.user_id, status="cancelled")

    await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())


async def test_the_cap_follows_the_platform_setting(harness: Harness) -> None:
    await harness.fund(1_000)
    harness.reader.values["jobs.max_active_per_user"] = 1
    await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())

    with pytest.raises(TooManyActiveJobsError):
        await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())


async def test_a_catalog_topic_becomes_the_query(harness: Harness) -> None:
    await harness.fund(500)
    topic = harness.topics.add("How DNS works")
    request = JobCreateRequest(topic_id=topic.id, options=JobOptionsRequest(duration_seconds=30))

    view = await harness.service.create(harness.session, harness.user_id, request, harness.key())

    assert (view.source, view.topic_id, view.query) == ("catalog", topic.id, "How DNS works")


async def test_an_unknown_or_unpublished_topic_is_rejected(harness: Harness) -> None:
    await harness.fund(500)
    request = JobCreateRequest(topic_id=new_id(), options=JobOptionsRequest(duration_seconds=30))

    with pytest.raises(TopicNotFoundError):
        await harness.service.create(harness.session, harness.user_id, request, harness.key())

    assert harness.wallet() == (500, 0)


def test_a_request_needs_exactly_one_source() -> None:
    both = {"topicId": str(new_id()), "query": "x", "options": {"durationSeconds": 30}}
    neither = {"options": {"durationSeconds": 30}}

    for payload in (both, neither):
        with pytest.raises(ValidationError, match="exactly one"):
            JobCreateRequest.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"durationSeconds": 9},
        {"durationSeconds": 121},
        {"durationSeconds": 30, "aspects": []},
        {"durationSeconds": 30, "aspects": ["16:9", "16:9"]},
        {"durationSeconds": 30, "aspects": ["4:3"]},
        {"durationSeconds": 30, "subtitles": False, "burnInSubtitles": True},
        {"durationSeconds": 30, "unknown": 1},
        {"durationSeconds": 30, "style": "Not A Slug"},
    ],
)
def test_option_requests_are_bounded(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        JobOptionsRequest.model_validate(payload)


def test_a_query_is_trimmed_and_bounded() -> None:
    assert JobCreateRequest.model_validate({"query": "  hi  ", "options": {"durationSeconds": 30}}).query == "hi"
    for query in ("", "   ", "x" * 2_001):
        with pytest.raises(ValidationError):
            JobCreateRequest.model_validate({"query": query, "options": {"durationSeconds": 30}})


async def test_the_style_comes_from_the_option_then_the_preference_then_the_default(harness: Harness) -> None:
    await harness.fund(1_000)
    harness.preferences.preferences = UserPreferences(default_style="whiteboard")

    explicit = await harness.service.create(
        harness.session, harness.user_id, harness.request(style="minimal-dark"), harness.key()
    )
    preferred = await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())
    harness.preferences.preferences = UserPreferences()
    harness.world.jobs[explicit.id].status = "completed"
    harness.world.jobs[preferred.id].status = "completed"
    fallback = await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())

    assert explicit.options.style == "minimal-dark"
    assert preferred.options.style == "whiteboard"
    assert fallback.options.style == "minimal-dark"


async def test_an_unknown_style_is_rejected(harness: Harness) -> None:
    await harness.fund(500)

    with pytest.raises(StyleNotFoundError):
        await harness.service.create(harness.session, harness.user_id, harness.request(style="nope"), harness.key())


async def test_the_language_follows_the_preference_and_must_be_allowed(harness: Harness) -> None:
    await harness.fund(1_000)
    harness.preferences.preferences = UserPreferences(language="hi-IN")

    view = await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())

    assert view.options.language == "hi-IN"
    with pytest.raises(LanguageNotSupportedError):
        await harness.service.create(harness.session, harness.user_id, harness.request(language="fr"), harness.key())


async def test_aspects_must_be_allowed_and_default_to_the_preference(harness: Harness) -> None:
    await harness.fund(1_000)
    harness.preferences.preferences = UserPreferences(default_aspect="9:16")
    view = await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())
    harness.reader.values["preferences.aspects"] = ["16:9"]

    assert view.options.aspects == ["9:16"]
    with pytest.raises(AspectNotAllowedError):
        await harness.service.create(harness.session, harness.user_id, harness.request(aspects=["1:1"]), harness.key())


async def test_the_voice_comes_from_the_option_then_the_preference_then_the_built_in_default(
    harness: Harness,
) -> None:
    await harness.fund(1_000)
    chosen, preferred = new_id(), new_id()
    harness.preferences.preferences = UserPreferences(default_voice_id=preferred)

    explicit = await harness.service.create(
        harness.session, harness.user_id, harness.request(voice_id=chosen), harness.key()
    )
    harness.world.jobs[explicit.id].status = "completed"
    from_preference = await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())
    harness.world.jobs[from_preference.id].status = "completed"
    harness.voices.unavailable.add(preferred)
    fallback = await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())

    assert explicit.options.voice_id == chosen
    assert from_preference.options.voice_id == preferred
    assert fallback.options.voice_id == harness.voices.default.voice_id


async def test_a_cloned_voice_reserves_the_premium(harness: Harness) -> None:
    await harness.fund(500)
    voice_id = new_id()
    harness.voices.cloned.add(voice_id)

    view = await harness.service.create(
        harness.session, harness.user_id, harness.request(voice_id=voice_id), harness.key()
    )

    assert (view.credits_reserved, view.options.voice_is_cloned) == (150, True)


async def test_music_must_be_an_active_track(harness: Harness) -> None:
    await harness.fund(500)
    track = new_id()

    with pytest.raises(MusicTrackUnavailableError):
        await harness.service.create(
            harness.session, harness.user_id, harness.request(music_track_id=track), harness.key()
        )

    harness.music.active.add(track)
    view = await harness.service.create(
        harness.session, harness.user_id, harness.request(music_track_id=track), harness.key()
    )
    assert view.options.music_track_id == track


async def test_captions_follow_the_preference(harness: Harness) -> None:
    await harness.fund(500)
    harness.preferences.preferences = UserPreferences(captions_enabled=False)

    view = await harness.service.create(harness.session, harness.user_id, harness.request(), harness.key())

    assert not view.options.subtitles


async def test_burning_in_captions_the_preference_turned_off_is_invalid(harness: Harness) -> None:
    await harness.fund(500)
    harness.preferences.preferences = UserPreferences(captions_enabled=False)

    with pytest.raises(JobOptionsInvalidError):
        await harness.service.create(
            harness.session, harness.user_id, harness.request(burn_in_subtitles=True), harness.key()
        )
