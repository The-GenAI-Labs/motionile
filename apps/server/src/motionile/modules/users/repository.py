from datetime import datetime
from uuid import UUID

from sqlalchemy import func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.core.pagination import Cursor, keyset_page
from motionile.core.security.identifiers import Identifier
from motionile.modules.access import Role, UserRole
from motionile.modules.users.models import User, UserContact, UserPreference


class UsersRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: UUID, *, lock: bool = False) -> User | None:
        query = select(User).where(User.id == user_id, User.deleted_at.is_(None))
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def get_any(self, user_id: UUID, *, lock: bool = False) -> User | None:
        query = select(User).where(User.id == user_id)
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def find_contact(self, identifier: Identifier, *, verified_only: bool = True) -> UserContact | None:
        query = (
            select(UserContact)
            .join(User)
            .where(
                UserContact.kind == identifier.kind,
                UserContact.value == identifier.value,
                User.deleted_at.is_(None),
            )
        )
        if verified_only:
            query = query.where(UserContact.verified_at.is_not(None))
        return await self.session.scalar(
            query.order_by(UserContact.verified_at.desc().nulls_last(), UserContact.created_at.desc()).limit(1)
        )

    async def contacts(self, user_id: UUID) -> list[UserContact]:
        return list(
            await self.session.scalars(
                select(UserContact)
                .where(UserContact.user_id == user_id)
                .order_by(UserContact.is_primary.desc(), UserContact.id)
            )
        )

    async def primary_verified_email(self, user_id: UUID) -> str | None:
        value = await self.session.scalar(
            select(UserContact.value)
            .join(User, User.id == UserContact.user_id)
            .where(
                UserContact.user_id == user_id,
                UserContact.kind == "email",
                UserContact.is_primary.is_(True),
                UserContact.verified_at.is_not(None),
                User.deleted_at.is_(None),
            )
        )
        return str(value) if value is not None else None

    async def primary_verified_contacts(self, user_id: UUID) -> tuple[str | None, str | None, str | None] | None:
        user = (
            await self.session.execute(select(User.name).where(User.id == user_id, User.deleted_at.is_(None)))
        ).one_or_none()
        if user is None:
            return None
        values = {
            kind: str(value)
            for kind, value in await self.session.execute(
                select(UserContact.kind, UserContact.value).where(
                    UserContact.user_id == user_id,
                    UserContact.is_primary.is_(True),
                    UserContact.verified_at.is_not(None),
                )
            )
        }
        return user[0], values.get("email"), values.get("phone")

    async def contact(self, user_id: UUID, contact_id: UUID, *, lock: bool = False) -> UserContact | None:
        query = select(UserContact).where(UserContact.user_id == user_id, UserContact.id == contact_id)
        if lock:
            query = query.with_for_update()
        return await self.session.scalar(query)

    async def add_contact(self, contact: UserContact) -> None:
        self.session.add(contact)
        await self.session.flush()

    async def set_primary(self, user_id: UUID, contact: UserContact) -> None:
        await self.session.execute(
            update(UserContact)
            .where(UserContact.user_id == user_id, UserContact.kind == contact.kind)
            .values(is_primary=False)
        )
        contact.is_primary = True
        await self.session.flush()

    async def remove_contact(self, contact: UserContact) -> None:
        await self.session.delete(contact)

    async def verified_contact_count(self, user_id: UUID) -> int:
        query = (
            select(func.count())
            .select_from(UserContact)
            .where(UserContact.user_id == user_id, UserContact.verified_at.is_not(None))
        )
        return int(await self.session.scalar(query) or 0)

    async def preference(self, user_id: UUID) -> UserPreference | None:
        return await self.session.get(UserPreference, user_id)

    async def roles(self, user_id: UUID) -> list[str]:
        query = select(Role.key).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
        return list(await self.session.scalars(query.order_by(Role.key)))

    async def active_role_count(self, role_key: str) -> int:
        query = (
            select(func.count())
            .select_from(UserRole)
            .join(Role, Role.id == UserRole.role_id)
            .join(User, User.id == UserRole.user_id)
            .where(Role.key == role_key, User.status == "active", User.deleted_at.is_(None))
        )
        return int(await self.session.scalar(query) or 0)

    async def delete_user(self, user: User) -> None:
        await self.session.delete(user)

    async def admin_users(  # noqa: PLR0913
        self,
        *,
        search: str | None,
        status: str | None,
        role: str | None,
        created_from: datetime | None,
        created_to: datetime | None,
        sort: str,
        cursor: Cursor | None,
        limit: int,
    ) -> list[User]:
        query = select(User).distinct()
        if search:
            prefix = f"{search}%"
            query = query.outerjoin(UserContact).where(or_(User.name.ilike(prefix), UserContact.value.ilike(prefix)))
        if status:
            query = query.where(User.status == status)
        if role:
            query = query.join(UserRole, UserRole.user_id == User.id).join(Role).where(Role.key == role)
        if created_from:
            query = query.where(User.created_at >= created_from)
        if created_to:
            query = query.where(User.created_at <= created_to)
        if sort == "created_asc":
            if cursor is not None:
                query = query.where(tuple_(User.created_at, User.id) > tuple_(cursor.created_at, cursor.id))
            query = query.order_by(User.created_at, User.id).limit(limit + 1)
        else:
            query = keyset_page(query, created_at=User.created_at, id_=User.id, cursor=cursor, limit=limit)
        return list(await self.session.scalars(query))

    async def activate(self, user: User, contact: UserContact, now: datetime) -> None:
        contact.verified_at = now
        await self.session.execute(
            update(User).where(User.id == user.id, User.status == user.status).values(status="active")
        )
        await self.session.flush()

    async def create(self, name: str, identifier: Identifier, now: datetime, *, verified: bool = False) -> User:
        user = User(
            id=new_id(),
            name=name,
            status="active" if verified else "pending_verification",
            created_at=now,
            updated_at=now,
        )
        self.session.add(user)
        await self.session.flush()
        self.session.add(
            UserContact(
                id=new_id(),
                user_id=user.id,
                kind=identifier.kind,
                value=identifier.value,
                verified_at=now if verified else None,
                is_primary=True,
                created_at=now,
                updated_at=now,
            )
        )
        await self.session.flush()
        return user
