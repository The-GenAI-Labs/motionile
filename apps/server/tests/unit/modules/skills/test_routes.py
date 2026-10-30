from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from motionile.core.openapi import operation_id
from motionile.modules.access import RequirePermission
from motionile.modules.auth import enforce_csrf
from motionile.modules.skills import admin_skills_router

EXPECTED = {
    ("GET", "/admin/skills"): ("admin_skills_list_system_skills", 200, False),
    ("GET", "/admin/skills/{slug}"): ("admin_skills_get_system_skill", 200, False),
    ("POST", "/admin/skills/reseed"): ("admin_skills_reseed_system_skills", 202, True),
}


def dependency_calls(dependant: Dependant) -> list[object]:
    calls: list[object] = []
    for sub in dependant.dependencies:
        calls.append(sub.call)
        calls.extend(dependency_calls(sub))
    return calls


def routes() -> dict[tuple[str, str], APIRoute]:
    found: dict[tuple[str, str], APIRoute] = {}
    for route in admin_skills_router.routes:
        assert isinstance(route, APIRoute)
        assert route.methods is not None
        for method in route.methods:
            found[(method, route.path)] = route
    return found


def test_the_admin_routes_are_exactly_the_documented_set() -> None:
    assert set(routes()) == set(EXPECTED)
    assert admin_skills_router.tags == ["admin-skills"]


def test_every_route_declares_its_operation_status_permission_and_rate_limits() -> None:
    for key, route in routes().items():
        name, status_code, writes = EXPECTED[key]
        calls = dependency_calls(route.dependant)
        names = {getattr(call, "__name__", "") for call in calls}
        permissions = {call.permission for call in calls if isinstance(call, RequirePermission)}
        assert operation_id(route) == name
        assert route.status_code == status_code
        assert route.response_model is not None
        assert route.summary
        assert permissions == {"skills.manage"}, key
        assert enforce_csrf in calls
        assert "rate_limit_api_default" in names
        assert ("rate_limit_skills_write" in names) is writes, key
