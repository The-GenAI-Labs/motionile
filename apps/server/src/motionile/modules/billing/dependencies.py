from typing import Annotated
from uuid import UUID

from fastapi import Depends

from motionile.core.dependencies import ResourcesDep
from motionile.core.errors import UnauthorizedError
from motionile.modules.auth import CurrentPrincipalDep
from motionile.modules.billing.razorpay.api import RazorpayApi
from motionile.modules.billing.razorpay.factory import razorpay_for
from motionile.modules.billing.services.factory import BillingServices, build_services
from motionile.modules.billing.tasks import worker_hooks

SERVICES_KEY = "billing.services"


def get_razorpay(resources: ResourcesDep) -> RazorpayApi:
    return razorpay_for(resources)


def get_billing_services(resources: ResourcesDep) -> BillingServices:
    return resources.shared_instance(SERVICES_KEY, lambda: build_services(resources, worker_hooks()))


def get_current_user_id(principal: CurrentPrincipalDep) -> UUID:
    if principal.user_id is None:
        raise UnauthorizedError(code="unauthenticated")
    return principal.user_id


RazorpayDep = Annotated[RazorpayApi, Depends(get_razorpay)]
BillingServicesDep = Annotated[BillingServices, Depends(get_billing_services)]
CurrentUserIdDep = Annotated[UUID, Depends(get_current_user_id)]
