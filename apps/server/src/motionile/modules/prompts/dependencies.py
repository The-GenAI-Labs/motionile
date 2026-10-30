from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from motionile.core.dependencies import ResourcesDep
from motionile.core.errors import UnauthorizedError
from motionile.modules.access import EvalsRunDep, PromptsManageDep
from motionile.modules.audit import context_from_request
from motionile.modules.prompts.domain import Actor
from motionile.modules.prompts.eval_runs import EvalRunService
from motionile.modules.prompts.factory import build_prompts_service
from motionile.modules.prompts.service import PromptsService
from motionile.modules.prompts.tasks import build_eval_run_service


def get_prompts_service(resources: ResourcesDep) -> PromptsService:
    return build_prompts_service(resources)


def get_eval_run_service(resources: ResourcesDep) -> EvalRunService:
    return build_eval_run_service(resources)


def actor_of(request: Request, user_id: UUID | None) -> Actor:
    if user_id is None:
        raise UnauthorizedError(code="unauthenticated")
    return Actor(user_id, context_from_request(request))


def manager_actor(request: Request, principal: PromptsManageDep) -> Actor:
    return actor_of(request, principal.user_id)


def evaluator_actor(request: Request, principal: EvalsRunDep) -> Actor:
    return actor_of(request, principal.user_id)


PromptsServiceDep = Annotated[PromptsService, Depends(get_prompts_service)]
EvalRunServiceDep = Annotated[EvalRunService, Depends(get_eval_run_service)]
ManagerDep = Annotated[Actor, Depends(manager_actor)]
EvaluatorDep = Annotated[Actor, Depends(evaluator_actor)]
