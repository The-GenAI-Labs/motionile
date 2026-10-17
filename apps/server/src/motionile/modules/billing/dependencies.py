from typing import Annotated

from fastapi import Depends

from motionile.core.dependencies import ResourcesDep
from motionile.modules.billing.razorpay.api import RazorpayApi
from motionile.modules.billing.razorpay.factory import razorpay_for


def get_razorpay(resources: ResourcesDep) -> RazorpayApi:
    return razorpay_for(resources)


RazorpayDep = Annotated[RazorpayApi, Depends(get_razorpay)]
