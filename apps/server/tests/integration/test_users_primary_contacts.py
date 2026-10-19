from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete

from motionile.core.db import Database
from motionile.core.ids import new_id
from motionile.modules.users import PrimaryContacts, User, UserContact, UsersService

VERIFIED = datetime(2026, 10, 1, tzinfo=UTC)


async def make_user(
    database: Database, *contacts: tuple[str, str, bool, bool], name: str | None = "Asha Rao", status: str = "active"
) -> UUID:
    user_id = new_id()
    async with database.transaction() as session:
        session.add(User(id=user_id, name=name, status=status, deleted_at=VERIFIED if status == "deleted" else None))
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


async def contacts_of(database: Database, user_id: UUID) -> PrimaryContacts | None:
    async with database.transaction() as session:
        return await UsersService(session).primary_verified_contacts(user_id)


async def remove(database: Database, *user_ids: UUID) -> None:
    async with database.transaction() as session:
        await session.execute(delete(User).where(User.id.in_(user_ids)))


async def test_returns_the_name_and_the_primary_verified_email_and_phone(database: Database) -> None:
    user_id = await make_user(
        database,
        ("email", "primary@example.com", True, True),
        ("email", "secondary@example.com", False, True),
        ("phone", "+919876543210", True, True),
    )

    assert await contacts_of(database, user_id) == PrimaryContacts("Asha Rao", "primary@example.com", "+919876543210")
    await remove(database, user_id)


async def test_ignores_unverified_and_non_primary_contacts(database: Database) -> None:
    unverified = await make_user(
        database, ("email", "pending@example.com", True, False), ("phone", "+919876543211", True, False)
    )
    secondary = await make_user(database, ("email", "second@example.com", False, True), name=None)

    assert await contacts_of(database, unverified) == PrimaryContacts("Asha Rao", None, None)
    assert await contacts_of(database, secondary) == PrimaryContacts(None, None, None)
    await remove(database, unverified, secondary)


async def test_deleted_and_unknown_users_have_no_contacts(database: Database) -> None:
    gone = await make_user(database, ("email", "gone@example.com", True, True), status="deleted")

    assert await contacts_of(database, gone) is None
    assert await contacts_of(database, new_id()) is None
    await remove(database, gone)
