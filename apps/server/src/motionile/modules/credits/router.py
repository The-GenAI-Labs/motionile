from typing import Annotated

from fastapi import APIRouter, Depends, Query

from motionile.core.dependencies import CursorCodecDep, DatabaseDep
from motionile.core.errors import problem_responses
from motionile.core.pagination import Cursor, CursorCodec
from motionile.core.ratelimit.limiter import rate_limit
from motionile.core.schemas import PageQuery
from motionile.modules.auth import enforce_csrf
from motionile.modules.credits.dependencies import CreditsServiceDep, CurrentUserIdDep
from motionile.modules.credits.schemas import (
    DailyUsageListResponse,
    DailyUsageResponse,
    ExpiringLotResponse,
    LedgerEntryResponse,
    LedgerPageResponse,
    UsageEntryResponse,
    UsagePageResponse,
    UsageQuery,
    WalletResponse,
)


def encode_cursor(codec: CursorCodec, cursor: Cursor | None) -> str | None:
    return codec.encode(cursor) if cursor is not None else None


credits_router = APIRouter(
    prefix="/credits",
    tags=["credits"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 422),
)


@credits_router.get("/wallet", response_model=WalletResponse, status_code=200, summary="Get the credit wallet")
async def wallet(user_id: CurrentUserIdDep, database: DatabaseDep, service: CreditsServiceDep) -> WalletResponse:
    async with database.transaction() as session:
        view = await service.wallet(session, user_id)
    return WalletResponse(
        balance=view.balance,
        reserved=view.reserved,
        available=view.available,
        expiring_soon=[ExpiringLotResponse.model_validate(lot) for lot in view.expiring_soon],
    )


@credits_router.get(
    "/ledger", response_model=LedgerPageResponse, status_code=200, summary="List credit ledger entries, newest first"
)
async def ledger(
    query: Annotated[PageQuery, Query()],
    user_id: CurrentUserIdDep,
    database: DatabaseDep,
    cursors: CursorCodecDep,
    service: CreditsServiceDep,
) -> LedgerPageResponse:
    cursor = cursors.decode(query.cursor) if query.cursor else None
    async with database.transaction() as session:
        page = await service.ledger(session, user_id, cursor, query.limit)
    return LedgerPageResponse(
        items=[LedgerEntryResponse.model_validate(item) for item in page.items],
        next_cursor=encode_cursor(cursors, page.next_cursor),
    )


@credits_router.get(
    "/usage",
    response_model=UsagePageResponse | DailyUsageListResponse,
    status_code=200,
    summary="List credit usage, newest first, or aggregate it per UTC day",
)
async def usage(
    query: Annotated[UsageQuery, Query()],
    user_id: CurrentUserIdDep,
    database: DatabaseDep,
    cursors: CursorCodecDep,
    service: CreditsServiceDep,
) -> UsagePageResponse | DailyUsageListResponse:
    if query.aggregate == "daily":
        async with database.transaction() as session:
            days = await service.daily_usage(session, user_id, query.range_start, query.range_end)
        return DailyUsageListResponse(items=[DailyUsageResponse.model_validate(day) for day in days])
    cursor = cursors.decode(query.cursor) if query.cursor else None
    async with database.transaction() as session:
        page = await service.usage(session, user_id, cursor, query.limit)
    return UsagePageResponse(
        items=[UsageEntryResponse.model_validate(item) for item in page.items],
        next_cursor=encode_cursor(cursors, page.next_cursor),
    )
