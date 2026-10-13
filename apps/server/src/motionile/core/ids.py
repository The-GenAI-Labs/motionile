from uuid import UUID

import uuid_utils


def new_id() -> UUID:
    return UUID(bytes=uuid_utils.uuid7().bytes)


UUID_VERSION = 7


def is_uuid7(value: UUID) -> bool:
    return value.version == UUID_VERSION
