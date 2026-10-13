from motionile.modules import billing
from motionile.modules.billing import BillingService

from .repository import CreditsRepository


class CreditsService:
    def __init__(self) -> None:
        self.billing = BillingService()
        self.module = billing
        self.repository = CreditsRepository()
