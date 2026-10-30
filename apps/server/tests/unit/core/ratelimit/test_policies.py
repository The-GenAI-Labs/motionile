import pytest

from motionile.core.config import RateLimitRuleOverride
from motionile.core.ratelimit.policies import (
    DEFAULT_POLICIES,
    HOUR,
    MINUTE,
    RateLimitScope,
    UnknownPolicyError,
    resolve_policies,
)

CONTEXT_POLICIES = {
    "auth.login": [(5, MINUTE, RateLimitScope.IP_IDENTIFIER), (30, HOUR, RateLimitScope.IP)],
    "auth.otp.send": [
        (1, MINUTE, RateLimitScope.IDENTIFIER),
        (5, HOUR, RateLimitScope.IDENTIFIER),
        (15, HOUR, RateLimitScope.IP),
    ],
    "auth.otp.verify": [(5, 5 * MINUTE, RateLimitScope.IDENTIFIER)],
    "auth.refresh": [(30, MINUTE, RateLimitScope.SESSION)],
    "api.default": [(120, MINUTE, RateLimitScope.USER), (60, MINUTE, RateLimitScope.IP)],
    "catalog.read": [(600, MINUTE, RateLimitScope.IP)],
    "jobs.create": [(5, MINUTE, RateLimitScope.USER)],
    "jobs.write": [(30, MINUTE, RateLimitScope.USER)],
    "share.view": [(120, MINUTE, RateLimitScope.IP)],
    "share.count": [(60, MINUTE, RateLimitScope.IP)],
    "share.manage": [(30, HOUR, RateLimitScope.USER)],
    "billing.order.create": [(10, MINUTE, RateLimitScope.USER)],
    "skills.write": [(20, HOUR, RateLimitScope.USER)],
    "prompts.write": [(20, HOUR, RateLimitScope.USER)],
    "publishing.publish": [(30, HOUR, RateLimitScope.USER)],
    "mcp.submit": [(10, HOUR, RateLimitScope.API_KEY)],
    "webhooks.razorpay": [(600, MINUTE, RateLimitScope.GLOBAL)],
}


@pytest.mark.parametrize(("name", "expected"), CONTEXT_POLICIES.items())
def test_defines_every_policy_from_the_context(name: str, expected: list[tuple[int, int, RateLimitScope]]) -> None:
    policy = resolve_policies({})[name]

    assert [(rule.limit, rule.window_seconds, rule.scope) for rule in policy.rules] == expected


def test_auth_policies_fail_closed_and_others_fail_open() -> None:
    for policy in DEFAULT_POLICIES:
        assert policy.fail_closed == policy.name.startswith("auth.")


def test_default_policy_applies_ip_limit_only_to_anonymous_callers() -> None:
    rules = resolve_policies({})["api.default"].rules

    assert [rule.anonymous_only for rule in rules] == [False, True]


def test_overrides_replace_limits_and_keep_scopes() -> None:
    policies = resolve_policies({"jobs.create": [RateLimitRuleOverride(limit=50, window_seconds=10)]})

    rule = policies["jobs.create"].rules[0]
    assert (rule.limit, rule.window_seconds, rule.scope) == (50, 10, RateLimitScope.USER)


def test_override_for_unknown_policy_is_rejected() -> None:
    with pytest.raises(UnknownPolicyError):
        resolve_policies({"nope": [RateLimitRuleOverride(limit=1, window_seconds=1)]})


def test_override_must_match_rule_count() -> None:
    with pytest.raises(ValueError, match="must list 2 rules"):
        resolve_policies({"auth.login": [RateLimitRuleOverride(limit=1, window_seconds=1)]})
