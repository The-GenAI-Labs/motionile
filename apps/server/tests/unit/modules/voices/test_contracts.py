from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.core.ratelimit.policies import HOUR, RateLimitScope, resolve_policies
from motionile.core.tasks.registry import TASK_MODULES
from motionile.modules.users import PreferenceGuards, purge_registry
from motionile.modules.users.preference_checks import DefaultVoiceUnavailableError
from motionile.modules.voices.schemas import (
    CloneStartRequest,
    CloneSubmitRequest,
    VoiceListQuery,
    VoiceUpdateRequest,
)


def test_clone_and_upload_policies_limit_each_user_per_hour() -> None:
    policies = resolve_policies({})

    [clone] = policies["voices.clone"].rules
    [upload] = policies["voices.upload"].rules
    assert (clone.limit, clone.window_seconds, clone.scope) == (10, HOUR, RateLimitScope.USER)
    assert (upload.limit, upload.window_seconds, upload.scope) == (60, HOUR, RateLimitScope.USER)


def test_the_voice_tasks_and_hooks_are_registered() -> None:
    assert "motionile.modules.voices.tasks" in TASK_MODULES
    assert "voices" in purge_registry.names()


async def test_the_default_voice_guard_fails_closed_until_a_guard_is_registered() -> None:
    guards = PreferenceGuards()
    session = AsyncSession()
    with pytest.raises(DefaultVoiceUnavailableError) as raised:
        await guards.check_default_voice(session, new_id(), new_id())
    assert raised.value.code == "voice_not_available"

    seen: list[tuple[UUID, UUID]] = []

    async def guard(_: AsyncSession, user_id: UUID, voice_id: UUID) -> None:
        seen.append((user_id, voice_id))

    guards.register_default_voice(guard)
    user_id, voice_id = new_id(), new_id()
    await guards.check_default_voice(session, user_id, voice_id)

    assert seen == [(user_id, voice_id)]
    with pytest.raises(ValueError, match="already registered"):
        guards.register_default_voice(guard)


def test_consent_acceptance_must_be_true_and_the_body_is_closed() -> None:
    assert CloneStartRequest.model_validate({"statementVersion": "v1", "accepted": True}).accepted is True
    for body in (
        {"statementVersion": "v1", "accepted": False},
        {"statementVersion": "v1"},
        {"statementVersion": "", "accepted": True},
        {"statementVersion": "v1", "accepted": True, "extra": 1},
    ):
        with pytest.raises(ValidationError):
            CloneStartRequest.model_validate(body)


def test_submit_bounds_the_name_and_requires_a_bcp47_language() -> None:
    assert CloneSubmitRequest.model_validate({"name": "  Me  ", "language": "en-IN"}).name == "Me"
    for body in (
        {"name": "", "language": "en"},
        {"name": "x" * 81, "language": "en"},
        {"name": "Me", "language": "English"},
        {"name": "Me", "language": "en", "extra": True},
    ):
        with pytest.raises(ValidationError):
            CloneSubmitRequest.model_validate(body)


def test_curation_accepts_only_ready_or_disabled_and_at_least_one_field() -> None:
    assert VoiceUpdateRequest.model_validate({"status": "ready"}).model_fields_set == {"status"}
    for body in ({}, {"status": "pending"}, {"name": None}, {"tags": ["Bad Tag!"]}, {"tags": ["a"] * 11}):
        with pytest.raises(ValidationError):
            VoiceUpdateRequest.model_validate(body)


def test_the_list_query_is_bounded() -> None:
    assert VoiceListQuery.model_validate({"language": "en", "kind": "cloned", "limit": 5}).limit == 5
    for body in ({"limit": 0}, {"limit": 101}, {"kind": "other"}, {"language": "EN"}):
        with pytest.raises(ValidationError):
            VoiceListQuery.model_validate(body)
