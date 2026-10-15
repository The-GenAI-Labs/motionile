from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.ids import new_id
from motionile.core.security.identifiers import Identifier
from motionile.modules.users.models import User, UserContact


class UsersRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: UUID, *, lock: bool = False) -> User | None:
        query = select(User).where(User.id == user_id, User.deleted_at.is_(None))
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
