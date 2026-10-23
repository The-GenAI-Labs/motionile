from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from motionile.modules.credits import CreditsService, ReservationNotActiveError, ReservationNotFoundError

RESERVATION_REF_TYPE = "voice_clone"


def reservation_key(voice_id: UUID) -> str:
    return f"voice-clone:{voice_id}:reserve"


def commit_key(voice_id: UUID) -> str:
    return f"voice-clone:{voice_id}:commit"


def release_key(voice_id: UUID) -> str:
    return f"voice-clone:{voice_id}:release"


async def release_clone_reservation(
    credit_service: CreditsService, session: AsyncSession, user_id: UUID, voice_id: UUID
) -> bool:
    reservation = await credit_service.active_reservation(session, user_id, RESERVATION_REF_TYPE, voice_id)
    if reservation is None:
        return False
    try:
        await credit_service.release(session, reservation.id, release_key(voice_id))
    except (ReservationNotActiveError, ReservationNotFoundError):
        return False
    return True
