from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.errors import ConflictError, UnauthorizedError
from motionile.core.security.identifiers import Identifier
from motionile.modules.users.models import User, UserContact
from motionile.modules.users.repository import UsersRepository


class UsersService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = UsersRepository(session)

    async def get(self, user_id: UUID, *, lock: bool = False) -> User:
        user = await self.repository.get(user_id, lock=lock)
        if user is None:
            raise UnauthorizedError(code="unauthenticated")
        return user

    async def find_contact(self, identifier: Identifier, *, verified_only: bool = True) -> UserContact | None:
        return await self.repository.find_contact(identifier, verified_only=verified_only)

    async def create_pending(self, name: str, identifier: Identifier, now: datetime) -> User:
        return await self.repository.create(name, identifier, now)

    async def create_verified(self, name: str, identifier: Identifier, now: datetime) -> User:
        return await self.repository.create(name, identifier, now, verified=True)

    async def contacts(self, user_id: UUID) -> list[UserContact]:
        return await self.repository.contacts(user_id)

    async def activate(self, user_id: UUID, identifier: Identifier, now: datetime) -> User:
        user = await self.get(user_id, lock=True)
        existing = await self.find_contact(identifier)
        if existing is not None and existing.user_id != user_id:
            raise ConflictError(code="verification_conflict")
        if user.status not in {"pending_verification", "active"}:
            raise UnauthorizedError(code="invalid_challenge")
        contacts = await self.contacts(user_id)
        for contact in contacts:
            if contact.kind == identifier.kind and contact.value.casefold() == identifier.value.casefold():
                try:
                    await self.repository.activate(user, contact, now)
                except IntegrityError as error:
                    raise ConflictError(code="verification_conflict") from error
                return user
        raise UnauthorizedError(code="invalid_challenge")

    async def mark_login(self, user_id: UUID, now: datetime) -> None:
        user = await self.get(user_id)
        user.last_login_at = now
