from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.clock import Clock
from motionile.core.errors import NotFoundError
from motionile.core.pagination import Cursor, CursorCodec, build_page, keyset_page
from motionile.core.redis import RedisStore
from motionile.modules.admin.schemas import (
    AnalyticsResponse,
    AuditEntryResponse,
    AuditListResponse,
    AuditQuery,
    DailyUsers,
)
from motionile.modules.audit import AuditLogEntry
from motionile.modules.auth import Credential, OAuthIdentity, Session
from motionile.modules.users import User, UserContact

ANALYTICS_TTL = timedelta(minutes=5)


class AdminInsightsService:
    def __init__(self, session: AsyncSession, redis: RedisStore, clock: Clock, cursor_codec: CursorCodec) -> None:
        self.session = session
        self.redis = redis
        self.clock = clock
        self.cursor_codec = cursor_codec

    def _audit_response(self, row: AuditLogEntry) -> AuditEntryResponse:
        return AuditEntryResponse(
            id=row.id,
            actor_user_id=row.actor_user_id,
            actor_type=row.actor_type,
            action=row.action,
            target_type=row.target_type,
            target_id=row.target_id,
            ip=row.ip,
            user_agent=row.user_agent,
            request_id=row.request_id,
            metadata=row.metadata_,
            created_at=row.created_at,
        )

    async def audit_entries(self, query: AuditQuery, cursor: Cursor | None) -> AuditListResponse:
        statement = select(AuditLogEntry)
        if query.actor_user_id is not None:
            statement = statement.where(AuditLogEntry.actor_user_id == query.actor_user_id)
        if query.action is not None:
            statement = statement.where(AuditLogEntry.action == query.action)
        if query.target_type is not None:
            statement = statement.where(AuditLogEntry.target_type == query.target_type)
        if query.target_id is not None:
            statement = statement.where(AuditLogEntry.target_id == query.target_id)
        if query.created_from is not None:
            statement = statement.where(AuditLogEntry.created_at >= query.created_from)
        if query.created_to is not None:
            statement = statement.where(AuditLogEntry.created_at <= query.created_to)
        statement = keyset_page(
            statement,
            created_at=AuditLogEntry.created_at,
            id_=AuditLogEntry.id,
            cursor=cursor,
            limit=query.limit,
        )
        rows = list(await self.session.scalars(statement))
        items, next_cursor = build_page(
            rows,
            limit=query.limit,
            codec=self.cursor_codec,
            key=lambda row: Cursor(row.created_at, row.id),
        )
        return AuditListResponse(items=[self._audit_response(row) for row in items], next_cursor=next_cursor)

    async def audit_entry(self, entry_id: UUID) -> AuditEntryResponse:
        row = await self.session.get(AuditLogEntry, entry_id)
        if row is None:
            raise NotFoundError(code="audit_entry_not_found")
        return self._audit_response(row)

    async def analytics(self) -> AnalyticsResponse:
        key = self.redis.keys.key("admin.analytics")
        cached = await self.redis.get(key)
        if cached is not None:
            return AnalyticsResponse.model_validate_json(cached)
        now = self.clock.now()
        start = now - timedelta(days=29)
        total_users = int(await self.session.scalar(select(func.count()).select_from(User)) or 0)
        verified_users = int(
            await self.session.scalar(
                select(func.count(func.distinct(UserContact.user_id))).where(UserContact.verified_at.is_not(None))
            )
            or 0
        )
        active_sessions = int(
            await self.session.scalar(
                select(func.count())
                .select_from(Session)
                .where(
                    Session.revoked_at.is_(None),
                    Session.rotated_at.is_(None),
                    Session.idle_expires_at > now,
                    Session.absolute_expires_at > now,
                )
            )
            or 0
        )
        created_day = func.date(User.created_at)
        daily_rows = list(
            await self.session.execute(
                select(created_day, func.count()).where(User.created_at >= start).group_by(created_day)
            )
        )
        daily = {day: int(count) for day, count in daily_rows}
        dates = [(start + timedelta(days=offset)).date() for offset in range(30)]
        new_users = [DailyUsers(date=item, count=daily.get(item, 0)) for item in dates]
        password_count = int(await self.session.scalar(select(func.count()).select_from(Credential)) or 0)
        provider_rows = list(
            await self.session.execute(
                select(OAuthIdentity.provider, func.count(func.distinct(OAuthIdentity.user_id))).group_by(
                    OAuthIdentity.provider
                )
            )
        )
        result = AnalyticsResponse(
            total_users=total_users,
            verified_ratio=verified_users / total_users if total_users else 0,
            active_sessions=active_sessions,
            new_users=new_users,
            sign_in_methods={"password": password_count, **{provider: int(count) for provider, count in provider_rows}},
        )
        await self.redis.set(key, result.model_dump_json(), ttl=ANALYTICS_TTL)
        return result
