from motionile.modules.auth.dependencies import (
    CurrentPrincipalDep,
    OptionalPrincipalDep,
    RequireRolesDep,
    enforce_csrf,
    identify_for_rate_limit,
    require_roles,
)
from motionile.modules.auth.exceptions import VerificationRequiredError, verification_required_response
from motionile.modules.auth.models import Credential, OAuthIdentity, Session
from motionile.modules.auth.otp import OtpService
from motionile.modules.auth.router import auth_router
from motionile.modules.auth.runtime import AuthRuntime
from motionile.modules.auth.sessions import active_session_count, revoke_user_sessions, session_families

__all__ = [
    "AuthRuntime",
    "Credential",
    "CurrentPrincipalDep",
    "FakeGrant",
    "FakeOAuthProvider",
    "OAuthIdentity",
    "OptionalPrincipalDep",
    "OtpService",
    "ProviderIdentity",
    "ProviderName",
    "RequireRolesDep",
    "Session",
    "VerificationRequiredError",
    "active_session_count",
    "auth_router",
    "enforce_csrf",
    "identify_for_rate_limit",
    "require_roles",
    "revoke_user_sessions",
    "session_families",
    "verification_required_response",
]

from motionile.modules.auth.oauth.fake import FakeGrant, FakeOAuthProvider
from motionile.modules.auth.oauth.providers import ProviderIdentity, ProviderName
