import motionile.modules.billing.service
from motionile.modules.billing.repository import BillingRepository

from ..billing import repository


class CreditsService:
    def __init__(self) -> None:
        self.billing = motionile.modules.billing.service.BillingService()
        self.repository = BillingRepository()
        self.module = repository
