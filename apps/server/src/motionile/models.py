from motionile.core.db import Base
from motionile.core.idempotency import IdempotencyRecord
from motionile.modules.access import Permission, Role, RolePermission, UserRole
from motionile.modules.audit import AuditLogEntry
from motionile.modules.auth import Credential, OAuthIdentity, Session
from motionile.modules.catalog import CatalogSlugHistory, Category, Topic
from motionile.modules.platform import FeatureFlag, SystemSetting
from motionile.modules.users import User, UserContact, UserPreference

metadata = Base.metadata

__all__ = [
    "AuditLogEntry",
    "CatalogSlugHistory",
    "Category",
    "Credential",
    "FeatureFlag",
    "IdempotencyRecord",
    "OAuthIdentity",
    "Permission",
    "Role",
    "RolePermission",
    "Session",
    "SystemSetting",
    "Topic",
    "User",
    "UserContact",
    "UserPreference",
    "UserRole",
    "metadata",
]
