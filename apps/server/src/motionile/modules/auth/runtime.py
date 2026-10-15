from motionile.core.resources import Resources
from motionile.core.security.csrf import CsrfTokens
from motionile.core.security.jwt import AccessTokens
from motionile.core.security.passwords import Passwords
from motionile.modules.auth.otp import OtpService
from motionile.modules.notifications import Notifications


class AuthRuntime:
    def __init__(self, resources: Resources) -> None:
        self.resources = resources
        self.tokens = AccessTokens(resources.settings.auth, resources.clock, resources.redis_store)
        self.csrf = CsrfTokens(resources.settings.auth.secret("csrf"))
        self.passwords = Passwords(
            resources.provider_clients["hibp"],
            check_breaches=resources.settings.auth.hibp_enabled and not resources.settings.is_fake_providers,
        )
        self.otp = OtpService(resources.redis_store, resources.clock, resources.settings.auth.secret("otp"))
        self.notifications = Notifications(resources)
