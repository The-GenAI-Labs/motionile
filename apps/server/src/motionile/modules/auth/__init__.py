from motionile.modules.auth.dependencies import (
    CurrentPrincipalDep,
    OptionalPrincipalDep,
    RequireRolesDep,
    identify_for_rate_limit,
    require_roles,
)
from motionile.modules.auth.exceptions import VerificationRequiredError, verification_required_response
from motionile.modules.auth.models import Credential, OAuthIdentity, Session
from motionile.modules.auth.router import auth_router
from motionile.modules.auth.runtime import AuthRuntime

__all__ = [
    "AuthRuntime",
    "Credential",
    "CurrentPrincipalDep",
    "FakeGrant",
    "FakeOAuthProvider",
    "OAuthIdentity",
    "OptionalPrincipalDep",
    "ProviderIdentity",
    "ProviderName",
    "RequireRolesDep",
    "Session",
    "VerificationRequiredError",
    "auth_router",
    "identify_for_rate_limit",
    "require_roles",
    "verification_required_response",
]

from motionile.modules.auth.oauth.fake import FakeGrant, FakeOAuthProvider
from motionile.modules.auth.oauth.providers import ProviderIdentity, ProviderName
