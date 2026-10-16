from typing import Any

from motionile.entrypoints.api import create_app
from motionile.modules.auth.service import AuthService


def test_every_auth_operation_declares_protections(auth_service: AuthService) -> None:
    schema: dict[str, Any] = create_app(
        auth_service.resources.settings, resources=auth_service.resources, include_test_routes=False
    ).openapi()
    assert not any("_test" in path for path in schema["paths"])
    operations = [
        operation
        for path, methods in schema["paths"].items()
        if path.startswith("/v1/auth/")
        for operation in methods.values()
    ]
    assert len(operations) == 22
    for operation in operations:
        assert operation["x-rate-limit-policy"]
        assert operation["x-csrf-protection"] in {"origin", "session", "refresh", "link", "none"}
        assert operation["x-error-codes"]
    security = schema["components"]["securitySchemes"]
    assert security["SessionCookie"]["name"] == "__Secure-mo_at"
    assert security["RefreshCookie"]["name"] == "__Secure-mo_rt"
    assert security["VerificationTicket"]["name"] == "__Secure-mo_vt"
