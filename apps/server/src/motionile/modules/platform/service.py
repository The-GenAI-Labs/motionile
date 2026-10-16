import hashlib
import json
from datetime import timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.db import after_commit
from motionile.core.errors import ConflictError, NotFoundError, ValidationAppError
from motionile.core.redis import RedisStore
from motionile.core.security.rbac import Principal
from motionile.modules.access import resolve_access
from motionile.modules.platform.models import FeatureFlag
from motionile.modules.platform.registry import SETTINGS, SettingValue, validate_setting
from motionile.modules.platform.repository import PlatformRepository
from motionile.modules.platform.schemas import (
    EvaluatedFlagsResponse,
    FeatureFlagResponse,
    FeatureFlagUpdateRequest,
    FeatureFlagWriteRequest,
    FlagRule,
    PublicSettingsResponse,
    SettingResponse,
)

CACHE_TTL = timedelta(hours=1)


class PlatformService:
    def __init__(self, session: AsyncSession, redis: RedisStore) -> None:
        self.session = session
        self.redis = redis
        self.repository = PlatformRepository(session)

    async def setting_value(self, key: str) -> SettingValue:
        definition = SETTINGS.get(key)
        if definition is None:
            raise NotFoundError(code="setting_not_found")
        cache_key = self.redis.keys.key("platform.setting", key)
        cached = await self.redis.get(cache_key)
        if cached is not None:
            return validate_setting(key, json.loads(cached))
        row = await self.repository.setting(key)
        value = validate_setting(key, row.value if row is not None else definition.default)
        await self.redis.set(cache_key, json.dumps(value), ttl=CACHE_TTL)
        return value

    async def settings(self, *, public_only: bool = False) -> list[SettingResponse]:
        rows = {row.key: row for row in await self.repository.settings()}
        result: list[SettingResponse] = []
        for key, definition in SETTINGS.items():
            if public_only and not definition.public:
                continue
            row = rows.get(key)
            result.append(
                SettingResponse(
                    key=key,
                    value=validate_setting(key, row.value if row is not None else definition.default),
                    schema_=definition.schema,
                    description=definition.description,
                    public=definition.public,
                    version=row.version if row is not None else 1,
                    updated_at=row.updated_at if row is not None else None,
                )
            )
        return result

    async def public_settings(self) -> PublicSettingsResponse:
        return PublicSettingsResponse(settings={item.key: item.value for item in await self.settings(public_only=True)})

    async def update_setting(self, key: str, value: object, version: int, actor_id: UUID) -> SettingResponse:
        definition = SETTINGS.get(key)
        if definition is None:
            raise NotFoundError(code="setting_not_found")
        try:
            validated = validate_setting(key, value)
        except ValueError as error:
            raise ValidationAppError(code="setting_value_invalid") from error
        row = await self.repository.update_setting(key, validated, version, actor_id)
        if row is None:
            raise ConflictError(code="setting_version_conflict")
        self._delete_after_commit(self.redis.keys.key("platform.setting", key))
        return SettingResponse(
            key=key,
            value=validated,
            schema_=definition.schema,
            description=definition.description,
            public=definition.public,
            version=row.version,
            updated_at=row.updated_at,
        )

    async def flags(self) -> list[FeatureFlagResponse]:
        return [self._flag_response(flag) for flag in await self.repository.flags()]

    async def create_flag(self, body: FeatureFlagWriteRequest, actor_id: UUID) -> FeatureFlagResponse:
        if await self.repository.flag(body.key) is not None:
            raise ConflictError(code="flag_exists")
        flag = FeatureFlag(
            key=body.key,
            description=body.description,
            enabled=body.enabled,
            rollout_percentage=body.rollout_percentage,
            rules=[rule.model_dump(mode="json") for rule in body.rules],
            updated_by=actor_id,
        )
        self.session.add(flag)
        try:
            await self.session.flush()
        except IntegrityError as error:
            raise ConflictError(code="flag_exists") from error
        self._flags_changed()
        return self._flag_response(flag)

    async def update_flag(self, key: str, body: FeatureFlagUpdateRequest, actor_id: UUID) -> FeatureFlagResponse:
        flag = await self.repository.flag(key, lock=True)
        if flag is None:
            raise NotFoundError(code="flag_not_found")
        if flag.version != body.version:
            raise ConflictError(code="flag_version_conflict")
        flag.description = body.description
        flag.enabled = body.enabled
        flag.rollout_percentage = body.rollout_percentage
        flag.rules = [rule.model_dump(mode="json") for rule in body.rules]
        flag.version += 1
        flag.updated_by = actor_id
        await self.session.flush()
        self._flags_changed()
        return self._flag_response(flag)

    async def delete_flag(self, key: str, version: int) -> None:
        existing = await self.repository.flag(key)
        if existing is None:
            raise NotFoundError(code="flag_not_found")
        if not await self.repository.delete_flag(key, version):
            raise ConflictError(code="flag_version_conflict")
        self._flags_changed()

    async def evaluated_flags(self, principal: Principal | None) -> EvaluatedFlagsResponse:
        roles: frozenset[str] = frozenset()
        user_id = principal.user_id if principal is not None else None
        if user_id is not None:
            roles = (await resolve_access(self.session, self.redis, user_id)).roles
        generation_key = self.redis.keys.key("platform.flags.generation", "global")
        generation = await self.redis.get(generation_key)
        subject = str(user_id) if user_id is not None else "anonymous"
        cache_key = self.redis.keys.key(
            "platform.flags.evaluated",
            generation.decode() if generation is not None else "0",
            subject,
            ",".join(sorted(roles)),
        )
        cached = await self.redis.get(cache_key)
        if cached is not None:
            return EvaluatedFlagsResponse.model_validate_json(cached)
        result = EvaluatedFlagsResponse(
            flags={flag.key: self.evaluate_flag(flag, user_id, roles) for flag in await self.repository.flags()}
        )
        await self.redis.set(cache_key, result.model_dump_json(), ttl=CACHE_TTL)
        return result

    def evaluate_flag(self, flag: FeatureFlag, user_id: UUID | None, roles: frozenset[str]) -> bool:
        if not flag.enabled:
            return False
        rules = [FlagRule.model_validate(rule) for rule in flag.rules]
        subject = str(user_id) if user_id is not None else "anonymous"
        for rule in rules:
            if rule.kind == "user" and user_id is not None and subject in rule.values:
                return True
            if rule.kind == "role" and roles.intersection(rule.values):
                return True
        bucket = int.from_bytes(hashlib.sha256(f"{flag.key}:{subject}".encode()).digest()[:8], "big") % 100
        return bucket < flag.rollout_percentage

    def _flag_response(self, flag: FeatureFlag) -> FeatureFlagResponse:
        return FeatureFlagResponse(
            key=flag.key,
            description=flag.description,
            enabled=flag.enabled,
            rollout_percentage=flag.rollout_percentage,
            rules=[FlagRule.model_validate(rule) for rule in flag.rules],
            version=flag.version,
            updated_at=flag.updated_at,
        )

    def _delete_after_commit(self, key: str) -> None:
        async def delete() -> None:
            await self.redis.delete(key)

        after_commit(self.session, delete)

    def _flags_changed(self) -> None:
        async def increment() -> None:
            await self.redis.increment(
                self.redis.keys.key("platform.flags.generation", "global"), ttl=timedelta(days=3650)
            )

        after_commit(self.session, increment)
