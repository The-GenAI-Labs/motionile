from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from motionile.core.dependencies import CursorCodecDep, ResourcesDep
from motionile.core.errors import ConflictError, NotFoundError, RateLimitedError, UnauthorizedError, problem_responses
from motionile.core.pagination import Cursor, build_page
from motionile.core.ratelimit.limiter import rate_limit
from motionile.modules.access import AccessService, UsersManageDep, UsersReadDep, UsersRolesAssignDep
from motionile.modules.audit import ActorType, AuditEvent, context_from_request, recent_for_user, record
from motionile.modules.auth import (
    CurrentPrincipalDep,
    active_session_count,
    enforce_csrf,
    revoke_user_sessions,
    session_families,
)
from motionile.modules.notifications import Notification, enqueue_notification
from motionile.modules.users.schemas import (
    AccountDeletionConfirmRequest,
    AdminUserAuditEntry,
    AdminUserDetailResponse,
    AdminUserListResponse,
    AdminUserQuery,
    AdminUserSummary,
    AvatarResponse,
    ContactAddRequest,
    ContactChallengeResponse,
    ContactVerifyRequest,
    ExportResponse,
    UserContactResponse,
    UserPreferencesResponse,
    UserPreferencesUpdateRequest,
    UserProfileResponse,
    UserProfileUpdateRequest,
    UserRoleMutationRequest,
)
from motionile.modules.users.service import UsersService
from motionile.modules.users.tasks import defer_export

users_router = APIRouter(
    prefix="/users/me",
    tags=["users"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 403, 404, 409, 413, 422, 429),
)
users_admin_router = APIRouter(
    prefix="/admin/users",
    tags=["admin-users"],
    dependencies=[Depends(enforce_csrf), Depends(rate_limit("api.default"))],
    responses=problem_responses(401, 403, 404, 409, 422),
)


def user_id(principal: CurrentPrincipalDep) -> UUID:
    if principal.user_id is None:
        raise UnauthorizedError(code="unauthenticated")
    return principal.user_id


@users_router.get("", response_model=UserProfileResponse, status_code=200, summary="Get the current user profile")
async def get_profile(request: Request, resources: ResourcesDep, principal: CurrentPrincipalDep) -> UserProfileResponse:
    async with resources.database.transaction() as session:
        return await UsersService(session, resources, context_from_request(request)).profile(user_id(principal))


@users_router.patch("", response_model=UserProfileResponse, status_code=200, summary="Update the current user profile")
async def update_profile(
    body: UserProfileUpdateRequest, request: Request, resources: ResourcesDep, principal: CurrentPrincipalDep
) -> UserProfileResponse:
    async with resources.database.transaction() as session:
        return await UsersService(session, resources, context_from_request(request)).update_profile(
            user_id(principal), body
        )


@users_router.put("/avatar", response_model=AvatarResponse, status_code=200, summary="Upload the current user's avatar")
async def upload_avatar(
    request: Request, resources: ResourcesDep, principal: CurrentPrincipalDep, file: Annotated[UploadFile, File()]
) -> AvatarResponse:
    source = await file.read(10 * 1024 * 1024 + 1)
    async with resources.database.transaction() as session:
        return await UsersService(session, resources, context_from_request(request)).set_avatar(
            user_id(principal), source
        )


@users_router.delete(
    "/avatar", response_model=None, status_code=status.HTTP_204_NO_CONTENT, summary="Delete the current user's avatar"
)
async def delete_avatar(request: Request, resources: ResourcesDep, principal: CurrentPrincipalDep) -> None:
    async with resources.database.transaction() as session:
        await UsersService(session, resources, context_from_request(request)).delete_avatar(user_id(principal))


@users_router.post(
    "/contacts",
    response_model=ContactChallengeResponse,
    status_code=202,
    summary="Request verification of a new contact",
)
async def add_contact(
    body: ContactAddRequest, request: Request, resources: ResourcesDep, principal: CurrentPrincipalDep
) -> ContactChallengeResponse:
    async with resources.database.transaction() as session:
        return await UsersService(session, resources, context_from_request(request)).request_contact(
            user_id(principal), body.identifier
        )


@users_router.post(
    "/contacts/verify", response_model=UserContactResponse, status_code=201, summary="Verify and add a contact"
)
async def verify_contact(
    body: ContactVerifyRequest, request: Request, resources: ResourcesDep, principal: CurrentPrincipalDep
) -> UserContactResponse:
    async with resources.database.transaction() as session:
        return await UsersService(session, resources, context_from_request(request)).verify_contact(
            user_id(principal), body.challenge_token, body.code
        )


@users_router.put(
    "/contacts/{contact_id}/primary",
    response_model=UserContactResponse,
    status_code=200,
    summary="Set a primary contact",
)
async def set_primary_contact(
    contact_id: UUID, request: Request, resources: ResourcesDep, principal: CurrentPrincipalDep
) -> UserContactResponse:
    async with resources.database.transaction() as session:
        return await UsersService(session, resources, context_from_request(request)).set_primary_contact(
            user_id(principal), contact_id
        )


@users_router.delete(
    "/contacts/{contact_id}", response_model=None, status_code=status.HTTP_204_NO_CONTENT, summary="Remove a contact"
)
async def remove_contact(
    contact_id: UUID, request: Request, resources: ResourcesDep, principal: CurrentPrincipalDep
) -> None:
    async with resources.database.transaction() as session:
        await UsersService(session, resources, context_from_request(request)).remove_contact(
            user_id(principal), contact_id
        )


@users_router.get(
    "/preferences", response_model=UserPreferencesResponse, status_code=200, summary="Get video preferences"
)
async def get_preferences(resources: ResourcesDep, principal: CurrentPrincipalDep) -> UserPreferencesResponse:
    async with resources.database.transaction() as session:
        return await UsersService(session, resources).preferences(user_id(principal))


@users_router.put(
    "/preferences", response_model=UserPreferencesResponse, status_code=200, summary="Replace video preferences"
)
async def update_preferences(
    body: UserPreferencesUpdateRequest, request: Request, resources: ResourcesDep, principal: CurrentPrincipalDep
) -> UserPreferencesResponse:
    async with resources.database.transaction() as session:
        return await UsersService(session, resources, context_from_request(request)).update_preferences(
            user_id(principal), body
        )


@users_router.post("/export", response_model=ExportResponse, status_code=202, summary="Request a user data export")
async def request_export(request: Request, resources: ResourcesDep, principal: CurrentPrincipalDep) -> ExportResponse:
    current_id = user_id(principal)
    key = resources.redis_store.keys.key("users.export", current_id)
    if not await resources.redis_store.set_if_absent(key, "1", ttl=timedelta(hours=24)):
        raise RateLimitedError(code="export_cooldown", headers={"Retry-After": "86400"})
    async with resources.database.transaction() as session:
        await UsersService(session, resources).get(current_id)
        defer_export(session, current_id)
        await record(
            session,
            AuditEvent(
                action="users.export.requested",
                actor_type=ActorType.USER,
                actor_user_id=current_id,
                target_type="user",
                target_id=str(current_id),
            ),
            context_from_request(request),
        )
    return ExportResponse()


@users_router.post(
    "/delete/request",
    response_model=ContactChallengeResponse,
    status_code=202,
    summary="Request account deletion verification",
)
async def request_deletion(
    request: Request, resources: ResourcesDep, principal: CurrentPrincipalDep
) -> ContactChallengeResponse:
    async with resources.database.transaction() as session:
        return await UsersService(session, resources, context_from_request(request)).request_deletion(
            user_id(principal)
        )


@users_router.post(
    "/delete/confirm", response_model=None, status_code=status.HTTP_204_NO_CONTENT, summary="Confirm account deletion"
)
async def confirm_deletion(
    body: AccountDeletionConfirmRequest, request: Request, resources: ResourcesDep, principal: CurrentPrincipalDep
) -> None:
    async with resources.database.transaction() as session:
        await UsersService(session, resources, context_from_request(request)).confirm_deletion(
            user_id(principal), body.challenge_token, body.code
        )


@users_admin_router.get("", response_model=AdminUserListResponse, status_code=200, summary="Search users")
async def admin_users(
    query: Annotated[AdminUserQuery, Depends()],
    request: Request,
    resources: ResourcesDep,
    cursor_codec: CursorCodecDep,
    principal: UsersReadDep,
) -> AdminUserListResponse:
    cursor = cursor_codec.decode(query.cursor) if query.cursor else None
    async with resources.database.transaction() as session:
        repository = UsersService(session, resources).repository
        rows = await repository.admin_users(
            search=query.search,
            status=query.status,
            role=query.role,
            created_from=query.created_from,
            created_to=query.created_to,
            sort=query.sort,
            cursor=cursor,
            limit=query.limit,
        )
        items, next_cursor = build_page(
            rows, limit=query.limit, codec=cursor_codec, key=lambda row: Cursor(row.created_at, row.id)
        )
        summaries: list[AdminUserSummary] = []
        for row in items:
            contacts = await repository.contacts(row.id)
            summaries.append(
                AdminUserSummary(
                    id=row.id,
                    name=row.name,
                    status=row.status,
                    primary_contact=next((str(item.value) for item in contacts if item.is_primary), None),
                    roles=await repository.roles(row.id),
                    created_at=row.created_at,
                )
            )
        await record(
            session,
            AuditEvent(
                action="users.listed",
                actor_type=ActorType.ADMIN,
                actor_user_id=principal.user_id,
                target_type="user",
            ),
            context_from_request(request),
        )
        return AdminUserListResponse(items=summaries, next_cursor=next_cursor)


@users_admin_router.get(
    "/{target_id}", response_model=AdminUserDetailResponse, status_code=200, summary="Get an administrative user detail"
)
async def admin_user_detail(
    target_id: UUID, request: Request, resources: ResourcesDep, principal: UsersReadDep
) -> AdminUserDetailResponse:
    async with resources.database.transaction() as session:
        service = UsersService(session, resources)
        profile = await service.profile(target_id)
        result = AdminUserDetailResponse(
            **profile.model_dump(),
            roles=await service.repository.roles(target_id),
            active_session_count=await active_session_count(session, target_id, resources.clock.now()),
            recent_audit=[
                AdminUserAuditEntry.model_validate(entry) for entry in await recent_for_user(session, target_id)
            ],
        )
        await record(
            session,
            AuditEvent(
                action="users.read",
                actor_type=ActorType.ADMIN,
                actor_user_id=principal.user_id,
                target_type="user",
                target_id=str(target_id),
            ),
            context_from_request(request),
        )
        return result


async def admin_status(
    target_id: UUID, action: str, request: Request, resources: ResourcesDep, principal: UsersManageDep
) -> None:
    transitions = {
        "suspend": ("active", "suspended"),
        "unsuspend": ("suspended", "active"),
        "restore": ("deleted", "active"),
    }
    expected_status, new_status = transitions[action]
    async with resources.database.transaction() as session:
        service = UsersService(session, resources)
        user = await service.repository.get_any(target_id, lock=True)
        if user is None:
            raise NotFoundError(code="user_not_found")
        if user.status != expected_status:
            raise ConflictError(code=f"user_{action}_invalid_status")
        if (
            action == "suspend"
            and "super_admin" in await service.repository.roles(target_id)
            and await service.repository.active_role_count("super_admin") <= 1
        ):
            raise ConflictError(code="last_super_admin")
        if action == "restore":
            user.deleted_at = None
            contacts = await service.contacts(target_id)
            contact = next((item for item in contacts if item.verified_at is not None and item.is_primary), None)
            if contact is not None:
                enqueue_notification(
                    resources,
                    session,
                    Notification(
                        destination=str(contact.value),
                        channel="email" if contact.kind == "email" else "whatsapp",
                        template="account_restored",
                    ),
                )
        user.status = new_status
        if new_status == "suspended":
            families = await session_families(session, target_id)
            await revoke_user_sessions(session, target_id, resources.clock.now(), "user_suspended")
            for family_id in families:
                await resources.redis_store.set(
                    resources.redis_store.keys.key("auth.revoked", family_id), "1", ttl=timedelta(minutes=20)
                )
        await record(
            session,
            AuditEvent(
                action=f"users.{action}",
                actor_type=ActorType.ADMIN,
                actor_user_id=principal.user_id,
                target_type="user",
                target_id=str(target_id),
            ),
            context_from_request(request),
        )


@users_admin_router.post(
    "/{target_id}/suspend", response_model=None, status_code=status.HTTP_204_NO_CONTENT, summary="Suspend a user"
)
async def suspend_user(target_id: UUID, request: Request, resources: ResourcesDep, principal: UsersManageDep) -> None:
    await admin_status(target_id, "suspend", request, resources, principal)


@users_admin_router.post(
    "/{target_id}/unsuspend", response_model=None, status_code=status.HTTP_204_NO_CONTENT, summary="Unsuspend a user"
)
async def unsuspend_user(target_id: UUID, request: Request, resources: ResourcesDep, principal: UsersManageDep) -> None:
    await admin_status(target_id, "unsuspend", request, resources, principal)


@users_admin_router.post(
    "/{target_id}/restore",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Restore a deleted user",
)
async def restore_user(target_id: UUID, request: Request, resources: ResourcesDep, principal: UsersManageDep) -> None:
    await admin_status(target_id, "restore", request, resources, principal)


@users_admin_router.post(
    "/{target_id}/sign-out",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Force a user to sign out",
)
async def force_sign_out(target_id: UUID, request: Request, resources: ResourcesDep, principal: UsersManageDep) -> None:
    async with resources.database.transaction() as session:
        families = await session_families(session, target_id)
        await revoke_user_sessions(session, target_id, resources.clock.now(), "admin")
        for family_id in families:
            await resources.redis_store.set(
                resources.redis_store.keys.key("auth.revoked", family_id), "1", ttl=timedelta(minutes=20)
            )
        await record(
            session,
            AuditEvent(
                action="users.signed_out",
                actor_type=ActorType.ADMIN,
                actor_user_id=principal.user_id,
                target_type="user",
                target_id=str(target_id),
            ),
            context_from_request(request),
        )


@users_admin_router.post(
    "/{target_id}/roles", response_model=None, status_code=status.HTTP_204_NO_CONTENT, summary="Assign a role to a user"
)
async def assign_user_role(
    target_id: UUID,
    body: UserRoleMutationRequest,
    request: Request,
    resources: ResourcesDep,
    principal: UsersRolesAssignDep,
) -> None:
    async with resources.database.transaction() as session:
        await AccessService(session, resources.redis_store).assign(principal, target_id, body.role_id)
        await record(
            session,
            AuditEvent(
                action="users.role_assigned",
                actor_type=ActorType.ADMIN,
                actor_user_id=principal.user_id,
                target_type="user",
                target_id=str(target_id),
                metadata={"roleId": str(body.role_id)},
            ),
            context_from_request(request),
        )


@users_admin_router.delete(
    "/{target_id}/roles/{role_id}",
    response_model=None,
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a role from a user",
)
async def remove_user_role(
    target_id: UUID, role_id: UUID, request: Request, resources: ResourcesDep, principal: UsersRolesAssignDep
) -> None:
    async with resources.database.transaction() as session:
        await AccessService(session, resources.redis_store).remove(principal, target_id, role_id)
        await record(
            session,
            AuditEvent(
                action="users.role_removed",
                actor_type=ActorType.ADMIN,
                actor_user_id=principal.user_id,
                target_type="user",
                target_id=str(target_id),
                metadata={"roleId": str(role_id)},
            ),
            context_from_request(request),
        )
