from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from motionile.core.config import RateLimitRuleOverride

MINUTE = 60
HOUR = 3600


class RateLimitScope(StrEnum):
    IP = "ip"
    USER = "user"
    IP_IDENTIFIER = "ip_identifier"
    IDENTIFIER = "identifier"
    SESSION = "session"
    API_KEY = "api_key"
    GLOBAL = "global"


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_seconds: int
    scope: RateLimitScope
    anonymous_only: bool = False


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    rules: tuple[RateLimitRule, ...]
    fail_closed: bool = False


DEFAULT_POLICIES: tuple[RateLimitPolicy, ...] = (
    RateLimitPolicy(
        "auth.register",
        (RateLimitRule(3, HOUR, RateLimitScope.IP), RateLimitRule(3, HOUR, RateLimitScope.IDENTIFIER)),
        fail_closed=True,
    ),
    RateLimitPolicy("auth.password.change", (RateLimitRule(5, HOUR, RateLimitScope.USER),), fail_closed=True),
    RateLimitPolicy(
        "auth.login",
        (
            RateLimitRule(5, MINUTE, RateLimitScope.IP_IDENTIFIER),
            RateLimitRule(30, HOUR, RateLimitScope.IP),
        ),
        fail_closed=True,
    ),
    RateLimitPolicy(
        "auth.otp.send",
        (
            RateLimitRule(1, MINUTE, RateLimitScope.IDENTIFIER),
            RateLimitRule(5, HOUR, RateLimitScope.IDENTIFIER),
            RateLimitRule(15, HOUR, RateLimitScope.IP),
        ),
        fail_closed=True,
    ),
    RateLimitPolicy("auth.otp.verify", (RateLimitRule(5, 5 * MINUTE, RateLimitScope.IDENTIFIER),), fail_closed=True),
    RateLimitPolicy("auth.refresh", (RateLimitRule(30, MINUTE, RateLimitScope.SESSION),), fail_closed=True),
    RateLimitPolicy(
        "api.default",
        (
            RateLimitRule(120, MINUTE, RateLimitScope.USER),
            RateLimitRule(60, MINUTE, RateLimitScope.IP, anonymous_only=True),
        ),
    ),
    RateLimitPolicy("catalog.read", (RateLimitRule(600, MINUTE, RateLimitScope.IP),)),
    RateLimitPolicy("jobs.create", (RateLimitRule(5, MINUTE, RateLimitScope.USER),)),
    RateLimitPolicy("billing.order.create", (RateLimitRule(10, MINUTE, RateLimitScope.USER),)),
    RateLimitPolicy("skills.write", (RateLimitRule(20, HOUR, RateLimitScope.USER),)),
    RateLimitPolicy("publishing.publish", (RateLimitRule(30, HOUR, RateLimitScope.USER),)),
    RateLimitPolicy("mcp.submit", (RateLimitRule(10, HOUR, RateLimitScope.API_KEY),)),
    RateLimitPolicy("webhooks.razorpay", (RateLimitRule(600, MINUTE, RateLimitScope.GLOBAL),)),
    RateLimitPolicy("test.limited", (RateLimitRule(3, 10, RateLimitScope.IP),)),
)


class UnknownPolicyError(KeyError):
    def __init__(self, name: str) -> None:
        super().__init__(f"unknown rate-limit policy {name!r}")


def apply_overrides(policy: RateLimitPolicy, overrides: Sequence[RateLimitRuleOverride]) -> RateLimitPolicy:
    if len(overrides) != len(policy.rules):
        message = f"override for {policy.name!r} must list {len(policy.rules)} rules"
        raise ValueError(message)
    rules = tuple(
        replace(rule, limit=override.limit, window_seconds=override.window_seconds)
        for rule, override in zip(policy.rules, overrides, strict=True)
    )
    return replace(policy, rules=rules)


def resolve_policies(overrides: Mapping[str, Sequence[RateLimitRuleOverride]]) -> dict[str, RateLimitPolicy]:
    policies = {policy.name: policy for policy in DEFAULT_POLICIES}
    for name, rules in overrides.items():
        if name not in policies:
            raise UnknownPolicyError(name)
        policies[name] = apply_overrides(policies[name], rules)
    return policies
