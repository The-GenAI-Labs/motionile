from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete

from motionile.core.db import Database
from motionile.core.ids import new_id
from motionile.modules.users import User, UserContact, UsersService

VERIFIED = datetime(2026, 10, 1, tzinfo=UTC)


async def make_user(database: Database, *contacts: tuple[str, str, bool, bool], status: str = "active") -> UUID:
    user_id = new_id()
    async with database.transaction() as session:
        session.add(
            User(
                id=user_id,
                name="Primary email",
                status=status,
                deleted_at=VERIFIED if status == "deleted" else None,
            )
        )
        await session.flush()
        for kind, value, primary, verified in contacts:
            session.add(
                UserContact(
                    id=new_id(),
                    user_id=user_id,
                    kind=kind,
                    value=value,
                    is_primary=primary,
                    verified_at=VERIFIED if verified else None,
                )
            )
    return user_id


async def primary_email(database: Database, user_id: UUID) -> str | None:
    async with database.transaction() as session:
        return await UsersService(session).primary_verified_email(user_id)


async def remove(database: Database, *user_ids: UUID) -> None:
    async with database.transaction() as session:
        await session.execute(delete(User).where(User.id.in_(user_ids)))


async def test_returns_the_primary_verified_email(database: Database) -> None:
    user_id = await make_user(
        database,
        ("email", "primary@example.com", True, True),
        ("email", "secondary@example.com", False, True),
        ("phone", "+919876543210", True, True),
    )

    assert await primary_email(database, user_id) == "primary@example.com"
    await remove(database, user_id)


async def test_ignores_unverified_primary_emails_and_phones(database: Database) -> None:
    unverified = await make_user(database, ("email", "pending@example.com", True, False))
    phone_only = await make_user(database, ("phone", "+919876543211", True, True))
    secondary_only = await make_user(database, ("email", "second@example.com", False, True))

    assert await primary_email(database, unverified) is None
    assert await primary_email(database, phone_only) is None
    assert await primary_email(database, secondary_only) is None
    assert await primary_email(database, new_id()) is None
    await remove(database, unverified, phone_only, secondary_only)


async def test_ignores_deleted_users(database: Database) -> None:
    user_id = await make_user(database, ("email", "gone@example.com", True, True), status="deleted")

    assert await primary_email(database, user_id) is None
    await remove(database, user_id)
