from typing import ClassVar
from uuid import UUID

from motionile.core.events import DomainEvent


class UserRegistered(DomainEvent):
    name: ClassVar[str] = "user.registered"
    user_id: UUID


class ContactVerified(DomainEvent):
    name: ClassVar[str] = "contact.verified"
    user_id: UUID


class UserSignedIn(DomainEvent):
    name: ClassVar[str] = "user.signed_in"
    user_id: UUID
    family_id: UUID


class PasswordChanged(DomainEvent):
    name: ClassVar[str] = "password.changed"
    user_id: UUID


class SessionFamilyRevoked(DomainEvent):
    name: ClassVar[str] = "session.family_revoked"
    user_id: UUID
    family_id: UUID
    reason: str


class RefreshTokenReuseDetected(DomainEvent):
    name: ClassVar[str] = "refresh.reuse_detected"
    user_id: UUID
    family_id: UUID


class OAuthIdentityLinked(DomainEvent):
    name: ClassVar[str] = "oauth.identity_linked"
    user_id: UUID
    provider: str
