from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import Field

from motionile.core.dependencies import ResourcesDep
from motionile.core.errors import NotFoundError, problem_responses, request_id_of
from motionile.core.idempotency import IdempotencyGuard, idempotent
from motionile.core.ids import new_id
from motionile.core.ratelimit.limiter import rate_limit
from motionile.core.schemas import ResponseModel, StrictModel
from motionile.modules.audit import ActorType, AuditEvent, context_from_request, record
from motionile.modules.auth import FakeGrant, FakeOAuthProvider, ProviderIdentity, ProviderName
from motionile.modules.notifications import FakeDelivery, Notification

TEST_IDEMPOTENCY_SCOPE = "test.idempotent"

test_support_router = APIRouter(prefix="/_test", tags=["test_support"])


class EchoRequest(StrictModel):
    message: str = Field(min_length=1, max_length=500)
    repeat_count: int = Field(default=1, ge=1, le=10)


class EchoResponse(ResponseModel):
    message: str
    repeat_count: int
    request_id: str | None


class TestStatusResponse(ResponseModel):
    status: str


class IdempotentItemRequest(StrictModel):
    item_name: str = Field(min_length=1, max_length=100)


class IdempotentItemResponse(ResponseModel):
    id: UUID
    item_name: str


@test_support_router.post(
    "/echo",
    response_model=EchoResponse,
    status_code=status.HTTP_200_OK,
    summary="Echo the request body through the full middleware chain",
    responses=problem_responses(status.HTTP_403_FORBIDDEN, status.HTTP_422_UNPROCESSABLE_CONTENT),
)
async def echo(body: EchoRequest, request: Request) -> EchoResponse:
    return EchoResponse(message=body.message, repeat_count=body.repeat_count, request_id=request_id_of(request))


@test_support_router.get(
    "/rate-limited",
    response_model=TestStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Return ok until the dedicated test rate-limit policy is exhausted",
    dependencies=[Depends(rate_limit("test.limited"))],
)
async def rate_limited() -> TestStatusResponse:
    return TestStatusResponse(status="ok")


@test_support_router.post(
    "/idempotent",
    response_model=IdempotentItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a test item once per Idempotency-Key",
    responses=problem_responses(status.HTTP_400_BAD_REQUEST, status.HTTP_409_CONFLICT),
)
async def create_idempotent_item(
    body: IdempotentItemRequest,
    request: Request,
    resources: ResourcesDep,
    guard: Annotated[IdempotencyGuard, Depends(idempotent(TEST_IDEMPOTENCY_SCOPE))],
) -> JSONResponse:
    item_id = new_id()
    async with resources.database.transaction() as session:
        await record(
            session,
            AuditEvent(
                action="test_support.item.created",
                actor_type=ActorType.SYSTEM,
                target_type="test_item",
                target_id=str(item_id),
                metadata={"itemName": body.item_name},
            ),
            context_from_request(request),
        )
    return await guard.respond(
        IdempotentItemResponse(id=item_id, item_name=body.item_name),
        status_code=status.HTTP_201_CREATED,
        headers={"Location": f"/v1/_test/idempotent/{item_id}"},
    )


class InboxResponse(ResponseModel):
    messages: list[Notification]


class FakeAuthorizeQuery(StrictModel):
    state: str = Field(min_length=1, max_length=256)
    challenge: str = Field(min_length=1, max_length=256)
    nonce: str = Field(min_length=1, max_length=256)
    email: str = Field(default="oauth@example.com", max_length=254)
    verified: bool = True


@test_support_router.get(
    "/inbox/{destination}",
    response_model=InboxResponse,
    status_code=200,
    summary="Read the fake delivery inbox",
)
async def inbox(destination: str, resources: ResourcesDep) -> InboxResponse:
    if not resources.settings.is_fake_providers:
        raise NotFoundError
    return InboxResponse(messages=await FakeDelivery(resources.redis_store).inbox(destination))


@test_support_router.get(
    "/oauth/{provider}/authorize",
    response_model=None,
    status_code=302,
    summary="Authorize through the local fake provider",
    dependencies=[Depends(rate_limit("api.default"))],
)
async def fake_authorize(
    provider: ProviderName, query: Annotated[FakeAuthorizeQuery, Query()], resources: ResourcesDep
) -> RedirectResponse:
    if not resources.settings.is_fake_providers:
        raise NotFoundError
    adapter = FakeOAuthProvider(provider, resources.settings.auth.api_origin, resources.redis_store)
    grant = FakeGrant(
        challenge=query.challenge,
        nonce=query.nonce,
        identity=ProviderIdentity(subject=query.email, email=query.email, email_verified=query.verified),
    )
    return RedirectResponse(await adapter.authorize(query.state, grant), status_code=302)
