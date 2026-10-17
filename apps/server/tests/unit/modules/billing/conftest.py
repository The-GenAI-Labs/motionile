from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from tests.fakes.billing import BillingWorld, FakeBillingStore
from tests.fakes.credits import FakeAudit, FakeCreditsStore
from tests.fakes.razorpay import InMemoryFakeRazorpayStore
from tests.fakes.settings import make_settings

from motionile.core.clock import FrozenClock
from motionile.core.ids import new_id
from motionile.modules.billing.razorpay.fake import FakeRazorpay
from motionile.modules.billing.razorpay.fake_simulator import FakeRazorpaySimulator, PaymentOutcome
from motionile.modules.billing.razorpay.models import RazorpayPayment
from motionile.modules.billing.records import NewOrder, OrderRecord, ProductRecord
from motionile.modules.billing.services.settlement import SettlementPorts, SettlementService
from motionile.modules.billing.states import OrderStatus
from motionile.modules.credits import CreditsService

START = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
PACK_PRICE = 19_900
PACK_CREDITS = 100


def pack_product(*, code: str = "pack_starter", active: bool = True, kind: str = "credit_pack") -> ProductRecord:
    return ProductRecord(
        id=new_id(),
        code=code,
        kind=kind,
        plan_key=None if kind == "credit_pack" else "pro",
        name="Starter",
        description="100 credits",
        price_paise=PACK_PRICE,
        currency="INR",
        interval=None if kind == "credit_pack" else "month",
        credits_granted=PACK_CREDITS,
        razorpay_plan_id=None if kind == "credit_pack" else "plan_fake",
        is_active=active,
        is_sample=False,
        sort_order=10,
        features=("100 credits",),
        version=1,
    )


class BillingHarness:
    def __init__(self) -> None:
        self.clock = FrozenClock(START)
        self.billing = FakeBillingStore(self.clock)
        self.credits_store = FakeCreditsStore(self.clock)
        self.audit = FakeAudit()
        self.world = BillingWorld(
            clock=self.clock,
            billing=self.billing,
            credits=self.credits_store,
            audit=self.audit,
            alerts=[],
            receipts=[],
        )
        self.razorpay_store = InMemoryFakeRazorpayStore()
        self.razorpay = FakeRazorpay(self.razorpay_store, self.clock)
        self.simulator = FakeRazorpaySimulator(self.razorpay_store, self.clock)
        self.settings = make_settings().billing
        self.credits = CreditsService(self.clock, self.settings, store_factory=self.credits_store, audit=self.audit)
        self.settlement = SettlementService(
            self.clock,
            self.credits,
            self.world.send_receipt,
            SettlementPorts(store_factory=self.billing, audit=self.audit, alert=self.world.alert),
        )
        self.user_id = new_id()
        self.product = self.billing.add_product(pack_product())
        self.counter = 0

    def audit_actions(self) -> list[str]:
        return [event.action for event in self.audit.events]

    async def local_order(self, *, user_id: UUID | None = None, product: ProductRecord | None = None) -> OrderRecord:
        self.counter += 1
        created = await self.billing.insert_order(
            NewOrder(
                id=new_id(),
                user_id=user_id or self.user_id,
                product=product or self.product,
                idempotency_key=f"key-{self.counter}",
                expires_at=self.clock.now() + timedelta(seconds=self.settings.order_expiry_seconds),
            )
        )
        assert created is not None
        return created

    async def open_order(
        self, *, user_id: UUID | None = None, status: OrderStatus = OrderStatus.PENDING
    ) -> OrderRecord:
        order = await self.local_order(user_id=user_id)
        remote = await self.razorpay.create_order(
            amount=order.amount_paise, currency=order.currency, receipt=order.receipt
        )
        opened = replace(order, status=status, razorpay_order_id=remote.id)
        self.billing.orders[order.id] = opened
        return opened

    async def pay(
        self,
        order: OrderRecord,
        outcome: PaymentOutcome = PaymentOutcome.SUCCESS,
        *,
        amount: int | None = None,
        currency: str | None = None,
    ) -> RazorpayPayment:
        assert order.razorpay_order_id is not None
        result = await self.simulator.pay_order(order.razorpay_order_id, outcome, amount=amount, currency=currency)
        return RazorpayPayment.model_validate(result.payment)

    def balance(self, user_id: UUID | None = None) -> int:
        wallet = self.credits_store.wallets.get(user_id or self.user_id)
        return wallet.balance if wallet is not None else 0


@pytest.fixture
def billing_harness() -> BillingHarness:
    return BillingHarness()
