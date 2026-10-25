from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute

from motionile.core.openapi import operation_id
from motionile.core.tasks.registry import TASK_MODULES
from motionile.modules.access import RequirePermission
from motionile.modules.auth import enforce_csrf
from motionile.modules.prompts import admin_prompts_router

EXPECTED = {
    ("GET", "/admin/prompts/templates"): ("admin_prompts_list_prompt_templates", 200, "prompts.manage", False),
    ("GET", "/admin/prompts/templates/{key}/versions"): (
        "admin_prompts_list_prompt_versions",
        200,
        "prompts.manage",
        False,
    ),
    ("GET", "/admin/prompts/templates/{key}/diff"): (
        "admin_prompts_diff_prompt_versions",
        200,
        "prompts.manage",
        False,
    ),
    ("POST", "/admin/prompts/templates/{key}/versions"): (
        "admin_prompts_create_prompt_draft",
        201,
        "prompts.manage",
        True,
    ),
    ("POST", "/admin/prompts/templates/{key}/versions/{version}/activate"): (
        "admin_prompts_activate_prompt_version",
        200,
        "prompts.manage",
        True,
    ),
    ("POST", "/admin/prompts/templates/{key}/rollback"): (
        "admin_prompts_rollback_prompt_template",
        200,
        "prompts.manage",
        True,
    ),
    ("POST", "/admin/prompts/eval-runs"): ("admin_prompts_start_eval_run", 202, "evals.run", True),
    ("GET", "/admin/prompts/eval-runs"): ("admin_prompts_list_eval_runs", 200, "prompts.manage", False),
    ("GET", "/admin/prompts/eval-runs/{run_id}"): ("admin_prompts_get_eval_run", 200, "prompts.manage", False),
}


def dependency_calls(dependant: Dependant) -> list[object]:
    calls: list[object] = []
    for sub in dependant.dependencies:
        calls.append(sub.call)
        calls.extend(dependency_calls(sub))
    return calls


def routes() -> dict[tuple[str, str], APIRoute]:
    found: dict[tuple[str, str], APIRoute] = {}
    for route in admin_prompts_router.routes:
        assert isinstance(route, APIRoute)
        assert route.methods is not None
        for method in route.methods:
            found[(method, route.path)] = route
    return found


def test_the_admin_routes_are_exactly_the_documented_set() -> None:
    assert set(routes()) == set(EXPECTED)


def test_every_route_declares_its_operation_status_permission_and_rate_limits() -> None:
    for key, route in routes().items():
        name, status_code, permission, writes = EXPECTED[key]
        calls = dependency_calls(route.dependant)
        names = {getattr(call, "__name__", "") for call in calls}
        permissions = {call.permission for call in calls if isinstance(call, RequirePermission)}
        assert operation_id(route) == name
        assert route.status_code == status_code
        assert route.response_model is not None
        assert route.summary
        assert permissions == {permission}, key
        assert enforce_csrf in calls
        assert "rate_limit_api_default" in names
        assert ("rate_limit_prompts_write" in names) is writes, key


def test_the_eval_task_is_registered_with_the_worker() -> None:
    assert "motionile.modules.prompts.tasks" in TASK_MODULES
