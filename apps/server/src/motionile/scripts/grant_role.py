import argparse
import asyncio

from motionile.core.config import get_settings
from motionile.core.errors import NotFoundError
from motionile.core.resources import build_resources
from motionile.core.security.identifiers import normalize_identifier
from motionile.modules.access import grant_role_by_key
from motionile.modules.audit import ActorType, AuditContext, AuditEvent, record
from motionile.modules.users import UsersService


async def grant(identifier_text: str, role_key: str) -> None:
    resources = build_resources(get_settings(), application_name="motionile-grant-role")
    try:
        identifier = normalize_identifier(identifier_text)
        async with resources.database.transaction() as session:
            contact = await UsersService(session).find_contact(identifier)
            if contact is None:
                raise NotFoundError(code="user_not_found")
            role = await grant_role_by_key(session, resources.redis_store, contact.user_id, role_key)
            await record(
                session,
                AuditEvent(
                    action="roles.bootstrap_granted",
                    actor_type=ActorType.SYSTEM,
                    target_type="user",
                    target_id=str(contact.user_id),
                    metadata={"role": role.key},
                ),
                AuditContext(),
            )
    finally:
        await resources.aclose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Grant a role to an existing verified Motionile user.")
    parser.add_argument("--identifier", required=True)
    parser.add_argument("--role", required=True)
    arguments = parser.parse_args(argv)
    asyncio.run(grant(arguments.identifier, arguments.role))


if __name__ == "__main__":
    main()
