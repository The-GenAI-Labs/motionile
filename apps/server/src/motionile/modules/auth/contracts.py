from typing import Literal


def protection(
    policy: str,
    *,
    csrf: Literal["origin", "session", "refresh", "link", "none"],
    errors: dict[int, list[str]],
    turnstile: str | None = None,
    cookie: str | None = None,
) -> dict[str, object]:
    common = {
        422: ["validation_failed", "invalid_identifier"],
        429: ["rate_limited", "otp_cooldown"],
        503: ["service_unavailable"],
    }
    for status, codes in errors.items():
        common.setdefault(status, []).extend(codes)
    if csrf != "none":
        common.setdefault(403, []).extend(["origin_forbidden", "origin_not_allowed", "csrf_failed"])
    if turnstile:
        common.setdefault(400, []).append("turnstile_required")
        common.setdefault(403, []).append("turnstile_failed")
        common.setdefault(503, []).append("turnstile_unavailable")
    result: dict[str, object] = {
        "x-rate-limit-policy": policy,
        "x-turnstile-action": turnstile,
        "x-csrf-protection": csrf,
        "x-required-cookie": cookie,
        "x-error-codes": {str(status): sorted(set(codes)) for status, codes in common.items()},
    }
    if csrf == "link" or cookie == "__Secure-mo_oauth":
        result["security"] = [{}, {"SessionCookie": []}]
    return result
