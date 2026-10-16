from __future__ import annotations

from collections.abc import AsyncIterable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal, cast
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from motionile.core.db import after_commit, after_rollback
from motionile.core.errors import ConflictError, NotFoundError, UnauthorizedError, ValidationAppError
from motionile.core.ids import new_id
from motionile.core.resources import Resources
from motionile.core.security.identifiers import Identifier, normalize_identifier
from motionile.modules.audit import ActorType, AuditContext, AuditEvent, record
from motionile.modules.notifications import Notification, enqueue_notification
from motionile.modules.platform import PlatformService
from motionile.modules.users.avatar import process_avatar
from motionile.modules.users.events import UserDeletionRequested
from motionile.modules.users.models import User, UserContact, UserPreference
from motionile.modules.users.repository import UsersRepository
from motionile.modules.users.schemas import (
    AvatarResponse,
    ContactChallengeResponse,
    UserContactResponse,
    UserPreferencesResponse,
    UserPreferencesUpdateRequest,
    UserProfileResponse,
    UserProfileUpdateRequest,
)

if TYPE_CHECKING:
    from motionile.modules.auth import OtpService


class UsersService:
    def __init__(
        self,
        session: AsyncSession,
        resources: Resources | None = None,
        audit_context: AuditContext | None = None,
    ) -> None:
        self.session = session
        self.resources = resources
        self.audit_context = audit_context or AuditContext()
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

    def require_resources(self) -> Resources:
        if self.resources is None:
            raise RuntimeError("user resources are required")
        return self.resources

    async def profile(self, user_id: UUID) -> UserProfileResponse:
        resources = self.require_resources()
        user = await self.get(user_id)
        avatar_url = (
            await resources.storage.presigned_get_url(user.avatar_storage_key, expires_in=timedelta(minutes=15))
            if user.avatar_storage_key
            else None
        )
        return UserProfileResponse(
            id=user.id,
            name=user.name,
            status=user.status,
            locale=user.locale,
            avatar_url=avatar_url,
            contacts=[self._contact(item) for item in await self.contacts(user.id)],
            created_at=user.created_at,
        )

    async def update_profile(self, user_id: UUID, body: UserProfileUpdateRequest) -> UserProfileResponse:
        user = await self.get(user_id, lock=True)
        if body.name is not None:
            user.name = body.name
        if body.locale is not None:
            user.locale = body.locale
        await self.session.flush()
        await self._audit("users.profile.updated", user_id)
        return await self.profile(user_id)

    async def set_avatar(self, user_id: UUID, source: bytes) -> AvatarResponse:
        resources = self.require_resources()
        user = await self.get(user_id, lock=True)
        configured = await PlatformService(self.session, resources.redis_store).setting_value(
            "uploads.avatar_max_bytes"
        )
        if not isinstance(configured, int):
            raise RuntimeError("avatar limit must be an integer")
        encoded = await process_avatar(source, configured)
        key = f"avatars/{user.id}/{new_id()}.webp"

        async def chunks() -> AsyncIterable[bytes]:
            yield encoded

        await resources.storage.put(key, chunks(), content_type="image/webp")

        async def delete_new() -> None:
            await resources.storage.delete(key)

        after_rollback(self.session, delete_new)
        previous = user.avatar_storage_key
        user.avatar_storage_key = key
        await self.session.flush()
        if previous is not None:

            async def delete_previous() -> None:
                await resources.storage.delete(previous)

            after_commit(self.session, delete_previous)
        await self._audit("users.avatar.updated", user_id)
        return AvatarResponse(url=await resources.storage.presigned_get_url(key, expires_in=timedelta(minutes=15)))

    async def delete_avatar(self, user_id: UUID) -> None:
        resources = self.require_resources()
        user = await self.get(user_id, lock=True)
        if user.avatar_storage_key is not None:
            previous = user.avatar_storage_key
            user.avatar_storage_key = None
            await self.session.flush()

            async def delete_previous() -> None:
                await resources.storage.delete(previous)

            after_commit(self.session, delete_previous)
        await self._audit("users.avatar.deleted", user_id)

    async def request_contact(self, user_id: UUID, raw_identifier: str) -> ContactChallengeResponse:
        resources = self.require_resources()
        identifier = normalize_identifier(raw_identifier)
        user = await self.get(user_id)
        existing = await self.repository.find_contact(identifier, verified_only=False)
        if existing is not None and existing.user_id == user.id:
            raise ConflictError(code="contact_exists")
        ticket, _, code = await self._otp().issue("add_contact", identifier, user.id)
        enqueue_notification(
            resources,
            self.session,
            Notification(
                destination=identifier.value,
                channel="email" if identifier.kind == "email" else "whatsapp",
                template="contact_verification",
                code=code,
            ),
        )
        await self._audit("users.contact.requested", user.id)
        return ContactChallengeResponse(
            challenge_token=ticket,
            destination=self._masked(identifier),
            channel="email" if identifier.kind == "email" else "whatsapp",
        )

    async def verify_contact(self, user_id: UUID, ticket: str, code: str) -> UserContactResponse:
        resources = self.require_resources()
        challenge = await self._otp().verify(ticket, "add_contact", code)
        if challenge.user_id != user_id:
            raise UnauthorizedError(code="invalid_challenge")
        identifier = challenge.identifier
        await self.get(user_id, lock=True)
        existing = await self.repository.find_contact(identifier)
        if existing is not None and existing.user_id != user_id:
            raise ConflictError(code="verification_conflict")
        contacts = await self.contacts(user_id)
        contact = UserContact(
            id=new_id(),
            user_id=user_id,
            kind=identifier.kind,
            value=identifier.value,
            verified_at=resources.clock.now(),
            is_primary=not any(item.kind == identifier.kind and item.is_primary for item in contacts),
        )
        try:
            await self.repository.add_contact(contact)
        except IntegrityError as error:
            raise ConflictError(code="verification_conflict") from error
        await self._security_notice(user_id, contact.id)
        await self._audit("users.contact.verified", user_id, str(contact.id))
        return self._contact(contact)

    async def set_primary_contact(self, user_id: UUID, contact_id: UUID) -> UserContactResponse:
        await self.get(user_id, lock=True)
        contact = await self.repository.contact(user_id, contact_id, lock=True)
        if contact is None:
            raise NotFoundError(code="contact_not_found")
        if contact.verified_at is None:
            raise ConflictError(code="contact_unverified")
        await self.repository.set_primary(user_id, contact)
        await self._security_notice(user_id, contact.id)
        await self._audit("users.contact.primary_changed", user_id, str(contact.id))
        return self._contact(contact)

    async def remove_contact(self, user_id: UUID, contact_id: UUID) -> None:
        await self.get(user_id, lock=True)
        contact = await self.repository.contact(user_id, contact_id, lock=True)
        if contact is None:
            raise NotFoundError(code="contact_not_found")
        if contact.verified_at is not None and await self.repository.verified_contact_count(user_id) <= 1:
            raise ConflictError(code="last_verified_contact")
        if contact.is_primary:
            replacement = next(
                (
                    item
                    for item in await self.contacts(user_id)
                    if item.id != contact.id and item.kind == contact.kind and item.verified_at is not None
                ),
                None,
            )
            if replacement is not None:
                await self.repository.set_primary(user_id, replacement)
        await self.repository.remove_contact(contact)
        await self._security_notice(user_id, contact.id)
        await self._audit("users.contact.removed", user_id, str(contact.id))

    async def preferences(self, user_id: UUID) -> UserPreferencesResponse:
        await self.get(user_id)
        row = await self.repository.preference(user_id)
        if row is None:
            return UserPreferencesResponse(
                default_style=None,
                pace="normal",
                language="en",
                depth="standard",
                default_voice_id=None,
                default_aspect="16:9",
                captions_enabled=True,
            )
        return UserPreferencesResponse.model_validate(row)

    async def update_preferences(self, user_id: UUID, body: UserPreferencesUpdateRequest) -> UserPreferencesResponse:
        resources = self.require_resources()
        await self.get(user_id)
        settings = PlatformService(self.session, resources.redis_store)
        checks = {
            "default_style": (body.default_style, "preferences.styles"),
            "pace": (body.pace, "preferences.paces"),
            "language": (body.language, "preferences.languages"),
            "depth": (body.depth, "preferences.depths"),
            "default_aspect": (body.default_aspect, "preferences.aspects"),
        }
        for value, key in checks.values():
            allowed = await settings.setting_value(key)
            if not isinstance(allowed, list) or (value is not None and value not in allowed):
                raise ValidationAppError(code="preference_value_invalid")
        row = await self.repository.preference(user_id)
        values = body.model_dump()
        if row is None:
            row = UserPreference(user_id=user_id, **values)
            self.session.add(row)
        else:
            for key, value in values.items():
                setattr(row, key, value)
        await self.session.flush()
        await self._audit("users.preferences.updated", user_id)
        return UserPreferencesResponse.model_validate(row)

    async def request_deletion(self, user_id: UUID) -> ContactChallengeResponse:
        resources = self.require_resources()
        contacts = [item for item in await self.contacts(user_id) if item.verified_at is not None and item.is_primary]
        contact = next((item for item in contacts if item.kind == "email"), contacts[0] if contacts else None)
        if contact is None:
            raise ConflictError(code="verified_contact_required")
        identifier = Identifier(cast("Literal['email', 'phone']", contact.kind), str(contact.value))
        ticket, _, code = await self._otp().issue("delete_account", identifier, user_id)
        enqueue_notification(
            resources,
            self.session,
            Notification(
                destination=identifier.value,
                channel="email" if identifier.kind == "email" else "whatsapp",
                template="account_deletion",
                code=code,
            ),
        )
        await self._audit("users.deletion.requested", user_id)
        return ContactChallengeResponse(
            challenge_token=ticket,
            destination=self._masked(identifier),
            channel="email" if identifier.kind == "email" else "whatsapp",
        )

    async def confirm_deletion(self, user_id: UUID, ticket: str, code: str) -> None:
        resources = self.require_resources()
        challenge = await self._otp().verify(ticket, "delete_account", code)
        if challenge.user_id != user_id:
            raise UnauthorizedError(code="invalid_challenge")
        user = await self.get(user_id, lock=True)
        if (
            "super_admin" in await self.repository.roles(user_id)
            and await self.repository.active_role_count("super_admin") <= 1
        ):
            raise ConflictError(code="last_super_admin")
        now = resources.clock.now()
        from motionile.modules.auth import (  # noqa: PLC0415
            AuthRuntime,
            revoke_user_sessions,
            session_families,
        )

        families = await session_families(self.session, user_id)
        await revoke_user_sessions(self.session, user_id, now, "logout_all")

        for family_id in families:
            await AuthRuntime(resources).tokens.revoke(family_id)
        user.status = "deleted"
        user.deleted_at = now
        await self.session.flush()
        resources.events.publish_after_commit(self.session, UserDeletionRequested(user_id=user_id))
        await self._audit("users.deletion.confirmed", user_id)

    def _otp(self) -> OtpService:
        from motionile.modules.auth import AuthRuntime  # noqa: PLC0415

        return AuthRuntime(self.require_resources()).otp

    def _contact(self, contact: UserContact) -> UserContactResponse:
        return UserContactResponse(
            id=contact.id,
            kind=cast("Literal['email', 'phone']", contact.kind),
            value=str(contact.value),
            verified=contact.verified_at is not None,
            primary=contact.is_primary,
        )

    def _masked(self, identifier: Identifier) -> str:
        if identifier.kind == "email":
            local, domain = identifier.value.split("@", 1)
            return f"{local[:1]}***@{domain}"
        return f"***{identifier.value[-4:]}"

    async def _security_notice(self, user_id: UUID, changed_contact_id: UUID) -> None:
        resources = self.require_resources()
        for contact in await self.contacts(user_id):
            if contact.id != changed_contact_id and contact.verified_at is not None and contact.is_primary:
                enqueue_notification(
                    resources,
                    self.session,
                    Notification(
                        destination=str(contact.value),
                        channel="email" if contact.kind == "email" else "whatsapp",
                        template="contact_changed",
                    ),
                )

    async def _audit(self, action: str, user_id: UUID, target_id: str | None = None) -> None:
        await record(
            self.session,
            AuditEvent(
                action=action,
                actor_type=ActorType.USER,
                actor_user_id=user_id,
                target_type="user",
                target_id=target_id or str(user_id),
            ),
            self.audit_context,
        )
